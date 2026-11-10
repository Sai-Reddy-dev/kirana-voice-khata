import argparse
import json
import mimetypes
from pathlib import Path
import sys

import requests


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Upload a recorded audio file to the Kirana Voice Khata API."
    )
    parser.add_argument("audio_path", type=Path)
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="API base URL (default: http://127.0.0.1:8000)",
    )
    parser.add_argument("--pending-id", help="Pending ID for spoken avunu/vaddu")
    parser.add_argument("--language", choices=("te-IN", "en-IN"), default="te-IN")
    args = parser.parse_args()

    if not args.audio_path.is_file():
        print(f"Audio file not found: {args.audio_path}", file=sys.stderr)
        return 2

    mime_type = mimetypes.guess_type(args.audio_path.name)[0]
    if mime_type is None:
        print("Could not determine audio MIME type from the file extension.", file=sys.stderr)
        return 2

    form_data = {"language": args.language}
    if args.pending_id is not None:
        form_data["pending_id"] = args.pending_id

    try:
        with args.audio_path.open("rb") as audio_file:
            response = requests.post(
                f"{args.base_url.rstrip('/')}/api/voice",
                files={
                    "audio_file": (
                        args.audio_path.name,
                        audio_file,
                        mime_type,
                    )
                },
                data=form_data,
                timeout=60,
            )
    except requests.RequestException as error:
        print(f"Voice API request failed: {error}", file=sys.stderr)
        return 1

    try:
        body = response.json()
    except requests.exceptions.JSONDecodeError:
        print(f"Voice API returned HTTP {response.status_code} without JSON.", file=sys.stderr)
        return 1

    print(f"Transcript: {body.get('transcript', '')}")
    print(json.dumps(body, ensure_ascii=False, indent=2))
    return 0 if response.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
