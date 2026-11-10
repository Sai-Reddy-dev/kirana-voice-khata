// voice.js — MediaRecorder wrapper for Kirana Voice Khata.
//
// Handles microphone permission, recording lifecycle, and duration timer.
// Returns a WebM/Opus blob (with OGG fallback mime selection).

export class VoiceRecorder {
  constructor() {
    this.mediaRecorder = null;
    this.stream = null;
    this.chunks = [];
    this.isRecording = false;
    this.startTime = 0;
    this.timerInterval = null;
    this.onDurationUpdate = null; // callback(secs)
    this.onStop = null; // callback(blob)
    this.onError = null; // callback(Error)
  }

  // Returns true if the browser supports recording.
  static isSupported() {
    return (
      typeof navigator !== "undefined" &&
      navigator.mediaDevices &&
      typeof navigator.mediaDevices.getUserMedia === "function" &&
      typeof window !== "undefined" &&
      window.MediaRecorder
    );
  }

  // Pick the best supported MIME type.
  static pickMimeType() {
    const candidates = [
      "audio/webm;codecs=opus",
      "audio/webm",
      "audio/ogg;codecs=opus",
      "audio/mp4",
    ];
    for (const c of candidates) {
      if (window.MediaRecorder && MediaRecorder.isTypeSupported(c)) {
        return c;
      }
    }
    return ""; // let browser decide
  }

  // Start recording. Resolves when recording begins.
  // Rejects with a typed Error if permission denied or unsupported.
  async start() {
    if (this.isRecording) return;
    if (!VoiceRecorder.isSupported()) {
      const e = new Error("UNSUPPORTED");
      throw e;
    }

    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      if (err && (err.name === "NotAllowedError" || err.name === "PermissionDeniedError")) {
        throw new Error("PERMISSION_DENIED");
      }
      if (err && (err.name === "NotFoundError" || err.name === "DevicesNotFoundError")) {
        throw new Error("NO_MICROPHONE");
      }
      throw new Error("MIC_ERROR");
    }

    this.stream = stream;
    this.chunks = [];

    const mime = VoiceRecorder.pickMimeType();
    let recorder;
    try {
      recorder = mime
        ? new MediaRecorder(stream, { mimeType: mime })
        : new MediaRecorder(stream);
    } catch {
      // Fallback: default mimeType.
      recorder = new MediaRecorder(stream);
    }

    this.mediaRecorder = recorder;

    recorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) {
        this.chunks.push(e.data);
      }
    };

    recorder.onerror = () => {
      this._cleanup();
      if (this.onError) this.onError(new Error("RECORD_ERROR"));
    };

    recorder.onstop = () => {
      const blob = new Blob(this.chunks, { type: recorder.mimeType || "audio/webm" });
      this._cleanup();
      if (this.onStop) this.onStop(blob);
    };

    recorder.start();
    this.isRecording = true;
    this.startTime = Date.now();
    this._startTimer();
  }

  // Stop recording. The onStop callback receives the audio Blob.
  stop() {
    if (!this.isRecording || !this.mediaRecorder) return;
    this.isRecording = false;
    this._stopTimer();
    if (this.mediaRecorder.state !== "inactive") {
      this.mediaRecorder.stop();
    }
  }

  // Cancel without producing a blob.
  cancel() {
    this.isRecording = false;
    this._stopTimer();
    if (this.mediaRecorder && this.mediaRecorder.state !== "inactive") {
      // Silence the onStop callback for a cancel.
      this.onStop = null;
      try {
        this.mediaRecorder.stop();
      } catch {
        // ignore
      }
    }
    this._cleanup();
  }

  _startTimer() {
    this._stopTimer();
    this.timerInterval = setInterval(() => {
      const secs = Math.floor((Date.now() - this.startTime) / 1000);
      if (this.onDurationUpdate) this.onDurationUpdate(secs);
    }, 250);
  }

  _stopTimer() {
    if (this.timerInterval) {
      clearInterval(this.timerInterval);
      this.timerInterval = null;
    }
  }

  _cleanup() {
    this._stopTimer();
    if (this.stream) {
      this.stream.getTracks().forEach((tr) => tr.stop());
      this.stream = null;
    }
    this.mediaRecorder = null;
    this.chunks = [];
    this.isRecording = false;
  }
}

// Decode a base64 audio string into a playable Blob.
// Handles plain base64 and data: URIs. Never logs the raw string.
export function base64ToAudioBlob(b64, mime = "audio/webm") {
  let cleaned = b64;
  if (cleaned.startsWith("data:")) {
    // "data:audio/webm;base64,AAAA..."
    const comma = cleaned.indexOf(",");
    if (comma >= 0) {
      const meta = cleaned.slice(5, comma); // "audio/webm;base64"
      const semicolon = meta.indexOf(";");
      if (semicolon >= 0) {
        mime = meta.slice(0, semicolon) || mime;
      }
      cleaned = cleaned.slice(comma + 1);
    }
  }
  // Strip whitespace/newlines.
  cleaned = cleaned.replace(/\s/g, "");
  const byteChars = atob(cleaned);
  const len = byteChars.length;
  const bytes = new Uint8Array(len);
  for (let i = 0; i < len; i++) {
    bytes[i] = byteChars.charCodeAt(i);
  }
  return new Blob([bytes], { type: mime });
}

// Given a replyAudio descriptor ({kind, value}) from the API adapter,
// produce a playable object URL (or null). Caller should revokeObjectURL
// after playback.
export function makePlayableAudio(replyAudio) {
  if (!replyAudio) return null;
  if (replyAudio.kind === "url") {
    return { url: replyAudio.value, revoke: false };
  }
  if (replyAudio.kind === "base64") {
    const blob = base64ToAudioBlob(
      replyAudio.value,
      replyAudio.contentType || "application/octet-stream",
    );
    const url = URL.createObjectURL(blob);
    return { url, revoke: true };
  }
  return null;
}
