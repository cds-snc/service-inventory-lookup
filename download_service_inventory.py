"""Download and combine GC service inventory, program, and org data into services.json.

Steps:
1. Download goc-service-id-registry.csv (service registry)
2. Download goc-service-program.csv (program mappings)
3. Filter out transferred services (non-empty date_transferred)
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
