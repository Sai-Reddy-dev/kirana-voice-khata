
DURATION = 8
SAMPLE_RATE = 16000
OUTPUT_FILE = "test_audio.wav"


def main() -> int:
    import sounddevice as sd
    import soundfile as sf

    print(f"Recording for {DURATION} seconds. Speak now...")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
