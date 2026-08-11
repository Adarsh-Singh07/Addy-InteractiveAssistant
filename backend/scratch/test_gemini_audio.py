import os
from google import genai
from google.genai import types

# Load API key from environment
api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    # Try loading from ../.env
    with open("../.env", "r") as f:
        for line in f:
            if line.startswith("GEMINI_API_KEY="):
                api_key = line.split("=", 1)[1].strip()
                break

if not api_key:
    print("GEMINI_API_KEY not found!")
    exit(1)

client = genai.Client(api_key=api_key)

print("Calling generate_content with AUDIO modality...")
try:
    response = client.models.generate_content(
        model="gemini-3.1-flash-tts-preview",
        contents="Say exactly: Hello Adarsh, this is a test of the voice assistant.",
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

    print("Response structure:")
    print("Candidates:", len(response.candidates) if response.candidates else 0)
    for part in response.candidates[0].content.parts:
        print("Part type:", type(part))
        if part.inline_data:
            print("  Inline data mime_type:", part.inline_data.mime_type)
            print("  Inline data size:", len(part.inline_data.data))
            # Save the raw bytes to test.wav
            with open("test_audio_gemini.wav", "wb") as f:
                f.write(part.inline_data.data)
            print("  Saved test_audio_gemini.wav successfully!")

except Exception as e:
    print("Error:", e)
