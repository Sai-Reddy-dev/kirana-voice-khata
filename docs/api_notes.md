> ## Documentation Index
> Fetch the complete documentation index at: https://docs.gnani.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Quick Start

> Make your first speech-to-text, text-to-speech or voice-cloned TTS API request in minutes.

## Prerequisites

Before you begin, ensure you have:

* A valid API key (sign up on the [Gnani API platform](https://app.gnani.ai/voice/) to generate API keys)
* cURL installed, or an API client such as Postman

> [tab] Speech-to-Text (STT)
>
> > [tab] REST
> >
> > Use a test audio file that meets these requirements:
> >
> > * Format: WAV, MP3, OGG, FLAC, AAC, or M4A
> > * Sample rate: 8 kHz to 44.1 kHz
> > * Maximum duration: 30 seconds
> >
> > ### Your First Speech-to-Text Request
> >
> > Minimal examples to transcribe an audio file. Prisma v2.5 is the default model. Add `model=prisma-v3.0` to use Prisma v3.0.
> >
> > #### Prisma v3.0
> >
> > ```bash theme={null}
> > curl -X POST https://api.vachana.ai/stt/v3 \
> >   -H 'X-API-Key-ID: <API_KEY>' \
> >   -F audio_file='@/path/to/your/audio.wav' \
> >   -F model=prisma-v3.0 \
> >   -F language_code=indic-auto
> > ```
> >
> > ```python theme={null}
> > import requests
> >
> > with open("/path/to/your/audio.wav", "rb") as f:
> >     r = requests.post(
> >         "https://api.vachana.ai/stt/v3",
> >         headers={"X-API-Key-ID": "<API_KEY>"},
> >         files={"audio_file": ("audio.wav", f, "audio/wav")},
> >         data={"model": "prisma-v3.0", "language_code": "indic-auto"},
> >         timeout=60,
> >     )
> > print(r.json())
> > ```
> >
> > With one language and output style:
> >
> > ```bash theme={null}
> > # One language, numbers as digits
> > curl -X POST https://api.vachana.ai/stt/v3 \
> >   -H 'X-API-Key-ID: <API_KEY>' \
> >   -F audio_file='@/path/to/your/audio.wav' \
> >   -F model=prisma-v3.0 \
> >   -F language_code=hi-IN \
> >   -F format=transcribe
> > ```
> >
> > #### Prisma v2.5 (default)
> >
> > ```bash theme={null}
> > curl -X POST https://api.vachana.ai/stt/v3 \
> >   -H 'Content-Type: multipart/form-data' \
> >   -H 'X-API-Key-ID: <API_KEY>' \
> >   -F audio_file='@/path/to/your/audio.wav' \
> >   -F language_code=hi-IN
> > ```
> >
> > **Replace these values:**
> >
> > * `<API_KEY>`: Your Gnani API key
> > * `/path/to/your/audio.wav`: Path to your audio file
> > * `hi-IN`: Language code (see [Supported Languages](https://docs.gnani.ai/api/STT/speech-to-text.md#supported-languages))
> >
> > ### Expected STT Response
> >
> > On success, you'll receive a JSON response like this for Prisma v3.0:
> >
> > ```json theme={null}
> > {
> >   "success": true,
> >   "request_id": "5c1f0a52-6d62-4e0b-9a38-2f2b8a8f7a10",
> >   "transcript": "नमस्ते, आप कैसे हैं?",
> >   "model": "prisma-v3.0",
> >   "detected_language_code": "hi-IN",
> >   "processing_time": 0.58,
> >   "end_to_end_latency": 0.66
> > }
> > ```
> >
> > And for Prisma v2.5:
> >
> > ```json theme={null}
> > {
> >   "success": true,
> >   "request_id": "019fd17d-1106-7265-88ab-3ed12d029292",
> >   "transcript": "नमस्ते, आप कैसे हैं?",
> >   "model": "prisma-v2.5"
> > }
> > ```
>
> > [tab] Realtime
> >
> > Stream live audio over WebSocket. See [STT Realtime](https://docs.gnani.ai/api/STT/stt-websocket.md) for the full protocol, headers, and PCM requirements.
> >
> > **Endpoint**
> >
> > ```text theme={null}
> > wss://api.vachana.ai/stt/v3/stream
> > ```
> >
> > **Required headers**
> >
> > | Header | Value |
> > | - | - |
> > | `x-api-key-id` | Your API key |
> > | `model` | `prisma-v3.0` (omit it, or send `prisma-v2.5`, for Prisma v2.5) |
> > | `language_code` | A code such as `hi-IN`, or `indic-auto` (Prisma v3.0 only) |
> >
> > Send **binary PCM frames** only (16-bit mono, 8 or 16 kHz, 1024 bytes per frame). The server returns JSON transcript events:
> >
> > ```json theme={null}
> > {
> >   "type": "transcript",
> >   "text": "Hello, how are you today?",
> >   "segment_id": "seg_abc123",
> >   "latency": 320
> > }
> > ```
> >
> > Example for Prisma v3.0 in Python (uses the `websockets` package):
> >
> > ```python theme={null}
> > import asyncio, json, websockets
> >
> > HEADERS = {
> >     "x-api-key-id": "<API_KEY>",
> >     "model": "prisma-v3.0",
> >     "language_code": "indic-auto",
> >     # "language_code" can also be a list such as "hi-IN,en-IN"
> >     "x-sample-rate": "16000",
> > }
> >
> > async def run(pcm_chunks):
> >     async with websockets.connect(
> >         "wss://api.vachana.ai/stt/v3/stream",
> >         additional_headers=HEADERS,            # `extra_headers` on websockets < 13
> >     ) as ws:
> >         async def send():
> >             for chunk in pcm_chunks:           # 16-bit mono PCM bytes
> >                 await ws.send(chunk)
> >                 await asyncio.sleep(0.1)
> >             await ws.send(json.dumps({"type": "commit"}))
> >
> >         async def receive():
> >             async for raw in ws:
> >                 frame = json.loads(raw)
> >                 kind = frame["type"]
> >                 if kind == "transcript":
> >                     print(frame.get("detected_language_code"), frame["text"])
> >                 elif kind == "error":
> >                     print("error:", frame["message"])
> >
> >         await asyncio.gather(send(), receive())
> > ```

> [tab] Text-to-Speech (TTS)
>
> > [!TIP]
> >
> > Timbre v2.5 is now the recommended TTS model. Migrate from Timbre v2.0 to continue receiving the latest improvements. Timbre v2.0 will be deprecated soon.
>
> > [tab] REST
> >
> > Have your input text ready. Choose a voice from the [Voice Catalog](https://docs.gnani.ai/api/TTS/available-voices.md).
> >
> > ### Your First Text-to-Speech Call
> >
> > Minimal example for REST TTS (synchronous audio). This endpoint returns the full synthesized audio as a binary response.
> >
> > ```bash theme={null}
> > curl -X POST https://api.vachana.ai/api/v1/tts/inference \
> >   -H 'Content-Type: application/json' \
> >   -H 'X-API-Key-ID: <API_KEY>' \
> >   -d '{
> >         "text": "नमस्ते, आप कैसे हैं?",
> >         "voice": "Nalini",
> >         "model": "timbre-v2.5",
> >         "language": "hi-IN",
> >         "speed": 1.0,
> >         "audio_config": {
> >           "sample_rate": 48000,
> >           "num_channels": 1,
> >           "sample_width": 2,
> >           "encoding": "linear_pcm",
> >           "container": "wav"
> >         }
> >       }' \
> >   --output response.wav
> > ```
> >
> > ### Expected TTS Response
> >
> > A successful request will return a `200 OK` HTTP status. The response body will contain raw binary audio data representing the synthesized text, adhering to the format specified in your `audio_config`.
> >
> > ```http theme={null}
> > HTTP/1.1 200 OK
> > Content-Type: audio/wav
> >
> > <binary audio data>
> > ```
>
> > [tab] Streaming
> >
> > This endpoint streams synthesized audio using Server-Sent Events (SSE). Audio is generated and delivered incrementally as it becomes available.
> >
> > ### Your First Streaming Call
> >
> > ```bash theme={null}
> > curl -X POST https://api.vachana.ai/api/v1/tts/sse \
> >   -H 'Content-Type: application/json' \
> >   -H 'X-API-Key-ID: <API_KEY>' \
> >   -d '{
> >         "text": "नमस्ते, आप कैसे हैं?",
> >         "voice": "Nalini",
> >         "model": "timbre-v2.5",
> >         "language": "hi-IN",
> >         "speed": 1.0,
> >         "audio_config": {
> >           "sample_rate": 48000,
> >           "encoding": "linear_pcm",
> >           "container": "wav"
> >         }
> >       }'
> > ```
> >
> > ### Expected SSE Response
> >
> > A successful request will return a `200 OK` HTTP status. The response body will contain a stream of server-sent events. Each chunk contains base64 encoded audio fragments.
> >
> > ```http theme={null}
> > HTTP/1.1 200 OK
> > Content-Type: text/event-stream
> >
> > event: start
> > data: {"status": "streaming_started", "text": "नमस्ते, आप कैसे हैं?"}
> >
> > event: chunk
> > data: {"chunk_index": 1, "audio": "<base64-encoded audio>", "is_final": false}
> >
> > event: complete
> > data: {"chunk_index": 2, "audio": "", "is_final": true}
> > ```
>
> > [tab] Realtime
> >
> > Connect over WebSocket for lowest latency. See [TTS Realtime](https://docs.gnani.ai/api/TTS/tts-websocket.md) for message types and `audio_config` options.
> >
> > **Endpoint**
> >
> > ```text theme={null}
> > wss://api.vachana.ai/api/v1/tts
> > ```
> >
> > Send a JSON payload after connecting (include `X-API-Key-ID` in the upgrade headers):
> >
> > ```json theme={null}
> > {
> >   "text": "नमस्ते, आप कैसे हैं?",
> >   "voice": "Nalini",
> >   "model": "timbre-v2.5",
> >   "language": "hi-IN",
> >   "audio_config": {
> >     "sample_rate": 48000,
> >     "encoding": "linear_pcm",
> >     "container": "wav"
> >   }
> > }
> > ```
> >
> > The server streams JSON messages with base64 audio chunks (`start`, then `audio`, then `complete`).

> [tab] Voice Cloning (VC)
>
> Voice cloning works in two steps:
>
> 1. **Generate embeddings** — upload a reference audio file to get a `speaker_embedding`
> 2. **Synthesize** — pass the embedding with your text to any VC TTS endpoint
>
> ### Step 1: Generate Voice Embeddings
>
> Upload a reference audio file (WAV/MP3, ideally 5–30 seconds of clear speech):
>
> ```bash theme={null}
> curl -X POST https://api.vachana.ai/api/v1/tts/voice-clone/embeddings \
>   -H 'X-API-Key-ID: <API_KEY>' \
>   -F audio_file='@/path/to/reference.wav'
> ```
>
> **Replace these values:**
>
> * `<API_KEY>`: Your Gnani API key
> * `/path/to/reference.wav`: Path to your reference audio file
>
> ### Expected Embeddings Response
>
> ```json theme={null}
> {
>   "embedding": "<embedding-string>",
>   "shape": [1, 768],
>   "dtype": "torch.bfloat16"
> }
> ```
>
> ### Step 2: Synthesize with Your Cloned Voice
>
> > [tab] REST
> >
> > Pass the `speaker_embedding` from Step 1 to synthesize audio in your cloned voice:
> >
> > ```bash theme={null}
> > curl -X POST https://api.vachana.ai/api/v1/tts/inference \
> >   -H 'Content-Type: application/json' \
> >   -H 'X-API-Key-ID: <API_KEY>' \
> >   -d '{
> >         "text": "नमस्ते, आप कैसे हैं?",
> >         "model": "vachana-vc-v1",
> >         "audio_config": {
> >           "sample_rate": 44100,
> >           "num_channels": 1,
> >           "sample_width": 2,
> >           "encoding": "linear_pcm",
> >           "container": "wav"
> >         },
> >         "speaker_embedding": {
> >           "embedding": "<your-embedding-string>",
> >           "shape": [1, 768],
> >           "dtype": "torch.bfloat16"
> >         }
> >       }' \
> >   --output cloned_voice.wav
> > ```
> >
> > A successful request returns a `200 OK` with raw binary audio data in the specified format.
>
> > [tab] Streaming
> >
> > Stream cloned voice audio progressively via Server-Sent Events:
> >
> > ```bash theme={null}
> > curl -X POST https://api.vachana.ai/api/v1/tts/sse \
> >   -H 'Content-Type: application/json' \
> >   -H 'X-API-Key-ID: <API_KEY>' \
> >   -d '{
> >         "text": "नमस्ते, आप कैसे हैं?",
> >         "model": "vachana-vc-v1",
> >         "speaker_embedding": {
> >           "embedding": "<your-embedding-string>",
> >           "shape": [1, 768],
> >           "dtype": "torch.bfloat16"
> >         }
> >       }'
> > ```
> >
> > The response streams base64-encoded audio chunks as server-sent events, identical in format to the TTS SSE response.
>
> > [tab] Realtime
> >
> > For the lowest latency, stream text and receive cloned voice audio over a WebSocket:
> >
> > ```javascript theme={null}
> > const ws = new WebSocket("wss://api.vachana.ai/api/v1/tts", {
> >   headers: {
> >     "Content-Type": "application/json",
> >     "X-API-Key-ID": "<API_KEY>",
> >   },
> > });
> >
> > ws.on("open", () => {
> >   ws.send(JSON.stringify({
> >     text: "नमस्ते, आप कैसे हैं?",
> >     model: "vachana-vc-v1",
> >     audio_config: { sample_rate: 44100, encoding: "linear_pcm" },
> >     speaker_embedding: {
> >       embedding: "<your-embedding-string>",
> >       shape: [1, 768],
> >       dtype: "torch.bfloat16",
> >     },
> >   }));
> > });
> >
> > ws.on("message", (data) => {
> >   // Handle binary PCM audio chunks
> > });
> > ```
> >
> > The server streams binary PCM audio chunks over the WebSocket connection.

***

## Next Steps

* **Speech-to-Text**: [Overview](https://docs.gnani.ai/api/STT/overview.md), [STT REST](https://docs.gnani.ai/api/STT/speech-to-text.md) and [STT Realtime](https://docs.gnani.ai/api/STT/stt-websocket.md)
* **Models**: [Models](https://docs.gnani.ai/api/STT/models/overview.md) and [Prisma v3.0](https://docs.gnani.ai/api/STT/models/prisma-v3.md)
* **Text-to-Speech**: [REST](https://docs.gnani.ai/api/TTS/tts-inference.md), [Streaming (SSE)](https://docs.gnani.ai/api/TTS/tts-sse.md), and [Realtime](https://docs.gnani.ai/api/TTS/tts-websocket.md)
* **Voice Cloning**: [VC Embeddings](https://docs.gnani.ai/api/VC/voice-clone-embeddings.md), [REST](https://docs.gnani.ai/api/VC/vc-inference.md), [Streaming](https://docs.gnani.ai/api/VC/vc-sse.md), and [Realtime](https://docs.gnani.ai/api/VC/vc-websocket.md)
* **Batch transcription**: [Batch transcription](https://docs.gnani.ai/api/STTBatch/Introduction.md)
* **Errors**: [Error Reference](https://docs.gnani.ai/api/introduction/errors.md)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.