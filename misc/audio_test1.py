from piper.voice import PiperVoice
from config import PIPER_MODEL, PIPER_CONFIG

voice = PiperVoice.load(PIPER_MODEL, config_path=PIPER_CONFIG, use_cuda=False)
result = voice.synthesize("Hello, this is a test.")
print("Type of result:", type(result))
print("Sample rate:", voice.config.sample_rate)