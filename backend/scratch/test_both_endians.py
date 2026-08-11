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

async def test_stream(raw_pcm_data, description):
    print(f"\n--- Testing: {description} ---")
    client = DeepgramClient(api_key)
    connection = client.listen.asyncwebsocket.v("1")
    
    transcripts = []
    
    async def on_transcript(self, result, **kwargs):
        alternatives = result.channel.alternatives
        if alternatives:
            text = alternatives[0].transcript
            if text:
                print(f"  [{description}] Transcript: '{text}'")
                transcripts.append(text)

    connection.on(LiveTranscriptionEvents.Transcript, on_transcript)

    options = LiveOptions(
        model="nova-3",
        language="multi",
        punctuate=True,
        encoding="linear16",
        sample_rate=24000,
        channels=1,
    )

    if not await connection.start(options):
        print(f"  [{description}] Failed to connect!")
        return

    # Stream raw PCM
    chunk_size = 8192
    for i in range(0, len(raw_pcm_data), chunk_size):
        chunk = raw_pcm_data[i:i + chunk_size]
        await connection.send(chunk)
        await asyncio.sleep(0.1)

    await asyncio.sleep(3)
    await connection.finish()
    print(f"  [{description}] Finished. Transcripts received: {transcripts}")

async def main():
    if not os.path.exists("test_phrase_hindi.wav"):
        print("Please run generate_wav.py first!")
        return

    # Load WAV file
    import wave
    with wave.open("test_phrase_hindi.wav", "rb") as wav_file:
        raw_pcm_swapped = wav_file.readframes(wav_file.getnframes())

    # The current WAV is byte-swapped (from generate_wav.py).
    # Let's create the original non-swapped version by swapping it again!
    import array
    pcm_array = array.array('h', raw_pcm_swapped)
    pcm_array.byteswap()
    raw_pcm_original = pcm_array.tobytes()

    # Test both
    await test_stream(raw_pcm_original, "Original (Little Endian)")
    await test_stream(raw_pcm_swapped, "Byte-swapped (Big Endian)")

if __name__ == "__main__":
    asyncio.run(main())
