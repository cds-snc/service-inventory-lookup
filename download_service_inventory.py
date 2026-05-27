"""Download and combine GC service inventory, program, and org data into services.json.

Steps:
1. Download goc-service-id-registry.csv (service registry)
2. Download goc-service-program.csv (program mappings)
3. Filter out transferred services (non-empty date_transferred) and placeholder rows
4. Build program_id lookup: most recent fiscal year per service_id
5. Resolve unique org names via gcorg-resolver -> org lookup table
6. Join program_id and org info onto service rows
7. Write services.json
"""

import json
import warnings
from pathlib import Path
from urllib.request import urlopen

import pandas as pd
import requests
import urllib3

SERVICE_REGISTRY_URL = (
    "https://raw.githubusercontent.com/gcperformance/utilities/master/goc-service-id-registry.csv"
)
SERVICE_PROGRAM_URL = (
    "https://raw.githubusercontent.com/gcperformance/utilities/master/goc-service-program.csv"
)
GCORG_RESOLVER_URL = "https://gcorgs.cdssandbox.xyz/resolve"
RESOLVER_BATCH_SIZE = 1000
OUT_PATH = Path(__file__).parent / "services.json"


def download_csv(url: str) -> pd.DataFrame:
    """Download a CSV from url and return it as a DataFrame."""
    with urlopen(url) as response:
        body = response.read()
    return pd.read_csv(pd.io.common.BytesIO(body))


PLACEHOLDER_SERVICE_NAMES = ["id not used"]

# Known errors in the source data: wrong org name -> correct canonical name.

ORG_NAME_CORRECTIONS = {
    # "Offices of the Information and Privacy Commissioners of Canada" is a combined
    # entry that should be two separate orgs; services here are predominantly Privacy
    # Commissioner in nature so we remap to that until the source data is corrected.
    "Offices of the Information and Privacy Commissioners of Canada": (
        "Office of the Privacy Commissioner of Canada"
    ),
}


def filter_transferred(df: pd.DataFrame) -> pd.DataFrame:
    """Drop services that have been transferred to another org."""
    # fillna("") first so .str accessor works on all-NaN float columns
    mask = df["date_transferred"].fillna("").str.strip() == ""
    return df[mask].reset_index(drop=True)


def apply_org_corrections(df: pd.DataFrame) -> pd.DataFrame:
    """Remap known bad org names in the source data to their correct canonical names."""
    return df.assign(org_name_en=df["org_name_en"].replace(ORG_NAME_CORRECTIONS))


def filter_placeholder(df: pd.DataFrame) -> pd.DataFrame:
    """Drop placeholder rows that reserve a service_id without a real service."""
    return df[~df["service_en"].str.strip().isin(PLACEHOLDER_SERVICE_NAMES)].reset_index(drop=True)


def build_program_lookup(df: pd.DataFrame) -> dict[str, list[str]]:
    """Return {service_id: [program_id, ...]} for all programs in the most recent fiscal year."""
    latest_yr = df.groupby("service_id")["fiscal_yr"].transform("max")
    latest = df[df["fiscal_yr"] == latest_yr]
    return {str(sid): group["program_id"].tolist() for sid, group in latest.groupby("service_id")}


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
            verify=False,
        )
        response.raise_for_status()
        for result in response.json()["results"]:
            if result["matched"]:
                lookup[result["input"]] = {
                    "gc_orgID": result["gc_orgID"],
                    "org_name_en": result["harmonized_name"],
                    "org_name_fr": result["nom_harmonise"],
                }
            else:
                raise ValueError(f"gcorg-resolver could not match org: '{result['input']}'")
    return lookup


def build_records(
    services: pd.DataFrame,
    program_lookup: dict[str, list[str]],
    org_lookup: dict[str, dict],
) -> list[dict]:
    """Join program and org data onto each service row and return as a list of dicts."""
    records = []
    for _, row in services.iterrows():
        sid = str(row["service_id"])
        org = org_lookup.get(row["org_name_en"], {})
        records.append(
            {
                "service_id": sid,
                "service_en": row["service_en"],
                "service_fr": row["service_fr"],
                "gc_orgID": org.get("gc_orgID"),
                "org_name_en": org.get("org_name_en", row["org_name_en"]),
                "org_name_fr": org.get("org_name_fr"),
                "program_id": program_lookup.get(sid),
            }
        )
    return records


def write_json(records: list[dict], path: Path) -> None:
    """Write records to a JSON file and print a summary."""
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(records):,} records to {path}")


if __name__ == "__main__":
    warnings.filterwarnings("ignore", category=urllib3.exceptions.InsecureRequestWarning)

    print("Downloading service registry...")
    services = download_csv(SERVICE_REGISTRY_URL)
    print(f"  {len(services):,} rows")

    print("Downloading program data...")
    programs = download_csv(SERVICE_PROGRAM_URL)
    print(f"  {len(programs):,} rows")

    print("Filtering services...")
    services = filter_transferred(services)
    services = filter_placeholder(services)
    services = apply_org_corrections(services)
    print(f"  {len(services):,} rows after filtering")

    print("Building program_id lookup...")
    program_lookup = build_program_lookup(programs)
    print(f"  {len(program_lookup):,} services with program_id")

    print("Resolving org names...")
    unique_orgs = services["org_name_en"].unique().tolist()
    print(f"  {len(unique_orgs):,} unique orgs")
    org_lookup = resolve_orgs(unique_orgs)

    print("Building output records...")
    records = build_records(services, program_lookup, org_lookup)

    write_json(records, OUT_PATH)
