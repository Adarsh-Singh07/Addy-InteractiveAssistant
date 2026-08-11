import os
from google import genai
from google.genai import types

# Load API key
api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    with open("../.env", "r") as f:
        for line in f:
            if line.startswith("GEMINI_API_KEY="):
                api_key = line.split("=", 1)[1].strip()
                break

client = genai.Client(api_key=api_key)

response = client.models.generate_content(
    model="gemini-3.1-flash-tts-preview",
    contents="Say exactly: Hello.",
    config=types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name="Puck"
                )
            )
        )
    )
)

raw_pcm_bytes = response.candidates[0].content.parts[0].inline_data.data
print("Type of raw_pcm_bytes:", type(raw_pcm_bytes))
print("Length of raw_pcm_bytes:", len(raw_pcm_bytes))
print("First 100 bytes as raw values:", list(raw_pcm_bytes[:100]))
try:
    print("First 100 bytes decoded as string:", raw_pcm_bytes[:100].decode('utf-8'))
except Exception as e:
    print("Could not decode as string:", e)
