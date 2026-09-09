"""Prueba técnica de ASR con silencio; no mide precisión lingüística."""
import wave
from pathlib import Path
from tempfile import TemporaryDirectory

from rn_live.config import Settings
from rn_live.transcription import process_audio

with TemporaryDirectory() as directory:
    path = Path(directory) / "silence.wav"
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\0\0" * 16000 * 2)
    speakers, segments = process_audio(path, 1, Settings(whisper_model="tiny"))
    assert len(speakers) == 1
    assert segments == []
    print("OK: FFmpeg + faster-whisper tiny + VAD; silencio sin texto inventado")
