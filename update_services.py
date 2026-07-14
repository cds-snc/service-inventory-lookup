"""Download and combine GC Service Inventory and org data into services.json.

Steps:
1. Download service.csv (GC Service Inventory, pinned fiscal year list).
2. Download the published schema for the bilingual classification code labels.
3. Filter to the pinned fiscal year.
4. Validate service_id uniqueness and that every service has both names.
5. Resolve unique org names via gcorg-resolver -> org lookup table.
6. Join org info onto service rows, pair program IDs with their names, and
   label the classification codes.
7. Write services.json.
"""

import csv
import io
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

# The schema is the published code table for the classification fields. We read
# the labels from it rather than hardcoding them so the wording stays the
# publisher's. It describes the current schema, so it is not year-pinned.
SERVICE_SCHEMA_URL = "https://open.canada.ca/data/recombinant-published-schema/service.json"

GCORG_RESOLVER_URL = "https://gcorgs.cdssandbox.xyz/resolve"
RESOLVER_BATCH_SIZE = 1000
OUT_PATH = Path(__file__).parent / "services.json"

FISCAL_YR_COL = "fiscal_yr"
SERVICE_ID_COL = "service_id"
SERVICE_NAME_EN_COL = "service_name_en"
SERVICE_NAME_FR_COL = "service_name_fr"
PROGRAM_ID_COL = "program_id"
PROGRAM_NAME_EN_COL = "program_name_en"
PROGRAM_NAME_FR_COL = "program_name_fr"
SERVICE_URI_EN_COL = "service_uri_en"
SERVICE_URI_FR_COL = "service_uri_fr"
ORG_TITLE_COL = "owner_org_title"

# Classification fields, each a comma-separated list of codes the schema defines
# labels for.
CLASSIFICATION_COLS = [
    "service_type",
    "service_scope",
    "client_target_groups",
    "service_recipient_type",
]

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

    Raises ValueError if the pinned year isn't in the file.
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
    """Raise ValueError if any service is missing an EN or FR name."""
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


def parse_list_cell(value) -> list[str]:
    """Parse one of the source's comma-separated cells into a list of values.

    Parsed as CSV rather than split on "," because program_name_en/fr quote each
    value ('"Business Growth", "Trade and Investment"') and some names contain
    a comma of their own. Splitting naively misaligns them against program_id.
    """
    if pd.isna(value):
        return []
    row = next(csv.reader(io.StringIO(str(value)), skipinitialspace=True), [])
    return [item.strip() for item in row if item.strip()]


def parse_programs(row) -> list[dict] | None:
    """Pair a row's program IDs with their bilingual names.

    Returns None rather than [] when the service has no programs, so the site can
    tell "no programs" apart from a program with no name.
    Raises ValueError if the ID and name lists don't line up.
    """
    ids = parse_list_cell(row[PROGRAM_ID_COL])
    names_en = parse_list_cell(row[PROGRAM_NAME_EN_COL])
    names_fr = parse_list_cell(row[PROGRAM_NAME_FR_COL])
    if not ids:
        return None
    if not len(ids) == len(names_en) == len(names_fr):
        raise ValueError(
            f"Service {row[SERVICE_ID_COL]} has {len(ids)} program IDs but "
            f"{len(names_en)} EN and {len(names_fr)} FR program names."
        )
    return [
        {"program_id": pid, "program_name_en": name_en, "program_name_fr": name_fr}
        for pid, name_en, name_fr in zip(ids, names_en, names_fr)
    ]


def parse_uri(value) -> str | None:
    """Return a service URL, or None when the source leaves it blank.

    13% of services have no URL, so the site has to render the row without a link
    rather than show an empty one.
    """
    if pd.isna(value) or not str(value).strip():
        return None
    return str(value).strip()


def fetch_code_labels(url: str) -> dict[str, dict[str, dict]]:
    """Return {field_id: {code: {"en": label, "fr": label}}} for the classification fields."""
    with urlopen(url) as response:
        schema = json.loads(response.read())
    labels = {}
    for resource in schema["resources"]:
        for field in resource["fields"]:
            if field["id"] in CLASSIFICATION_COLS and "choices" in field:
                labels[field["id"]] = field["choices"]
    missing = set(CLASSIFICATION_COLS) - set(labels)
    if missing:
        raise ValueError(f"Schema has no choices for: {sorted(missing)}")
    return labels


def label_codes(value, field: str, code_labels: dict[str, dict[str, dict]]) -> list[dict]:
    """Expand a classification cell into [{code, name_en, name_fr}, ...].

    Raises ValueError on a code the schema doesn't define, so a vocabulary change
    surfaces at build time instead of rendering a blank label on the page.
    """
    choices = code_labels[field]
    labelled = []
    for code in parse_list_cell(value):
        if code not in choices:
            raise ValueError(f"{field} code {code!r} is not in the published schema.")
        labelled.append(
            {
                "code": code,
                "name_en": choices[code]["en"],
                "name_fr": choices[code]["fr"],
            }
        )
    return labelled


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


def build_records(
    services: pd.DataFrame,
    org_lookup: dict[str, dict],
    code_labels: dict[str, dict[str, dict]],
) -> list[dict]:
    """Join org data onto each service row and return as a list of dicts."""
    records = []
    for _, row in services.iterrows():
        org_name_en, _ = split_org_title(row[ORG_TITLE_COL])
        org = org_lookup.get(org_name_en, {})
        record = {
            "service_id": str(row[SERVICE_ID_COL]),
            "service_en": row[SERVICE_NAME_EN_COL].strip(),
            "service_fr": row[SERVICE_NAME_FR_COL].strip(),
            "gc_orgID": org.get("gc_orgID"),
            "org_name_en": org.get("org_name_en", org_name_en),
            "org_name_fr": org.get("org_name_fr"),
            "acronym_en": org.get("acronym_en"),
            "acronym_fr": org.get("acronym_fr"),
            "service_uri_en": parse_uri(row[SERVICE_URI_EN_COL]),
            "service_uri_fr": parse_uri(row[SERVICE_URI_FR_COL]),
            "programs": parse_programs(row),
        }
        for field in CLASSIFICATION_COLS:
            record[field] = label_codes(row[field], field, code_labels)
        records.append(record)
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

    print("Downloading published schema...")
    code_labels = fetch_code_labels(SERVICE_SCHEMA_URL)
    print(f"  {sum(len(c) for c in code_labels.values()):,} classification codes")

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
    records = build_records(services, org_lookup, code_labels)

    write_json(records, OUT_PATH)
