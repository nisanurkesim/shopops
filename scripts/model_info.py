# Show the settings Google reports for our model (default temperature, limits)
# This is a metadata request: it does not generate text.
# Run: python scripts/model_info.py
import os
import sys
from pathlib import Path

# Let this script import config.py from the project root
sys.path.append(str(Path(__file__).resolve().parent.parent))
from config import GEMINI_MODEL, PROJECT_ROOT

from dotenv import load_dotenv
from google import genai

load_dotenv(PROJECT_ROOT / ".env")
api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    print("GEMINI_API_KEY is missing. Copy .env.example to .env and add your key.")
    sys.exit(1)

client = genai.Client(api_key=api_key)
model = client.models.get(model=GEMINI_MODEL)

print(f"Model: {GEMINI_MODEL}")
for key, value in model.model_dump(exclude_none=True).items():
    if key in ("description", "supported_actions"):
        continue
    print(f"  {key}: {value}")
