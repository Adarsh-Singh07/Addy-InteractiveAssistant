import wave
import array

with wave.open("test_gtts_hindi.wav", "rb") as f:
    frames = f.readframes(f.getnframes())
    print("Channels:", f.getnchannels())
    print("Sample width:", f.getsampwidth())
    print("Frame rate:", f.getframerate())
    print("Frames:", f.getnframes())
    
    samples = array.array('h', frames)
    print("Total samples:", len(samples))
    if len(samples) > 0:
        max_val = max(abs(s) for s in samples)
        min_val = min(samples)
        max_pos = max(samples)
        print("Max absolute value:", max_val)
        print("Min sample value:", min_val)
        print("Max sample value:", max_pos)
        print("First 50 samples:", list(samples[:50]))
