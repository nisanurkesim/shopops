# Check that the Gemini API key works, list the models it can use and show the
# settings Google reports for our model (default temperature, token limits)
# Run: python scripts/gemini_check.py
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

print("Flash models available to this key:")
for model in client.models.list():
    if "flash" in model.name:
        print("  ", model.name)


# Metadata request: shows the model's defaults (TEMPERATURE in config.py was checked here)
print(f"\nSettings of {GEMINI_MODEL}:")
for key, value in client.models.get(model=GEMINI_MODEL).model_dump(exclude_none=True).items():
    if key not in ("description", "supported_actions"):
        print(f"   {key}: {value}")

print(f"\nTest call to {GEMINI_MODEL}:")
response = client.models.generate_content(
    model=GEMINI_MODEL,
    contents="Merhaba! Tek bir cümleyle kendini tanıt.",
)
print("  ", response.text)