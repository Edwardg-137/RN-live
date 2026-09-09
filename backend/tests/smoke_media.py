"""Comprobación multimedia dentro del contenedor: python backend/tests/smoke_media.py."""
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from rn_live.config import Settings
from rn_live.media import extract, probe


with TemporaryDirectory() as directory:
    settings = Settings()
    root = Path(directory)
    for extension, arguments in [
        (".mp3", ["-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:a", "libmp3lame"]),
        (".mp4", ["-f", "lavfi", "-i", "color=c=black:s=320x180:d=2", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest"]),
    ]:
        source = root / f"test{extension}"
        subprocess.run(["ffmpeg", "-v", "error", "-y", *arguments, str(source)], check=True)
        assert 1900 <= probe(source, settings) <= 2200
        target = root / "extracted.wav"
        extract(source, target, settings)
        assert 1900 <= probe(target, settings) <= 2200
        print(f"OK {extension}: validación y extracción")
    delayed = root / "delayed.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=320x180:d=3", "-itsoffset", "1", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:v", "libx264", "-c:a", "aac", str(delayed)], check=True)
    extract(delayed, root / "delayed.wav", settings)
    assert 2900 <= probe(root / "delayed.wav", settings) <= 3100, "Se perdió el retraso inicial del audio"
    print("OK: se conserva un segundo inicial sin audio")
