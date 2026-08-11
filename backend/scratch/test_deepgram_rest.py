import os
from deepgram import DeepgramClient, PrerecordedOptions

# Load API key
api_key = os.environ.get("DEEPGRAM_API_KEY")
if not api_key:
    with open("../.env", "r") as f:
        for line in f:
            if line.startswith("DEEPGRAM_API_KEY="):
                api_key = line.split("=", 1)[1].strip()
                break

def main():
    print("Testing Deepgram Prerecorded REST API...")
    if not os.path.exists("test_gtts_hindi.wav"):
        print("Please run test_mp3_to_wav.py first!")
        return

    client = DeepgramClient(api_key)
    
    with open("test_gtts_hindi.wav", "rb") as f:
        buffer_data = f.read()

    payload = {
        "buffer": buffer_data,
    }

    options = PrerecordedOptions(
        model="nova-2",
        language="hi",
        smart_format=True,
    )

    print("Sending request to Deepgram REST API...")
    # Call the transcribe_file method
    response = client.listen.rest.v("1").transcribe_file(
        payload,
        options
    )
    
    print("\nResult:")
    print("Response:", response.to_json(indent=2))
    
    try:
        transcript = response.results.channels[0].alternatives[0].transcript
        print(f"\nExtracted Transcript: '{transcript}'")
    except Exception as e:
        print("Error extracting transcript:", e)

if __name__ == "__main__":
    main()
