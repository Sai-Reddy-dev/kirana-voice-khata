
import sounddevice as sd
import soundfile as sf

DURATION = 8
SAMPLE_RATE = 16000
OUTPUT_FILE = "test_audio.wav"

print("Recording for 5 seconds. Speak now...")

audio = sd.rec(
    int(DURATION * SAMPLE_RATE),
    samplerate=SAMPLE_RATE,
    channels=1,
    dtype="int16",
    device=1,
)

sd.wait()

sf.write(OUTPUT_FILE, audio, SAMPLE_RATE)

print(f"Recording saved: {OUTPUT_FILE}")
