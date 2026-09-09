import json
import subprocess
import wave
from pathlib import Path


class MediaError(ValueError):
    pass


def probe(path: Path, settings) -> int:
    if path.suffix == ".wav":
        try:
            with wave.open(str(path), "rb") as source:
                frames, rate = source.getnframes(), source.getframerate()
                expected = frames * source.getnchannels() * source.getsampwidth()
                actual = 0
                while chunk := source.readframes(65536):
                    actual += len(chunk)
                if frames <= 0 or actual != expected:
                    raise MediaError("WAV vacío o truncado.")
                duration = round(frames * 1000 / rate)
        except (wave.Error, EOFError, ZeroDivisionError) as exc:
            raise MediaError("El archivo no es un WAV PCM válido.") from exc
    else:
        try:
            process = subprocess.run([settings.ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)], capture_output=True, timeout=30, check=True)
            data = json.loads(process.stdout)
            audio = [s for s in data["streams"] if s["codec_type"] == "audio"]
            video = [s for s in data["streams"] if s["codec_type"] == "video" and not s.get("disposition", {}).get("attached_pic")]
            if not audio:
                raise MediaError("La grabación no contiene audio.")
            formats = data["format"]["format_name"].split(",")
            if path.suffix == ".mp3" and ("mp3" not in formats or any(s["codec_name"] != "mp3" for s in audio) or video):
                raise MediaError("Se requiere audio MP3.")
            if path.suffix == ".mp4" and ("mp4" not in formats or not video or any(s["codec_name"] != "h264" for s in video) or any(s["codec_name"] != "aac" for s in audio)):
                raise MediaError("Se requiere MP4 con video H.264 y audio AAC.")
            duration = round(float(data["format"]["duration"]) * 1000)
        except FileNotFoundError as exc:
            raise MediaError("Instala FFmpeg/ffprobe para validar MP3 y MP4.") from exc
        except (subprocess.SubprocessError, KeyError, ValueError, OverflowError) as exc:
            if isinstance(exc, MediaError):
                raise
            raise MediaError("No se pudo validar el archivo multimedia.") from exc
    if not 0 < duration <= settings.max_duration_ms:
        raise MediaError("La duración debe ser positiva y no superar el límite configurado.")
    return duration


def extract(source: Path, target: Path, settings):
    try:
        subprocess.run([settings.ffmpeg, "-nostdin", "-v", "error", "-y", "-copyts", "-start_at_zero", "-i", str(source), "-map", "0:a:0", "-vn", "-af", "aresample=16000:async=1:first_pts=0", "-ac", "1", "-ar", "16000", str(target)], check=True, capture_output=True, timeout=600)
    except FileNotFoundError as exc:
        raise MediaError("FFmpeg no está instalado o RN_FFMPEG no apunta a su ejecutable.") from exc
    except subprocess.SubprocessError as exc:
        raise MediaError("No se pudo extraer el audio.") from exc
