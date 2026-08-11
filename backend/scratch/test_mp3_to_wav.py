import os
import wave
import asyncio
from gtts import gTTS
import miniaudio
from deepgram import (
    DeepgramClient,
    LiveTranscriptionEvents,
    LiveOptions,
)

# Load API key
api_key = os.environ.get("DEEPGRAM_API_KEY")
if not api_key:
    with open("../.env", "r") as f:
        for line in f:
            if line.startswith("DEEPGRAM_API_KEY="):
                api_key = line.split("=", 1)[1].strip()
                break

async def main():
    print("1. Generating MP3 using gTTS...")
    text = "नमस्ते एड़ी, तुम्हारा नाम क्या है?"
    tts = gTTS(text=text, lang="hi")
    mp3_path = "test_gtts_hindi.mp3"
    tts.save(mp3_path)
    print(f"   Saved {mp3_path}")

    print("2. Decoding MP3 to raw PCM using miniaudio (16kHz, mono)...")
    decoded = miniaudio.decode_file(mp3_path, sample_rate=16000, nchannels=1)
    print(f"   Decoded audio properties: sample_rate={decoded.sample_rate}, channels={decoded.nchannels}, type={type(decoded.samples)}")
    
    # Save as WAV
    wav_path = "test_gtts_hindi.wav"
    with wave.open(wav_path, "wb") as f:
        f.setnchannels(decoded.nchannels)
        f.setsampwidth(2) # 16-bit PCM
        f.setframerate(decoded.sample_rate)
        # decoded.samples is a memoryview or array, convert to bytes if needed
        f.writeframes(decoded.samples)
    wav_path = "test_gtts_hindi.wav"
    # 3. Stream to Deepgram
    print("3. Connecting to Deepgram Live...")
    client = DeepgramClient(api_key)
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

    connection = client.listen.asyncwebsocket.v("1")

    transcripts = []
    
    async def on_transcript(self, result, **kwargs):
        try:
            alternatives = result.channel.alternatives
            if alternatives:
                text = alternatives[0].transcript
                if text:
                    transcripts.append(text)
                    print(f"   [Callback] Transcript text: '{text}' (is_final={result.is_final})")
                else:
                    print(f"   [Callback] Empty transcript (is_final={result.is_final})")
        except Exception as e:
            print("   [Callback] Error parsing transcript:", str(e))

    connection.on(LiveTranscriptionEvents.Transcript, on_transcript)

    options = LiveOptions(
        model="nova-2",
        language="hi",
        punctuate=True,
        encoding="linear16",
        sample_rate=16000,
        channels=1,
    )

    if not await connection.start(options):
        print("   Connection failed!")
        return

    # Stream WAV frames (skipping WAV header)
    with wave.open(wav_path, "rb") as f:
        raw_pcm = f.readframes(f.getnframes())

    print(f"   Streaming {len(raw_pcm)} raw PCM bytes...")
    chunk_size = 4096
    for i in range(0, len(raw_pcm), chunk_size):
        chunk = raw_pcm[i:i + chunk_size]
        success = await connection.send(chunk)
        if not success:
            print(f"   [Error] Failed to send chunk at index {i}!")
        await asyncio.sleep(0.08)

    print("   Finished streaming. Sending CloseStream...")
    import json
    await connection.send(json.dumps({"type": "CloseStream"}))
    print("   Waiting 4 seconds for remaining transcripts...")
    await asyncio.sleep(4)
    await connection.finish()
    
    print("\nResult:")
    print("Transcripts received:", transcripts)

if __name__ == "__main__":
    asyncio.run(main())
