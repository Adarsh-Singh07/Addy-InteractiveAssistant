import wave
import array

with wave.open("test_english.wav", "rb") as f:
    frames = f.readframes(f.getnframes())
    print("Number of channels:", f.getnchannels())
    print("Sample width:", f.getsampwidth())
    print("Frame rate:", f.getframerate())
    print("Number of frames:", f.getnframes())
    print("Total byte size of frames:", len(frames))
    
    samples = array.array('h', frames)
    print("Number of samples:", len(samples))
    if len(samples) > 0:
        max_val = max(abs(s) for s in samples)
        min_val = min(samples)
        max_pos = max(samples)
        print("Max absolute sample value (amplitude):", max_val)
        print("Min sample value:", min_val)
        print("Max sample value:", max_pos)
        print("First 20 samples:", list(samples[:20]))
