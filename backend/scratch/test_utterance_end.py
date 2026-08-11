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
    print("Testing Deepgram UtteranceEnd event callback signature...")
    client = DeepgramClient(api_key)
    connection = client.listen.asyncwebsocket.v("1")

    async def on_utterance_end(*args, **kwargs):
        print("UTTERANCE_END EVENT TRIGGERED!")
        print("  Args:", [type(a) for a in args])
        print("  Kwargs keys:", list(kwargs.keys()))
        for k, v in kwargs.items():
            print(f"  Kwarg '{k}': type={type(v)}, value={v}")

    async def on_transcript(*args, **kwargs):
        # Just to print transcript progress
        result = kwargs.get('result')
        if result:
            alternatives = result.channel.alternatives
            if alternatives and alternatives[0].transcript:
                print("Transcript:", alternatives[0].transcript)

    connection.on(LiveTranscriptionEvents.UtteranceEnd, on_utterance_end)
    connection.on(LiveTranscriptionEvents.Transcript, on_transcript)

    options = LiveOptions(
        model="nova-2",
        language="hi",
        punctuate=True,
        encoding="linear16",
        sample_rate=16000,
        channels=1,
        utterance_end_ms="1000",
        interim_results=True,
    )

    if not await connection.start(options):
        print("Connection failed!")
        return

    import wave
    with wave.open("test_gtts_hindi.wav", "rb") as f:
        raw_pcm = f.readframes(f.getnframes())

    print("Streaming audio...")
    chunk_size = 4096
    for i in range(0, len(raw_pcm), chunk_size):
        chunk = raw_pcm[i:i + chunk_size]
        await connection.send(chunk)
        await asyncio.sleep(0.08)

    # Stream 2.5 seconds of silence to trigger VAD UtteranceEnd
    print("Streaming silence to trigger VAD...")
    silence_chunk = bytes(4096)
    for _ in range(20):
        await connection.send(silence_chunk)
        await asyncio.sleep(0.1)

    print("Streaming finished. Sending CloseStream...")
    import json
    await connection.send(json.dumps({"type": "CloseStream"}))
    
    print("Waiting 4 seconds for events...")
    await asyncio.sleep(4)
    await connection.finish()

if __name__ == "__main__":
    asyncio.run(main())
