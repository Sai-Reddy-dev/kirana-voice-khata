
import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("TIMBRE_API_KEY")
TTS_URL = "https://api.vachana.ai/api/v1/tts/inference"

if not API_KEY:
    raise ValueError("TIMBRE_API_KEY is missing in .env")

TEXT = "లక్ష్మి దగ్గర నుంచి పన్నెండు వందల రూపాయలు తీసుకున్నాను."

payload = {
    "text": TEXT,
    "model": "timbre-v2.5",
    "language": "te-IN",
    "voice": "Nalini",
    "sample_rate": 16000,
    "container": "wav",
    "encoding": "linear_pcm",
}

headers = {
    "X-API-Key-ID": API_KEY,
    "Content-Type": "application/json",
}

print("Sending Telugu text to Gnani Timbre TTS...")
start = time.perf_counter()

response = requests.post(
    TTS_URL,
    headers=headers,
    json=payload,
    timeout=60,

)

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
