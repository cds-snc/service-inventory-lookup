"""Download and combine PSPC Program Inventory data into program_codes.json.

Steps:
1. Download the EN and FR Program codes CSVs (pinned fiscal year list).
2. Filter each to Program Inventory rows (non-blank program-inventory code).
3. Validate every program code matches the [A-Z]{3}[0-9A-Z]{2} format.
4. Resolve unique department names per file via gcorg-resolver -> org lookup.
5. Build per-file (gc_orgID, PROG) keyed records.
6. Join EN and FR records on the key, composing program_code_id.
7. Write program_codes.json.
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
PROGRAM_CODES_EN_URL = "https://donnees-data.tpsgc-pwgsc.gc.ca/ba1/cp-pc/cp-pc-2627-eng.csv"
PROGRAM_CODES_FR_URL = "https://donnees-data.tpsgc-pwgsc.gc.ca/ba1/cp-pc/cp-pc-2627-fra.csv"
SOURCE_FISCAL_YEAR = "2026-27"
SOURCE_DATASET_URL = "https://open.canada.ca/data/en/dataset/3c371e57-d487-49fa-bb0d-352ae8dd6e4e"

GCORG_RESOLVER_URL = "https://gcorgs.cdssandbox.xyz/resolve"
RESOLVER_BATCH_SIZE = 1000
OUT_PATH = Path(__file__).parent / "program_codes.json"

DEPT_COL_EN = "EntityDept_name_Eng-EntitéMin_nom_ang"
DEPT_COL_FR = "EntityDept_name_fra-EntitéMin_nom_fra"
CR_NAME_COL = "ProgramorCoreResponsibility_name-ProgrammeouResponsabilitéessentielle_nom_PROG"
PROG_CODE_COL = "ProgramInventory-Répertoiredesprogrammes_code_PROG"
PROG_NAME_COL = "ProgramInventory_name-Répertoiredesprogrammes_nom_PROG"

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


def build_keyed_records(
    df: pd.DataFrame,
    dept_col: str,
    org_lookup: dict[str, dict],
    lang: str,
) -> dict[tuple, dict]:
    """Build {(gc_orgID, PROG): row data} for one language's filtered DataFrame.

    Raises ValueError if (gc_orgID, PROG) is not unique within the file.
    """
    records = {}
    for _, row in df.iterrows():
        org = org_lookup[row[dept_col]]
        prog = row[PROG_CODE_COL].strip()
        key = (org["gc_orgID"], prog)
        if key in records:
            raise ValueError(f"Duplicate (gc_orgID, PROG) key in {lang} file: {key}")
        records[key] = {
            "gc_orgID": org["gc_orgID"],
            "org_name_en": org["org_name_en"],
            "org_name_fr": org["org_name_fr"],
            "acronym_en": org["acronym_en"],
            "acronym_fr": org["acronym_fr"],
            f"program_name_{lang}": row[PROG_NAME_COL],
            f"core_responsibility_{lang}": row[CR_NAME_COL],
        }
    return records


def combine_records(en_records: dict[tuple, dict], fr_records: dict[tuple, dict]) -> list[dict]:
    """Join EN and FR keyed records into the final program_codes.json record list.

    Raises ValueError if the EN and FR key sets don't match exactly.
    """
    en_keys, fr_keys = set(en_records), set(fr_records)
    if en_keys != fr_keys:
        raise ValueError(
            f"EN/FR key mismatch. Only in EN: {sorted(en_keys - fr_keys)}. "
            f"Only in FR: {sorted(fr_keys - en_keys)}."
        )
    records = []
    for gc_orgID, prog in sorted(en_keys):
        en = en_records[(gc_orgID, prog)]
        fr = fr_records[(gc_orgID, prog)]
        records.append(
            {
                "program_code_id": f"{gc_orgID}-{prog}",
                "prog_code": prog,
                "program_name_en": en["program_name_en"],
                "program_name_fr": fr["program_name_fr"],
                "core_responsibility_en": en["core_responsibility_en"],
                "core_responsibility_fr": fr["core_responsibility_fr"],
                "gc_orgID": gc_orgID,
                "org_name_en": en["org_name_en"],
                "org_name_fr": en["org_name_fr"],
                "acronym_en": en["acronym_en"],
                "acronym_fr": en["acronym_fr"],
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
        if existing.get("programs") == records and existing.get("generated_at"):
            return existing["generated_at"]
    return pd.Timestamp.now(tz="UTC").isoformat()


def write_json(records: list[dict], path: Path) -> None:
    output = {
        "generated_at": update_generated_at(records, path),
        "source": {
            "fiscal_year": SOURCE_FISCAL_YEAR,
            "dataset_url": SOURCE_DATASET_URL,
            "csv_en": PROGRAM_CODES_EN_URL,
            "csv_fr": PROGRAM_CODES_FR_URL,
        },
        "programs": records,
    }
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(records):,} records to {path}")


if __name__ == "__main__":
    warnings.filterwarnings("ignore", category=urllib3.exceptions.InsecureRequestWarning)

    print("Downloading EN program codes...")
    en_df = download_csv(PROGRAM_CODES_EN_URL)
    print(f"  {len(en_df):,} rows")

    print("Downloading FR program codes...")
    fr_df = download_csv(PROGRAM_CODES_FR_URL)
    print(f"  {len(fr_df):,} rows")

    print("Filtering to Program Inventory rows...")
    en_df = filter_program_rows(en_df)
    fr_df = filter_program_rows(fr_df)
    print(f"  {len(en_df):,} EN rows, {len(fr_df):,} FR rows")

    print("Validating program code format...")
    validate_prog_codes(en_df)
    validate_prog_codes(fr_df)

    print("Resolving EN department names...")
    en_orgs = resolve_orgs(en_df[DEPT_COL_EN].unique().tolist())
    print(f"  {len(en_orgs):,} unique EN departments")

    print("Resolving FR department names...")
    fr_orgs = resolve_orgs(fr_df[DEPT_COL_FR].unique().tolist())
    print(f"  {len(fr_orgs):,} unique FR departments")

    print("Building keyed records...")
    en_records = build_keyed_records(en_df, DEPT_COL_EN, en_orgs, lang="en")
    fr_records = build_keyed_records(fr_df, DEPT_COL_FR, fr_orgs, lang="fr")

    print("Joining EN and FR records...")
    records = combine_records(en_records, fr_records)

    write_json(records, OUT_PATH)
