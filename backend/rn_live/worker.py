import logging
import threading
import time
from datetime import timedelta

from sqlalchemy import and_, or_, select, update

from .config import Settings
from .db import Job, Recording, database, initialize_database, mark_claims_stale, now, uid
from .schemas import Segment, Speaker
from .transcription import process_audio

log = logging.getLogger(__name__)


def claim(sessions, settings):
    with sessions.begin() as session:
        available = or_(Job.status == "queued", and_(Job.status == "running", Job.lease_until < now()))
        candidate = session.execute(select(Job.id, Job.recording_id).where(available)).first()
        if candidate is None:
            return None
        job_id, recording_id = candidate
        item = session.scalar(select(Recording).where(Recording.id == recording_id).with_for_update(skip_locked=True))
        if item is None:
            return None
        token = uid()
        changed = session.execute(update(Job).where(Job.id == job_id, available).values(status="running", token=token, lease_until=now() + timedelta(seconds=settings.lease_seconds), attempts=Job.attempts + 1))
        if changed.rowcount != 1:
            return None
        item.status, item.error = "transcribing", None
        return job_id, token, item.id, item.suffix, item.speaker_count, item.duration_ms


def heartbeat(sessions, job_id, token, settings, stop):
    while not stop.wait(max(1, settings.lease_seconds / 3)):
        try:
            with sessions.begin() as session:
                result = session.execute(update(Job).where(Job.id == job_id, Job.token == token, Job.status == "running").values(lease_until=now() + timedelta(seconds=settings.lease_seconds)))
                if result.rowcount != 1:
                    return
        except Exception:
            log.exception("No se pudo renovar el arrendamiento")


def run_once(settings, processor=process_audio):
    engine, sessions = database(settings.database_url)
    try:
        work = claim(sessions, settings)
        if not work:
            return False
        job_id, token, recording_id, suffix, count, duration = work
        stop = threading.Event()
        thread = threading.Thread(target=heartbeat, args=(sessions, job_id, token, settings, stop), daemon=True)
        thread.start()
        try:
            speakers, segments = processor(settings.storage_dir / f"{recording_id}{suffix}", count, settings)
            speakers = [Speaker.model_validate(s).model_dump() for s in speakers]
            speaker_ids = {s["id"] for s in speakers}
            if len(speakers) > 4 or len(speaker_ids) != len(speakers):
                raise RuntimeError("Diarización fuera del límite de hablantes")
            normalized = []
            for raw in segments:
                value = Segment.model_validate(raw).model_dump()
                value.update(id=uid(), original_text=value["text"], reviewed=False)
                if value["end_ms"] > duration or (value["speaker_id"] is not None and value["speaker_id"] not in speaker_ids):
                    raise RuntimeError("La transcripción contiene tiempos o hablantes inválidos")
                normalized.append(value)
            with sessions.begin() as session:
                # Mismo orden de bloqueo que la API: grabación antes del trabajo.
                item = session.scalar(select(Recording).where(Recording.id == recording_id).with_for_update())
                result = session.execute(update(Job).where(Job.id == job_id, Job.token == token, Job.status == "running").values(status="completed", token=None, lease_until=None))
                if result.rowcount == 1 and item:
                    mark_claims_stale(session, item.id)
                    item.speakers, item.segments = speakers, normalized
                    item.status, item.error = "ready_for_review", None
                    item.revision += 1
        except Exception as exc:
            message = str(exc).replace(settings.hf_token, "[oculto]") if settings.hf_token else str(exc)
            log.error("Falló el trabajo %s: %s", job_id, message)
            with sessions.begin() as session:
                item = session.scalar(select(Recording).where(Recording.id == recording_id).with_for_update())
                result = session.execute(update(Job).where(Job.id == job_id, Job.token == token, Job.status == "running").values(status="failed", token=None, lease_until=None))
                if result.rowcount == 1 and item:
                    item.status = "failed"
                    item.error = message[:1000]
        finally:
            stop.set()
            thread.join(timeout=5)
        return True
    finally:
        engine.dispose()


def main():
    logging.basicConfig(level=logging.INFO)
    settings = Settings()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    engine, _ = database(settings.database_url)
    initialize_database(engine)
    engine.dispose()
    while True:
        try:
            did_transcription = run_once(settings)
            from .claims_worker import run_claim_once
            did_claim = run_claim_once(settings)
            if not did_transcription and not did_claim:
                time.sleep(2)
        except Exception:
            log.error("Error de infraestructura; se reintentará en cinco segundos")
            time.sleep(5)


if __name__ == "__main__":
    main()
