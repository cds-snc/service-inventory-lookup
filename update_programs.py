"""Download and reshape PSPC Program Inventory data into program_codes.json.

Steps:
1. Download the bilingual Program codes CSV (pinned fiscal year list).
2. Filter to Program Inventory rows (non-blank program-inventory code).
3. Validate every program code matches the [A-Z]{3}[0-9A-Z]{2} format.
4. Resolve unique department names via gcorg-resolver -> org lookup.
5. Build records keyed on (gc_orgID, PROG), composing program_code_id.
6. Write program_codes.json.
"""

import json
import re
from pathlib import Path
from urllib.request import urlopen

import pandas as pd
import requests

# Pinned to a fiscal year's Program codes list. Rolling to a new year is a
# manual, deliberate edit to these three constants - see the data-source
# section of docs/program-codes-spec.md. No auto-discovery.
PROGRAM_CODES_URL = "https://donnees-data.tpsgc-pwgsc.gc.ca/ba1/cp-pc/cp-pc-2627.csv"
SOURCE_FISCAL_YEAR = "2026-27"
SOURCE_DATASET_URL = "https://open.canada.ca/data/en/dataset/3c371e57-d487-49fa-bb0d-352ae8dd6e4e"

GCORG_RESOLVER_URL = "https://gcorgs.cdssandbox.xyz/resolve"
RESOLVER_BATCH_SIZE = 1000
OUT_PATH = Path(__file__).parent / "program_codes.json"

# Only the English department name is resolved: gcorg-resolver returns both
# languages for a match, so the French column carries no extra information.
DEPT_COL_EN = "Entity_Entite_eng"
PROG_CODE_COL = "Prog-inv-code_Code-rep-prog"
NAME_COLS = {
    "program_name_en": "Prog-inv-name_Nom-rep-prog_eng",
    "program_name_fr": "Prog-inv-name_Nom-rep-prog_fra",
    "core_responsibility_en": "Prog-core-resp-name_Nom-prog-resp-essent_eng",
    "core_responsibility_fr": "Prog-core-resp-name_Nom-prog-resp-essent_fra",
}

# 3 letters + 2 alphanumeric characters. Not always digits: ISS0Z/ISS1Z exist
# (internal services, the 10th slot uses Z).
PROG_CODE_PATTERN = re.compile(r"^[A-Z]{3}[0-9A-Z]{2}$")


def download_csv(url: str) -> pd.DataFrame:
    """Download a CSV from url and return it as a DataFrame."""
    with urlopen(url) as response:
        body = response.read()
    return pd.read_csv(pd.io.common.BytesIO(body), encoding="utf-8-sig")


def filter_program_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Drop core-responsibility rows and rows with no Program Inventory code."""
    mask = df[PROG_CODE_COL].fillna("").str.strip() != ""
    return df[mask].reset_index(drop=True)


def validate_prog_codes(df: pd.DataFrame) -> None:
    """Raise ValueError if any Program Inventory code doesn't match the expected format."""
    codes = df[PROG_CODE_COL].str.strip()
    bad = codes[~codes.str.match(PROG_CODE_PATTERN)]
    if not bad.empty:
        raise ValueError(f"Program codes with unexpected format: {sorted(bad.unique())}")


def validate_names_present(df: pd.DataFrame) -> None:
    """Raise ValueError if any Program Inventory row is missing a name in either language.

    A missing name would serialize as NaN - invalid JSON that breaks the site
    at load time - so fail loudly at build time instead.
    """
    blank = df[list(NAME_COLS.values())].isna().any(axis=1)
    if blank.any():
        codes = sorted(df[blank][PROG_CODE_COL].str.strip().unique())
        raise ValueError(f"Program rows missing a program or core-responsibility name: {codes}")


def resolve_orgs(org_names: list[str]) -> dict[str, dict]:
    """Resolve org names to gc_orgID and canonical bilingual names via gcorg-resolver.

    Returns {input_name: {gc_orgID, org_name_en, org_name_fr, acronym_en, acronym_fr}}.
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


def build_records(df: pd.DataFrame, org_lookup: dict[str, dict]) -> list[dict]:
    """Build the final program_codes.json record list from the filtered DataFrame.

    Raises ValueError if (gc_orgID, PROG) is not unique, since that key is what
    program_code_id is composed from.
    """
    records = {}
    for _, row in df.iterrows():
        org = org_lookup[row[DEPT_COL_EN]]
        prog = row[PROG_CODE_COL].strip()
        key = (org["gc_orgID"], prog)
        if key in records:
            raise ValueError(f"Duplicate (gc_orgID, PROG) key: {key}")
        records[key] = {
            "program_code_id": f"{org['gc_orgID']}-{prog}",
            "prog_code": prog,
            **{field: row[col].strip() for field, col in NAME_COLS.items()},
            "gc_orgID": org["gc_orgID"],
            "org_name_en": org["org_name_en"],
            "org_name_fr": org["org_name_fr"],
            "acronym_en": org["acronym_en"],
            "acronym_fr": org["acronym_fr"],
        }
    return [records[key] for key in sorted(records)]


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
        if existing.get("programs") == records and existing.get("generated_at"):
            return existing["generated_at"]
    return pd.Timestamp.now(tz="UTC").isoformat()


def write_json(records: list[dict], path: Path) -> None:
    output = {
        "generated_at": update_generated_at(records, path),
        "source": {
            "fiscal_year": SOURCE_FISCAL_YEAR,
            "dataset_url": SOURCE_DATASET_URL,
            "csv": PROGRAM_CODES_URL,
        },
        "programs": records,
    }
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(records):,} records to {path}")


if __name__ == "__main__":
    print("Downloading program codes...")
    df = download_csv(PROGRAM_CODES_URL)
    print(f"  {len(df):,} rows")

    print("Filtering to Program Inventory rows...")
    df = filter_program_rows(df)
    print(f"  {len(df):,} rows")

    print("Validating program code format...")
    validate_prog_codes(df)
    validate_names_present(df)

    print("Resolving department names...")
    orgs = resolve_orgs(df[DEPT_COL_EN].unique().tolist())
    print(f"  {len(orgs):,} unique departments")

    print("Building records...")
    records = build_records(df, orgs)

    write_json(records, OUT_PATH)
