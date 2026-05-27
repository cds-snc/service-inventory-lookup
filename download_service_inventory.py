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

from pathlib import Path
from urllib.request import urlopen

import pandas as pd

SERVICE_REGISTRY_URL = (
    "https://raw.githubusercontent.com/gcperformance/utilities/master/goc-service-id-registry.csv"
)
SERVICE_PROGRAM_URL = (
    "https://raw.githubusercontent.com/gcperformance/utilities/master/goc-service-program.csv"
)
GCORG_RESOLVER_URL = "https://gcorgs.cdssandbox.xyz/resolve"
OUT_PATH = Path(__file__).parent / "services.json"


def download_csv(url: str) -> pd.DataFrame:
    """Download a CSV from url and return it as a DataFrame."""
    with urlopen(url) as response:
        body = response.read()
    return pd.read_csv(pd.io.common.BytesIO(body))


PLACEHOLDER_SERVICE_NAMES = ["id not used"]


def filter_transferred(df: pd.DataFrame) -> pd.DataFrame:
    """Drop services that have been transferred to another org."""
    # fillna("") first so .str accessor works on all-NaN float columns
    mask = df["date_transferred"].fillna("").str.strip() == ""
    return df[mask].reset_index(drop=True)


def filter_placeholder(df: pd.DataFrame) -> pd.DataFrame:
    """Drop placeholder rows that reserve a service_id without a real service."""
    return df[~df["service_en"].str.strip().isin(PLACEHOLDER_SERVICE_NAMES)].reset_index(drop=True)


def build_program_lookup(df: pd.DataFrame) -> dict[str, str]:
    """Return {service_id: program_id} using the most recent fiscal year per service."""
    duplicates = df.duplicated(subset=["service_id", "fiscal_yr"], keep=False)
    if duplicates.any():
        count = duplicates.sum()
        print(
            f"WARNING: {count} duplicate (service_id, fiscal_yr) rows"
            " in program data - keeping first"
        )
        df = df.drop_duplicates(subset=["service_id", "fiscal_yr"], keep="first")
    latest = (
        df.sort_values("fiscal_yr")
        .groupby("service_id", as_index=False)
        .last()
    )
    return {str(row["service_id"]): row["program_id"] for _, row in latest.iterrows()}
