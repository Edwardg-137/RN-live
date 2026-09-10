import logging
import threading
from datetime import timedelta

from sqlalchemy import and_, or_, select, update

from .claims import extract_claims
from .config import Settings
from .db import AnalysisRun, Claim, ClaimSegment, Recording, database, initialize_database, now, uid

log = logging.getLogger(__name__)


def claim(sessions, settings):
    with sessions.begin() as session:
        available = or_(
            AnalysisRun.status == "queued",
            and_(
                AnalysisRun.status == "running",
                or_(AnalysisRun.lease_until.is_(None), AnalysisRun.lease_until < now()),
            ),
        )
        candidate = session.execute(
            select(AnalysisRun.id, AnalysisRun.recording_id, AnalysisRun.recording_revision)
            .where(AnalysisRun.kind == "claim_extraction", available)
            .order_by(AnalysisRun.created_at)
        ).first()
        if candidate is None:
            return None
        run_id, recording_id, revision = candidate
        recording = session.scalar(
            select(Recording).where(Recording.id == recording_id).with_for_update(skip_locked=True)
        )
        if recording is None:
            session.execute(
                update(AnalysisRun)
                .where(AnalysisRun.id == run_id, available)
                .values(
                    status="failed",
                    error="Grabación no encontrada",
                    completed_at=now(),
                    token=None,
                    lease_until=None,
                )
            )
            return False
        token = uid()
        changed = session.execute(
            update(AnalysisRun)
            .where(AnalysisRun.id == run_id, available)
            .values(
                status="running",
                token=token,
                lease_until=now() + timedelta(seconds=settings.lease_seconds),
                attempts=AnalysisRun.attempts + 1,
                error=None,
                completed_at=None,
            )
        )
        if changed.rowcount != 1:
            return None
        return {
            "run_id": run_id,
            "token": token,
            "recording_id": recording_id,
            "revision": revision,
            "kind": recording.kind,
            "segments": list(recording.segments or []),
            "speakers": list(recording.speakers or []),
            "content_date": recording.content_date,
            "scope": recording.scope,
        }


def heartbeat(sessions, run_id, token, settings, stop):
    while not stop.wait(max(1, settings.lease_seconds / 3)):
        try:
            with sessions.begin() as session:
                result = session.execute(
                    update(AnalysisRun)
                    .where(
                        AnalysisRun.id == run_id,
                        AnalysisRun.token == token,
                        AnalysisRun.status == "running",
                    )
                    .values(lease_until=now() + timedelta(seconds=settings.lease_seconds))
                )
                if result.rowcount != 1:
                    return
        except Exception:
            log.exception("No se pudo renovar el arrendamiento de afirmaciones")


def run_claim_once(settings: Settings, client=None) -> bool:
    engine, sessions = database(settings.database_url)
    try:
        work = claim(sessions, settings)
        if work is None:
            return False
        if work is False:
            return True
        run_id = work["run_id"]
        token = work["token"]
        stop = threading.Event()
        thread = threading.Thread(
            target=heartbeat, args=(sessions, run_id, token, settings, stop), daemon=True
        )
        thread.start()
        if client is None:
            from .openrouter import OpenRouterClient

            client = OpenRouterClient(settings)
            owns_client = True
        else:
            owns_client = False
        try:
            result = extract_claims(
                client,
                work["segments"],
                work["kind"],
                len(work["speakers"]),
                speakers=work["speakers"],
                content_date=work["content_date"],
                scope=work["scope"],
            )
            with sessions.begin() as session:
                current = session.scalar(
                    select(Recording).where(Recording.id == work["recording_id"]).with_for_update()
                )
                owned = and_(
                    AnalysisRun.id == run_id,
                    AnalysisRun.token == token,
                    AnalysisRun.status == "running",
                )
                if current is None or current.revision != work["revision"]:
                    session.execute(
                        update(AnalysisRun)
                        .where(owned)
                        .values(
                            status="stale",
                            error="La revisión del transcript cambió durante el análisis",
                            completed_at=now(),
                            token=None,
                            lease_until=None,
                        )
                    )
                    return True
                changed = session.execute(
                    update(AnalysisRun)
                    .where(owned)
                    .values(
                        status="completed",
                        model=result.model,
                        usage=result.usage,
                        completed_at=now(),
                        token=None,
                        lease_until=None,
                    )
                )
                if changed.rowcount != 1:
                    return True
                by_id = {str(item.get("id")): item for item in work["segments"]}
                speaker_names = {
                    str(speaker["id"]): speaker.get("name") or None for speaker in work["speakers"]
                }
                for position, extracted in enumerate(result.claims):
                    row = Claim(
                        analysis_run_id=run_id,
                        normalized_text=extracted.normalized_text,
                        original_quote=extracted.original_quote,
                        category=extracted.category,
                        verifiable=extracted.verifiable,
                        start_ms=extracted.start_ms,
                        end_ms=extracted.end_ms,
                        ambiguity_notes=extracted.ambiguity_notes,
                        missing_context=extracted.missing_context,
                        position=position,
                    )
                    session.add(row)
                    session.flush()
                    for segment_position, segment_id in enumerate(extracted.segment_ids):
                        segment = by_id[segment_id]
                        speaker_id = segment.get("speaker_id")
                        session.add(
                            ClaimSegment(
                                claim_id=row.id,
                                segment_id=segment_id,
                                start_ms=int(segment["start_ms"]),
                                end_ms=int(segment["end_ms"]),
                                speaker_id=speaker_id,
                                speaker_name=speaker_names.get(str(speaker_id)) if speaker_id else None,
                                position=segment_position,
                            )
                        )
        except Exception as exc:
            message = str(exc)
            if settings.openrouter_api_key:
                message = message.replace(settings.openrouter_api_key, "[oculto]")
            log.error("Falló extracción de afirmaciones %s: %s", run_id, message)
            with sessions.begin() as session:
                session.execute(
                    update(AnalysisRun)
                    .where(
                        AnalysisRun.id == run_id,
                        AnalysisRun.token == token,
                        AnalysisRun.status == "running",
                    )
                    .values(
                        status="failed",
                        error=message[:1000],
                        completed_at=now(),
                        token=None,
                        lease_until=None,
                    )
                )
        finally:
            stop.set()
            thread.join(timeout=5)
            if owns_client:
                client.close()
        return True
    finally:
        engine.dispose()


def main():
    settings = Settings()
    engine, _ = database(settings.database_url)
    initialize_database(engine)
    engine.dispose()
    run_claim_once(settings)


if __name__ == "__main__":
    main()
