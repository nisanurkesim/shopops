# Project settings, kept in one place
from pathlib import Path

# Folder that contains this file (the project root)
PROJECT_ROOT = Path(__file__).resolve().parent

# Local SQLite database built from the Olist CSV files
DB_PATH = PROJECT_ROOT / "data" / "shopops.db"

# Kaggle dataset id for Olist
OLIST_DATASET = "olistbr/brazilian-ecommerce"

# The dataset ends in 2018, so "today" is fixed for every date calculation
SIMULATED_TODAY = "2018-09-01"