
TTS_URL = "https://api.vachana.ai/api/v1/tts/inference"
TEXT = "లక్ష్మి దగ్గర నుంచి పన్నెండు వందల రూపాయలు తీసుకున్నాను."
PAYLOAD = {
    "text": TEXT,
    "model": "timbre-v2.5",
    "language": "te-IN",
    "voice": "Nalini",
    "sample_rate": 16000,
    "container": "wav",
    "encoding": "linear_pcm",
}


def main() -> int:
    import os
    import time

    import requests
    from dotenv import load_dotenv

    load_dotenv()
    api_key = os.getenv("TIMBRE_API_KEY")
    if not api_key:
        raise ValueError("TIMBRE_API_KEY is missing in .env")

    headers = {
        "X-API-Key-ID": api_key,
        "Content-Type": "application/json",
    }
    print("Sending Telugu text to Gnani Timbre TTS...")
    start = time.perf_counter()
    response = requests.post(TTS_URL, headers=headers, json=PAYLOAD, timeout=60)
    latency = time.perf_counter() - start

    print("HTTP status:", response.status_code)
    print(f"Latency: {latency:.2f} seconds")
    if response.status_code == 200:
        output_file = "tts_test.wav"
        with open(output_file, "wb") as audio:
            audio.write(response.content)
        print("Audio saved:", output_file)
        print("Audio size:", len(response.content), "bytes")
    else:
        print("Error response:")
        print(response.text)
    return 0 if response.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
