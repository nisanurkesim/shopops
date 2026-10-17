# Project settings, kept in one place
import os
from pathlib import Path

# Folder that contains this file (the project root)
PROJECT_ROOT = Path(__file__).resolve().parent

# Local SQLite database built from the Olist CSV files. SHOPOPS_DB_PATH can point the
# app at another file, e.g. to try the demo server's first start without touching this one.
DB_PATH = Path(os.environ.get("SHOPOPS_DB_PATH", PROJECT_ROOT / "data" / "shopops.db")).resolve()

# Kaggle dataset id for Olist
OLIST_DATASET = "olistbr/brazilian-ecommerce"

# The dataset ends in 2018, so "today" is fixed for every date calculation
SIMULATED_TODAY = "2018-09-01"

# Demo server: a sample of the database, built at start-up (Genel Rehber: a small
# sampled DB for the demo). Whole customers are kept; the eval uses the full database.
SAMPLE_FRACTION = 0.30
SAMPLE_SEED = 42   # same seed, same sample on every start

# Demo customer A in the app (17 orders); always kept in the sample
DEMO_CUSTOMER_A = "8d50f5eadf50201ccdcedfb9e2ac8455"

# LLM used by the agents (free tier on Google AI Studio)
GEMINI_MODEL = "gemini-3.5-flash-lite"

# Sampling temperature, set explicitly so every result file can name it.
# 1.0 is the model default (checked with scripts/gemini_check.py) and the value
# Google recommends for Gemini 3 models; lower values can cause loops.
TEMPERATURE = 1.0