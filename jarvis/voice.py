"""Local voice: Whisper for speech-to-text, Kokoro for text-to-speech.

Both are optional imports and are loaded lazily on first use, so the text path
works on machines without them. Install with:  pip install -e '.[voice]'
Nothing here talks to a cloud service; the first run downloads model weights
from Hugging Face, after that it is fully offline.
"""
from __future__ import annotations

import io
import os
import re
import tempfile
import threading
import wave


class VoiceUnavailable(RuntimeError):
    pass


class STT:
    def __init__(self, model_size: str = "base.en"):
        self.model_size = model_size
        self._model = None
        self._backend = ""
        self._lock = threading.Lock()

    def _load(self):
        with self._lock:
            if self._model is not None:
                return
            try:
                from faster_whisper import WhisperModel  # type: ignore
                self._model = WhisperModel(self.model_size, device="auto", compute_type="int8")
                self._backend = "faster-whisper"
                return
            except ImportError:
                pass
            try:
                import whisper  # type: ignore  (openai-whisper; needs ffmpeg)
                self._model = whisper.load_model(self.model_size)
                self._backend = "openai-whisper"
            except ImportError as e:
                raise VoiceUnavailable("Install faster-whisper (pip install faster-whisper) for local STT") from e

    def transcribe(self, audio: bytes, suffix: str = ".webm") -> str:
        self._load()
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(audio)
            path = f.name
        try:
            if self._backend == "faster-whisper":
                segments, _ = self._model.transcribe(path, vad_filter=True)
                return " ".join(s.text.strip() for s in segments).strip()
            return self._model.transcribe(path)["text"].strip()
        finally:
            os.unlink(path)


def speakable(text: str, max_chars: int = 1500) -> str:
    """Strip markdown so TTS doesn't read out asterisks and link syntax."""
    t = re.sub(r"```.*?```", " (code omitted) ", text, flags=re.S)
    t = re.sub(r"\[\[([^\]|]+)(\|[^\]]+)?\]\]", r"\1", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    t = re.sub(r"[#*_`>]+", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:max_chars]


class TTS:
    SAMPLE_RATE = 24000

    def __init__(self, voice: str = "af_heart", lang_code: str = "a"):
        self.voice = voice
        self.lang_code = lang_code
        self._pipeline = None
        self._lock = threading.Lock()

    def _load(self):
        with self._lock:
            if self._pipeline is None:
                try:
                    from kokoro import KPipeline  # type: ignore
                except ImportError as e:
                    raise VoiceUnavailable("Install kokoro (pip install kokoro soundfile) for local TTS") from e
                self._pipeline = KPipeline(lang_code=self.lang_code)

    def synthesize(self, text: str) -> bytes:
        """Return a 16-bit mono WAV."""
        self._load()
        import numpy as np  # kokoro depends on numpy
        pieces = [np.asarray(audio, dtype=np.float32)
                  for _, _, audio in self._pipeline(speakable(text), voice=self.voice) if audio is not None]
        if not pieces:
            raise VoiceUnavailable("Kokoro produced no audio")
        pcm = (np.clip(np.concatenate(pieces), -1, 1) * 32767).astype("<i2").tobytes()
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.SAMPLE_RATE)
            w.writeframes(pcm)
        return buf.getvalue()
