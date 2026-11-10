
STT_URL = "https://api.vachana.ai/stt/v3"
AUDIO_FILE = "test_audio.wav"


def main() -> int:
    import os

    import requests
    from dotenv import load_dotenv

    load_dotenv()
    api_key = os.getenv("PRISMA_API_KEY")
    if not api_key:
        raise ValueError("PRISMA_API_KEY is missing in .env")
    if not os.path.exists(AUDIO_FILE):
        raise FileNotFoundError(f"{AUDIO_FILE} not found. Record audio first.")

    headers = {"X-API-Key-ID": api_key}
    with open(AUDIO_FILE, "rb") as audio:
        files = {"audio_file": (AUDIO_FILE, audio, "audio/wav")}
        data = {"language_code": "indic-auto"}
        print("Sending audio to Gnani Prisma STT...")
        response = requests.post(
            STT_URL,
            headers=headers,
            files=files,
            data=data,
            timeout=60,
        )

    print("HTTP status:", response.status_code)
    try:
        result = response.json()
        print("Response:")
        print(result)
    except requests.exceptions.JSONDecodeError:
        print(response.text)
    return 0 if response.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
