import os
from google import genai

# Load API key from environment
api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    # Try loading from ../.env
    with open("../.env", "r") as f:
        for line in f:
            if line.startswith("GEMINI_API_KEY="):
                api_key = line.split("=", 1)[1].strip()
                break

client = genai.Client(api_key=api_key)

print("Listing models:")
for model in client.models.list():
    print(f"Name: {model.name}")
    print(f"  Supported Actions: {model.supported_actions}")
