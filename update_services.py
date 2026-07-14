"""Download and combine GC Service Inventory and org data into services.json.

Steps:
1. Download service.csv (GC Service Inventory, pinned fiscal year list).
2. Filter to the pinned fiscal year.
3. Validate service_id uniqueness and that every service has both names.
4. Resolve unique org names via gcorg-resolver -> org lookup table.
5. Join org info onto service rows and parse program IDs.
6. Write services.json.
"""

import json
from pathlib import Path
from urllib.request import urlopen

import pandas as pd
import requests

# Pinned to a fiscal year of the GC Service Inventory. Rolling to a new year is
# a manual, deliberate edit to SOURCE_FISCAL_YEAR - the CSV carries several
# years at once, so the year has to be filtered, not just the URL swapped.
SERVICE_CSV_URL = (
    "https://open.canada.ca/data/dataset/3ac0d080-6149-499a-8b06-7ce5f00ec56c/"
    "resource/c0cf9766-b85b-48c3-b295-34f72305aaf6/download/service.csv"
)
SOURCE_FISCAL_YEAR = "2024-2025"
SOURCE_DATASET_URL = "https://open.canada.ca/data/en/dataset/3ac0d080-6149-499a-8b06-7ce5f00ec56c"

GCORG_RESOLVER_URL = "https://gcorgs.cdssandbox.xyz/resolve"
RESOLVER_BATCH_SIZE = 1000
OUT_PATH = Path(__file__).parent / "services.json"

FISCAL_YR_COL = "fiscal_yr"
SERVICE_ID_COL = "service_id"
SERVICE_NAME_EN_COL = "service_name_en"
SERVICE_NAME_FR_COL = "service_name_fr"
PROGRAM_ID_COL = "program_id"
ORG_TITLE_COL = "owner_org_title"

# owner_org_title holds "English name | Nom français" in a single cell. The
# resolver only takes the EN half; the FR name comes back from the resolver so
# it stays the single source of truth for org naming.
ORG_TITLE_SEPARATOR = " | "


def download_csv(url: str) -> pd.DataFrame:
    """Download a CSV from url and return it as a DataFrame."""
    with urlopen(url) as response:
        body = response.read()
    return pd.read_csv(pd.io.common.BytesIO(body), encoding="utf-8-sig", dtype=str)


def filter_fiscal_year(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only rows for the pinned fiscal year.

    Raises ValueError if the pinned year isn't in the file. Without this guard a
    roll-forward that drops the pinned year would silently write an empty
    services.json and the weekly job would commit it.
    """
    present = sorted(df[FISCAL_YR_COL].dropna().unique())
    if SOURCE_FISCAL_YEAR not in present:
        raise ValueError(
            f"Pinned fiscal year {SOURCE_FISCAL_YEAR!r} is not in the source data. "
            f"Years present: {present}. Update SOURCE_FISCAL_YEAR."
        )
    return df[df[FISCAL_YR_COL] == SOURCE_FISCAL_YEAR].reset_index(drop=True)


def validate_unique_service_ids(df: pd.DataFrame) -> None:
    """Raise ValueError if service_id isn't unique within the pinned fiscal year."""
    duplicated = df[df[SERVICE_ID_COL].duplicated()][SERVICE_ID_COL]
    if not duplicated.empty:
        raise ValueError(
            f"Duplicate service_id in {SOURCE_FISCAL_YEAR}: {sorted(duplicated.unique())}"
        )


def validate_names_present(df: pd.DataFrame) -> None:
    """Raise ValueError if any service is missing an EN or FR name.

    A missing name would serialize as NaN - invalid JSON that breaks the site at
    load time - so fail loudly at build time instead.
    """
    missing = df[df[SERVICE_NAME_EN_COL].isna() | df[SERVICE_NAME_FR_COL].isna()]
    if not missing.empty:
        raise ValueError(
            f"Services missing an EN or FR name: {sorted(missing[SERVICE_ID_COL].unique())}"
        )


def split_org_title(title: str) -> tuple[str, str]:
    """Split an owner_org_title into its (EN, FR) halves.

    Raises ValueError if the title isn't exactly two non-empty parts.
    """
    parts = [part.strip() for part in str(title).split(ORG_TITLE_SEPARATOR)]
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"Malformed owner_org_title: {title!r}")
    return parts[0], parts[1]


def parse_program_ids(value) -> list[str] | None:
    """Parse a comma-separated program_id cell into a list, or None when empty.

    We return None rather than [] for the empty case so the site keeps rendering
    its "no program" string for services with no program IDs.
    """
    if pd.isna(value):
        return None
    ids = [pid.strip() for pid in str(value).split(",") if pid.strip()]
    return ids or None


def resolve_orgs(org_names: list[str]) -> dict[str, dict]:
    """Resolve org names to gc_orgID and canonical bilingual names via gcorg-resolver.

    Returns {input_name: {gc_orgID, org_name_en, org_name_fr}}.
    Raises ValueError if any org name cannot be resolved.
    Batches requests if org_names exceeds RESOLVER_BATCH_SIZE.
    """
    lookup = {}
    for i in range(0, max(len(org_names), 1), RESOLVER_BATCH_SIZE):
        batch = org_names[i : i + RESOLVER_BATCH_SIZE]
        response = requests.post(
            GCORG_RESOLVER_URL,
            json={"names": batch},
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()
        for result in response.json()["results"]:
            if result["matched"]:
                lookup[result["input"]] = {
                    "gc_orgID": result["gc_orgID"],
                    "org_name_en": result["harmonized_name"],
                    "org_name_fr": result["nom_harmonise"],
                    "acronym_en": result.get("abbreviation"),
                    "acronym_fr": result.get("abreviation"),
                }
            else:
                raise ValueError(f"gcorg-resolver could not match org: '{result['input']}'")
    return lookup


def build_records(services: pd.DataFrame, org_lookup: dict[str, dict]) -> list[dict]:
    """Join org data onto each service row and return as a list of dicts."""
    records = []
    for _, row in services.iterrows():
        org_name_en, _ = split_org_title(row[ORG_TITLE_COL])
        org = org_lookup.get(org_name_en, {})
        records.append(
            {
                "service_id": str(row[SERVICE_ID_COL]),
                "service_en": row[SERVICE_NAME_EN_COL].strip(),
                "service_fr": row[SERVICE_NAME_FR_COL].strip(),
                "gc_orgID": org.get("gc_orgID"),
                "org_name_en": org.get("org_name_en", org_name_en),
                "org_name_fr": org.get("org_name_fr"),
                "acronym_en": org.get("acronym_en"),
                "acronym_fr": org.get("acronym_fr"),
                "program_id": parse_program_ids(row[PROGRAM_ID_COL]),
            }
        )
    return records


def update_generated_at(records: list[dict], path: Path) -> str:
    """Return the generated_at timestamp to write.

    Reuse the existing file's timestamp when the records are unchanged, so the
    file (and the "last updated" date the site shows) only moves when the source
    data actually changes. The source block is deliberately excluded from the
    comparison so it can't force a timestamp bump on its own.
    """
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}
        if existing.get("services") == records and existing.get("generated_at"):
            return existing["generated_at"]
    return pd.Timestamp.now(tz="UTC").isoformat()


def write_json(records: list[dict], path: Path) -> None:
    output = {
        "generated_at": update_generated_at(records, path),
        "source": {
            "fiscal_year": SOURCE_FISCAL_YEAR,
            "dataset_url": SOURCE_DATASET_URL,
            "csv": SERVICE_CSV_URL,
        },
        "services": records,
    }
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(records):,} records to {path}")


if __name__ == "__main__":
    print("Downloading service inventory...")
    services = download_csv(SERVICE_CSV_URL)
    print(f"  {len(services):,} rows")

    print(f"Filtering to fiscal year {SOURCE_FISCAL_YEAR}...")
    services = filter_fiscal_year(services)
    print(f"  {len(services):,} rows")

    print("Validating service rows...")
    validate_unique_service_ids(services)
    validate_names_present(services)

    print("Resolving org names...")
    unique_orgs = sorted({split_org_title(title)[0] for title in services[ORG_TITLE_COL]})
    print(f"  {len(unique_orgs):,} unique orgs")
    org_lookup = resolve_orgs(unique_orgs)

    print("Building output records...")
    records = build_records(services, org_lookup)

    write_json(records, OUT_PATH)
