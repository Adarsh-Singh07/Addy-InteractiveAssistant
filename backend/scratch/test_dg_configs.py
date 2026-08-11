import os
import asyncio
import wave
import array
from google import genai
from google.genai import types
from deepgram import (
    DeepgramClient,
    LiveTranscriptionEvents,
    LiveOptions,
)

api_key = os.environ.get("DEEPGRAM_API_KEY")
if not api_key:
    with open("../.env", "r") as f:
        for line in f:
            if line.startswith("DEEPGRAM_API_KEY="):
                api_key = line.split("=", 1)[1].strip()
                break

gemini_key = os.environ.get("GEMINI_API_KEY")
if not gemini_key:
    with open("../.env", "r") as f:
        for line in f:
            if line.startswith("GEMINI_API_KEY="):
                gemini_key = line.split("=", 1)[1].strip()
                break

async def generate_english_wav():
    print("Generating English audio using Gemini TTS...")
    client = genai.Client(api_key=gemini_key)
    response = client.models.generate_content(
        model="gemini-3.1-flash-tts-preview",
        contents="Say exactly: Hello Addy, what can you do for me today?",
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
    raw_pcm = response.candidates[0].content.parts[0].inline_data.data
    # Convert big-endian L16 to little-endian PCM
    pcm_array = array.array('h', raw_pcm)
    pcm_array.byteswap()
    
    with wave.open("test_english.wav", "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(24000)
        wav_file.writeframes(pcm_array.tobytes())

async def test_deepgram(model, language):
    print(f"\nTesting Deepgram with model='{model}', language='{language}'...")
    client = DeepgramClient(api_key)
    connection = client.listen.asyncwebsocket.v("1")
    
    transcripts = []
    
    async def on_transcript(self, result, **kwargs):
        alternatives = result.channel.alternatives
        if alternatives:
            text = alternatives[0].transcript
            if text:
                print(f"  [{model}/{language}] Transcript: '{text}'")
                transcripts.append(text)

    async def on_error(self, error, **kwargs):
        print(f"  [{model}/{language}] Error event: {error}")

    connection.on(LiveTranscriptionEvents.Transcript, on_transcript)
    connection.on(LiveTranscriptionEvents.Error, on_error)

    options = LiveOptions(
        model=model,
        language=language,
        punctuate=True,
        encoding="linear16",
        sample_rate=24000,
        channels=1,
    )

    if not await connection.start(options):
        print(f"  [{model}/{language}] Connection failed!")
        return

    with wave.open("test_english.wav", "rb") as f:
        raw_pcm = f.readframes(f.getnframes())[44:] # skip WAV header

    chunk_size = 8192
    for i in range(0, len(raw_pcm), chunk_size):
        chunk = raw_pcm[i:i + chunk_size]
        await connection.send(chunk)
        await asyncio.sleep(0.1)

    await asyncio.sleep(4)
    await connection.finish()
    print(f"  [{model}/{language}] Transcripts: {transcripts}")

async def main():
    await generate_english_wav()
    
    # Try different model/language combinations
    await test_deepgram(model="nova-2", language="en-US")
    await test_deepgram(model="nova-3", language="en-US")
    await test_deepgram(model="nova-3", language="multi")

if __name__ == "__main__":
    asyncio.run(main())
