import os
import wave
import array
import sys
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

try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass

client = genai.Client(api_key=api_key)

phrase = "नमस्ते एड़ी, तुम्हारा नाम क्या है?"
print(f"Generating audio for phrase: '{phrase}'")

response = client.models.generate_content(
    model="gemini-3.1-flash-tts-preview",
    contents=f"Say exactly: {phrase}",
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

raw_pcm = None
for part in response.candidates[0].content.parts:
    if part.inline_data:
        raw_pcm = part.inline_data.data
        break

if not raw_pcm:
    print("Failed to generate audio!")
    exit(1)

# L16 returned by Gemini is big-endian.
# We convert it to little-endian using Python's built-in array module
pcm_array = array.array('h', raw_pcm)
pcm_array.byteswap()
le_pcm = pcm_array.tobytes()

# Write to WAV file
wav_path = "test_phrase_hindi.wav"
with wave.open(wav_path, "wb") as wav_file:
    wav_file.setnchannels(1)
    wav_file.setsampwidth(2)
    wav_file.setframerate(24000)
    wav_file.writeframes(le_pcm)

print(f"Saved byte-swapped WAV file to {wav_path}. Size: {os.path.getsize(wav_path)} bytes.")
