import os
import asyncio
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

async def main():
    print("Testing Deepgram callbacks with details...")
    client = DeepgramClient(api_key)
    connection = client.listen.asyncwebsocket.v("1")

    async def on_transcript(self, result, **kwargs):
        print(f"TRANSCRIPT EVENT CALLED!")
        print(f"  result type: {type(result)}")
        print(f"  result: {result}")
        try:
            alternatives = result.channel.alternatives
            print(f"  alternatives: {alternatives}")
            if alternatives:
                print(f"  transcript text: '{alternatives[0].transcript}'")
        except Exception as e:
            print("  Error parsing transcript:", e)

    async def on_error(self, error, **kwargs):
        print(f"ERROR EVENT CALLED! error: {error}")

    async def on_metadata(self, metadata, **kwargs):
        print(f"METADATA EVENT CALLED! metadata: {metadata}")

    connection.on(LiveTranscriptionEvents.Transcript, on_transcript)
    connection.on(LiveTranscriptionEvents.Metadata, on_metadata)
    connection.on(LiveTranscriptionEvents.Error, on_error)

    options = LiveOptions(
        model="nova-3",
        language="multi",
        punctuate=True,
        encoding="linear16",
        sample_rate=24000,
        channels=1,
    )

    print("Connecting...")
    if not await connection.start(options):
        print("Failed!")
        return

    print("Streaming WAV data in chunks...")
    if not os.path.exists("test_phrase_hindi.wav"):
        print("Please run generate_wav.py first!")
        return
        
    with open("test_phrase_hindi.wav", "rb") as f:
        data = f.read()

    # Skip WAV header (44 bytes)
    raw_pcm = data[44:]
    chunk_size = 8192
    for i in range(0, len(raw_pcm), chunk_size):
        chunk = raw_pcm[i:i + chunk_size]
        await connection.send(chunk)
        await asyncio.sleep(0.1)

    print("Finished streaming. Waiting 5 seconds...")
    await asyncio.sleep(5)
    
    print("Closing...")
    await connection.finish()

if __name__ == "__main__":
    asyncio.run(main())
