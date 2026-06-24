import sounddevice as sd
import numpy as np

fs = 22050
t = np.linspace(0, 1, fs, False)
tone = 0.3 * np.sin(2 * np.pi * 440 * t)
print("Default device:", sd.default.device)
print(sd.query_devices())
sd.play(tone.astype("float32"), samplerate=fs)
sd.wait()