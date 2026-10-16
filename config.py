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

# LLM used by the agents (free tier on Google AI Studio)
GEMINI_MODEL = "gemini-3.5-flash-lite"

# Sampling temperature, set explicitly so every result file can name it.
# 1.0 is the model default (checked with scripts/model_info.py) and the value
# Google recommends for Gemini 3 models; lower values can cause loops.
TEMPERATURE = 1.0