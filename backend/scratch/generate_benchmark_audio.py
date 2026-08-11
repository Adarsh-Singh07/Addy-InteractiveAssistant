import os
import wave
from gtts import gTTS
import miniaudio

import sys

# Reconfigure stdout to use UTF-8
try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass

phrases = [
    # English
    (1, "Hello Addy, what can you do for me today?", "en"),
    (2, "Tell me about my active projects.", "en"),
    (3, "Can you check if the Hermes agent is running?", "en"),
    (4, "What is my timezone and local time?", "en"),
    (5, "Summarize your architectural layout.", "en"),
    (6, "How do you handle voice barge-in?", "en"),
    (7, "What is the next phase of your development?", "en"),
    # Hindi
    (8, "नमस्ते एड़ी, तुम्हारा नाम क्या है?", "hi"),
    (9, "क्या तुम मेरी मदद कर सकते हो?", "hi"),
    (10, "आज का मौसम कैसा है?", "hi"),
    (11, "मुझे अपने बारे में कुछ बताओ।", "hi"),
    (12, "तुम कौन से प्रोजेक्ट्स संभालते हो?", "hi"),
    (13, "क्या तुम हरमीस को संदेश भेज सकते हो?", "hi"),
    (14, "समय क्या हुआ है?", "hi"),
    # Hinglish
    (15, "Addy, mera portfolio check karo aur batao.", "hi"),
    (16, "Hermes VPS ka status kya chal raha hai?", "hi"),
    (17, "Mera timezone Asia Kolkata set hai na?", "hi"),
    (18, "Kya tum mere portfolio ko deploy kar sakte ho?", "hi"),
    (19, "Naya command run karne ke liye bolo.", "hi"),
    (20, "Chalo ek test message send karte hain.", "hi"),
]

def main():
    out_dir = "benchmark_audio"
    os.makedirs(out_dir, exist_ok=True)
    print(f"Generating 20 benchmark speech files in '{out_dir}'...")

    for num, text, lang in phrases:
        mp3_path = f"{out_dir}/phrase_{num}.mp3"
        wav_path = f"{out_dir}/phrase_{num}.wav"
        
        if os.path.exists(wav_path):
            print(f"   [{num}] Already exists, skipping.")
            continue

        print(f"   [{num}] Generating MP3 for: '{text}' ({lang})...")
        tts = gTTS(text=text, lang=lang)
        tts.save(mp3_path)

        print(f"   [{num}] Decoding MP3 to 16kHz mono WAV...")
        decoded = miniaudio.decode_file(mp3_path, sample_rate=16000, nchannels=1)
        
        with wave.open(wav_path, "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2) # 16-bit PCM
            f.setframerate(16000)
            f.writeframes(decoded.samples)
            
        # Clean up MP3 temp file
        try:
            os.remove(mp3_path)
        except Exception:
            pass

    print("Generation complete!")

if __name__ == "__main__":
    main()
