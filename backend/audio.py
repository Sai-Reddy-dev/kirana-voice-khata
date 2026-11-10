import shutil
import subprocess


class AudioInputError(ValueError):
    pass


class AudioConversionError(RuntimeError):
    pass


_SUPPORTED_MIME_TYPES = {
    "audio/wav": (".wav", "audio/wav"),
    "audio/x-wav": (".wav", "audio/wav"),
    "audio/wave": (".wav", "audio/wav"),
    "audio/mpeg": (".mp3", "audio/mpeg"),
    "audio/mp3": (".mp3", "audio/mpeg"),
    "audio/ogg": (".ogg", "audio/ogg"),
    "audio/flac": (".flac", "audio/flac"),
    "audio/x-flac": (".flac", "audio/flac"),
    "audio/aac": (".aac", "audio/aac"),
    "audio/mp4": (".m4a", "audio/mp4"),
    "audio/x-m4a": (".m4a", "audio/mp4"),
}

_CONVERTIBLE_MIME_TYPES = {
    "audio/webm",
    "video/webm",
    "video/mp4",
}
_CONVERSION_TIMEOUT_SECONDS = 20


def prepare_audio(
    audio_bytes: bytes,
    mime_type: str,
) -> tuple[bytes, str, str]:
    if not audio_bytes:
        raise AudioInputError("Audio file is empty")
    if not mime_type:
        raise AudioInputError("Audio MIME type is required")

    normalized_mime_type = mime_type.split(";", 1)[0].strip().lower()
    supported = _SUPPORTED_MIME_TYPES.get(normalized_mime_type)
    if supported is not None:
        extension, provider_mime_type = supported
        return audio_bytes, provider_mime_type, f"audio{extension}"

    if normalized_mime_type not in _CONVERTIBLE_MIME_TYPES:
        raise AudioInputError("Unsupported audio format")

    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        raise AudioConversionError(
            "Audio conversion is unavailable because ffmpeg is not installed"
        )

    try:
        converted = subprocess.run(
            [
                ffmpeg_path,
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                "pipe:0",
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                "-f",
                "wav",
                "pipe:1",
            ],
            input=audio_bytes,
            capture_output=True,
            check=False,
            timeout=_CONVERSION_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise AudioConversionError("Audio conversion timed out") from error
    except OSError as error:
        raise AudioConversionError("Audio conversion could not be started") from error

    if converted.returncode != 0 or not converted.stdout:
        raise AudioConversionError("Audio conversion failed")
    return converted.stdout, "audio/wav", "audio.wav"
