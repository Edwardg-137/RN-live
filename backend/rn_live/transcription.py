from pathlib import Path
from tempfile import TemporaryDirectory

from .media import extract


def process_audio(path: Path, speaker_count: int, settings):
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("Instala el extra transcription para una voz o audio para varias voces") from exc
    if speaker_count > 1 and not settings.hf_token:
        raise RuntimeError("Configura RN_HF_TOKEN y acepta las condiciones del modelo de diarización para varias voces")
    with TemporaryDirectory(prefix="rn-live-") as temporary:
        audio = Path(temporary) / "audio.wav"
        extract(path, audio, settings)
        model = WhisperModel(settings.whisper_model, device=settings.whisper_device, compute_type=settings.whisper_compute_type)
        stream, _ = model.transcribe(str(audio), language="es", vad_filter=True, word_timestamps=True)
        transcript = list(stream)
        turns = []
        if speaker_count > 1:
            try:
                from pyannote.audio import Pipeline
            except ImportError as exc:
                raise RuntimeError("Instala el extra audio para separar varias voces (RN_INSTALL_AUDIO=true en Docker)") from exc
            pipeline = Pipeline.from_pretrained(settings.diarization_model, token=settings.hf_token)
            diarized = pipeline(str(audio), num_speakers=speaker_count)
            annotation = getattr(diarized, "speaker_diarization", diarized)
            turns = [(turn.start, turn.end, speaker) for turn, _, speaker in annotation.itertracks(yield_label=True)]
        labels = sorted({speaker for _, _, speaker in turns}) if speaker_count > 1 else ["speaker-1"]
        speakers = [{"id": label, "name": "", "role": "unspecified"} for label in labels]
        segments = []
        for segment in transcript:
            # Separar a nivel de palabra cuando cambia la voz. No inventar identidad
            # en zonas superpuestas: una palabra puede quedar sin atribución.
            units = segment.words or [segment]
            for unit in units:
                start, end = unit.start, unit.end
                text = getattr(unit, "word", None) or getattr(unit, "text", "")
                if not text.strip() or end <= start:
                    continue
                midpoint = (start + end) / 2
                active = {speaker for a, b, speaker in turns if a <= midpoint < b}
                speaker = "speaker-1" if speaker_count == 1 else next(iter(active)) if len(active) == 1 else None
                start_ms, end_ms = round(start * 1000), round(end * 1000)
                if segments and segments[-1]["speaker_id"] == speaker and start_ms - segments[-1]["end_ms"] < 600 and end_ms - segments[-1]["start_ms"] <= 15000:
                    segments[-1]["text"] += text
                    segments[-1]["end_ms"] = end_ms
                else:
                    segments.append({"start_ms": start_ms, "end_ms": end_ms, "text": text, "speaker_id": speaker})
        for segment in segments:
            segment["text"] = segment["text"].strip()
        return speakers, segments
