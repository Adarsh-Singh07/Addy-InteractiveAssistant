import os
import asyncio
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

if not api_key:
    print("DEEPGRAM_API_KEY not found!")
    exit(1)

async def main():
    print("Testing Deepgram STT with file: test_phrase_hindi.wav...")
    if not os.path.exists("test_phrase_hindi.wav"):
        print("Please run generate_wav.py first to create test_phrase_hindi.wav")
        return

    # Initialize client
    client = DeepgramClient(api_key)
    
    # Establish connection
    connection = client.listen.asyncwebsocket.v("1")
    
    transcripts = []

    # Use async def callbacks!
    async def on_transcript(self, result, **kwargs):
        try:
            alternatives = result.channel.alternatives
            if alternatives:
                text = alternatives[0].transcript
                if text:
                    print(f"Transcript event: '{text}' (is_final: {result.is_final})")
                    transcripts.append(text)
        except Exception as e:
            print("Error in callback:", e)

    async def on_error(self, error, **kwargs):
        print("Deepgram error:", error)

    connection.on(LiveTranscriptionEvents.Transcript, on_transcript)
    connection.on(LiveTranscriptionEvents.Error, on_error)

    options = LiveOptions(
        model="nova-3",
        language="multi",
        punctuate=True,
        encoding="linear16",
        sample_rate=24000,
        channels=1,
    )

    print("Connecting to Deepgram Live WebSocket...")
    if not await connection.start(options):
        print("Failed to start connection!")
        return

    # Stream the WAV file
    print("Streaming WAV data in chunks...")
    with open("test_phrase_hindi.wav", "rb") as f:
        data = f.read()

    # Skip the 44-byte WAV header so we send pure linear16 raw PCM!
    raw_pcm = data[44:]

    # Send in 8KB chunks (about 170ms of audio per chunk at 24kHz 16-bit mono)
    chunk_size = 8192
    for i in range(0, len(raw_pcm), chunk_size):
        chunk = raw_pcm[i:i + chunk_size]
        await connection.send(chunk)
        await asyncio.sleep(0.1)

    print("Finished streaming. Waiting for final transcripts...")
    await asyncio.sleep(5)
    
    print("Closing connection...")
    await connection.finish()
    
    print("\nResult:")
    print("Transcripts received:", transcripts)

if __name__ == "__main__":
    asyncio.run(main())
