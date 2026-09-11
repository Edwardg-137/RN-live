from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import delete, select, update

from .config import Settings
from .db import AnalysisRun, Claim, ClaimSegment, Job, Recording, database, initialize_database, mark_claims_stale, now, uid
from .media import MediaError, probe
from .openrouter import OpenRouterClient
from .schemas import ClaimSelection, ClaimUpdate, SegmentReview, SpeakerReview
from .limits import BodyLimit


def describe(recording):
    return {name: getattr(recording, name) for name in ("id", "title", "kind", "speaker_count", "content_date", "scope", "filename", "duration_ms", "status", "error", "revision", "speakers", "created_at")}


def describe_run(run, claims=None):
    value = {name: getattr(run, name) for name in ("id", "recording_id", "recording_revision", "kind", "status", "provider", "model", "prompt_version", "usage", "error", "unreviewed_segment_count", "created_at", "completed_at")}
    if claims is not None:
        value["claims"] = claims
    return value


def describe_claim(session, claim):
    links = [
        {
            "segment_id": link.segment_id,
            "start_ms": link.start_ms,
            "end_ms": link.end_ms,
            "speaker_id": link.speaker_id,
            "speaker_name": link.speaker_name,
            "position": link.position,
            "relation": link.relation,
        }
        for link in session.scalars(select(ClaimSegment).where(ClaimSegment.claim_id == claim.id).order_by(ClaimSegment.relation.desc(), ClaimSegment.position))
    ]
    return {
        "id": claim.id,
        "status": claim.status,
        "revision": claim.revision,
        "normalized_text": claim.normalized_text,
        "original_quote": claim.original_quote,
        "category": claim.category,
        "verifiable": claim.verifiable,
        "start_ms": claim.start_ms,
        "end_ms": claim.end_ms,
        "ambiguity_notes": claim.ambiguity_notes,
        "missing_context": claim.missing_context,
        "conversation_relation": claim.conversation_relation,
        "context_required": claim.context_required,
        "standalone_text": claim.standalone_text or claim.normalized_text,
        "segments": [link for link in links if link["relation"] == "source"],
        "context_segments": [link for link in links if link["relation"] == "context"],
    }


def create_app(settings=None):
    settings = settings or Settings()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    if settings.database_url.startswith("sqlite:///"):
        Path(settings.database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine, sessions = database(settings.database_url)

    @asynccontextmanager
    async def lifespan(_):
        initialize_database(engine)
        yield
        app.state.openrouter.close()
        engine.dispose()

    app = FastAPI(title="RN-live", lifespan=lifespan)
    app.add_middleware(BodyLimit, settings=settings)
    app.state.settings = settings
    app.state.sessions = sessions
    app.state.openrouter = OpenRouterClient(settings)

    def get(session, recording_id, lock=False):
        statement = select(Recording).where(Recording.id == str(recording_id))
        if lock:
            statement = statement.with_for_update()
        item = session.scalar(statement)
        if not item:
            raise HTTPException(404, "Grabación no encontrada")
        return item

    def editable(item):
        if item.status in ("queued", "transcribing"):
            raise HTTPException(409, "Cancela o espera a que termine la transcripción")

    @app.get("/api/health")
    def health():
        return {"status": "ok", "analysis_available": bool(settings.openrouter_api_key), "analysis_provider": "openrouter", "analysis_model": settings.openrouter_model, "version": "0.1.0"}

    @app.get("/api/recordings")
    def recordings():
        with sessions() as session:
            return [describe(r) for r in session.scalars(select(Recording).order_by(Recording.created_at.desc()))]

    @app.post("/api/recordings", status_code=201)
    def upload(file: Annotated[UploadFile, File()], title: Annotated[str, Form(min_length=1, max_length=200)], kind: Annotated[Literal["speech", "debate", "interview"], Form()], speaker_count: Annotated[int, Form(ge=1, le=4)] = 1, content_date: Annotated[date | None, Form()] = None, scope: Annotated[str, Form(max_length=200)] = ""):
        filename = (file.filename or "").replace("\\", "/").split("/")[-1]
        suffix = Path(filename).suffix.lower()
        if suffix not in (".wav", ".mp3", ".mp4") or not title.strip():
            raise HTTPException(422, "Usa WAV, MP3 o MP4 y un título válido")
        identifier = uid()
        destination = settings.storage_dir / f"{identifier}{suffix}"
        try:
            size = 0
            with destination.open("wb") as target:
                while chunk := file.file.read(1024 * 1024):
                    size += len(chunk)
                    if size > settings.max_upload_bytes:
                        raise HTTPException(413, "El archivo supera el límite permitido")
                    target.write(chunk)
            duration = probe(destination, settings)
            with sessions.begin() as session:
                item = Recording(id=identifier, title=title.strip(), kind=kind, speaker_count=speaker_count, content_date=content_date.isoformat() if content_date else None, scope=scope, filename=filename[:255], suffix=suffix, duration_ms=duration)
                session.add(item)
                session.flush()
                result = describe(item)
            return result
        except MediaError as exc:
            destination.unlink(missing_ok=True)
            raise HTTPException(422, str(exc)) from exc
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        finally:
            file.file.close()

    @app.get("/api/recordings/{recording_id}")
    def detail(recording_id: UUID):
        with sessions() as session:
            item = get(session, recording_id)
            return {**describe(item), "segments": item.segments}

    @app.get("/api/recordings/{recording_id}/media")
    def media(recording_id: UUID):
        with sessions() as session:
            item = get(session, recording_id)
            path = settings.storage_dir / f"{item.id}{item.suffix}"
            if not path.is_file():
                raise HTTPException(404, "Archivo no disponible")
            return FileResponse(path, media_type={".wav": "audio/wav", ".mp3": "audio/mpeg", ".mp4": "video/mp4"}[item.suffix])

    @app.delete("/api/recordings/{recording_id}", status_code=204)
    def remove(recording_id: UUID):
        with sessions.begin() as session:
            item = get(session, recording_id, lock=True)
            # Borrado limitado a archivos administrados con el UUID validado.
            (settings.storage_dir / f"{item.id}{item.suffix}").unlink(missing_ok=True)
            session.execute(delete(Job).where(Job.recording_id == item.id))
            session.delete(item)

    @app.get("/api/recordings/{recording_id}/segments")
    def segments(recording_id: UUID):
        with sessions() as session:
            item = get(session, recording_id)
            return {"revision": item.revision, "segments": item.segments}

    @app.put("/api/recordings/{recording_id}/segments")
    def review(recording_id: UUID, body: SegmentReview):
        with sessions.begin() as session:
            item = get(session, recording_id, lock=True)
            editable(item)
            if item.revision != body.revision:
                raise HTTPException(409, "Hay una versión más reciente; vuelve a cargar")
            speaker_ids = {s["id"] for s in item.speakers}
            previous = {s["id"]: s for s in item.segments}
            values, ids = [], set()
            for segment in body.segments:
                if segment.end_ms > item.duration_ms or (segment.speaker_id is not None and segment.speaker_id not in speaker_ids):
                    raise HTTPException(422, "Tiempo fuera de la grabación o hablante desconocido")
                value = segment.model_dump()
                value["id"] = segment.id or uid()
                if value["id"] in ids:
                    raise HTTPException(422, "Identificador de segmento repetido")
                ids.add(value["id"])
                old = previous.get(value["id"])
                value["original_text"] = old["original_text"] if old else segment.text
                value["reviewed"] = True
                values.append(value)
            values.sort(key=lambda s: (s["start_ms"], s["end_ms"]))
            changed = session.execute(update(Recording).where(Recording.id == item.id, Recording.revision == body.revision).values(segments=values, revision=body.revision + 1, status="ready_for_review"))
            if changed.rowcount != 1:
                raise HTTPException(409, "La grabación ha cambiado")
            mark_claims_stale(session, item.id)
            return {"revision": body.revision + 1, "segments": values}

    @app.put("/api/recordings/{recording_id}/speakers")
    def speakers(recording_id: UUID, body: SpeakerReview):
        with sessions.begin() as session:
            item = get(session, recording_id, lock=True)
            editable(item)
            if item.revision != body.revision:
                raise HTTPException(409, "Hay una versión más reciente; vuelve a cargar")
            ids = {s.id for s in body.speakers}
            if len(ids) != len(body.speakers):
                raise HTTPException(422, "Usa hasta cuatro hablantes sin identificadores repetidos")
            if any(s["speaker_id"] is not None and s["speaker_id"] not in ids for s in item.segments):
                raise HTTPException(422, "Reasigna los segmentos antes de eliminar un hablante")
            values = [s.model_dump() for s in body.speakers]
            changed = session.execute(update(Recording).where(Recording.id == item.id, Recording.revision == body.revision).values(speakers=values, revision=body.revision+1))
            if changed.rowcount != 1:
                raise HTTPException(409, "La grabación ha cambiado")
            mark_claims_stale(session, item.id)
            return {"revision": body.revision+1, "speakers": values}

    @app.post("/api/recordings/{recording_id}/transcribe", status_code=202)
    def transcribe(recording_id: UUID):
        with sessions.begin() as session:
            item = get(session, recording_id, lock=True)
            editable(item)
            job = session.scalar(select(Job).where(Job.recording_id == item.id))
            if job is None:
                session.add(Job(recording_id=item.id))
            else:
                job.status, job.token, job.lease_until, job.attempts = "queued", None, None, 0
            item.status, item.error = "queued", None
            return describe(item)

    @app.post("/api/recordings/{recording_id}/claim-extraction", status_code=202)
    def claim_extraction(recording_id: UUID):
        with sessions.begin() as session:
            item = get(session, recording_id, lock=True)
            if item.status in ("queued", "transcribing"):
                raise HTTPException(409, "Espera a que termine la transcripción")
            if not item.segments:
                raise HTTPException(409, "La grabación aún no tiene transcript revisable")
            active = session.scalar(select(AnalysisRun).where(AnalysisRun.recording_id == item.id, AnalysisRun.status.in_(("queued", "running"))))
            if active:
                return describe_run(active)
            run = AnalysisRun(
                recording_id=item.id,
                recording_revision=item.revision,
                kind="claim_extraction",
                provider="openrouter",
                prompt_version="claims-v2-conversation",
                unreviewed_segment_count=sum(not bool(segment.get("reviewed")) for segment in item.segments),
            )
            session.add(run)
            session.flush()
            return describe_run(run)

    @app.get("/api/recordings/{recording_id}/claim-extraction")
    def claim_extraction_status(recording_id: UUID):
        with sessions() as session:
            item = get(session, recording_id)
            run = session.scalar(select(AnalysisRun).where(AnalysisRun.recording_id == item.id).order_by(AnalysisRun.created_at.desc()))
            if not run:
                raise HTTPException(404, "No hay análisis de afirmaciones")
            claims = []
            for claim in session.scalars(select(Claim).where(Claim.analysis_run_id == run.id).order_by(Claim.position)):
                claims.append(describe_claim(session, claim))
            return describe_run(run, claims if run.status in ("completed", "stale") else None)

    @app.post("/api/recordings/{recording_id}/claim-extraction/cancel")
    def cancel_claim_extraction(recording_id: UUID):
        with sessions.begin() as session:
            item = get(session, recording_id, lock=True)
            run = session.scalar(
                select(AnalysisRun)
                .where(AnalysisRun.recording_id == item.id, AnalysisRun.status.in_(("queued", "running")))
                .order_by(AnalysisRun.created_at.desc())
                .with_for_update()
            )
            if run is None:
                raise HTTPException(409, "No hay una extracción activa que cancelar")
            run.status = "cancelled"
            run.completed_at = now()
            run.token = None
            run.lease_until = None
            return describe_run(run)

    @app.get("/api/recordings/{recording_id}/claims")
    def list_claims(recording_id: UUID, run_id: UUID | None = None):
        with sessions() as session:
            item = get(session, recording_id)
            statement = select(AnalysisRun).where(AnalysisRun.recording_id == item.id)
            if run_id is not None:
                statement = statement.where(AnalysisRun.id == str(run_id))
            run = session.scalar(statement.order_by(AnalysisRun.created_at.desc()))
            if run is None:
                raise HTTPException(404, "Ejecución de afirmaciones no encontrada")
            rows = session.scalars(
                select(Claim).where(Claim.analysis_run_id == run.id).order_by(Claim.position, Claim.start_ms)
            )
            return [describe_claim(session, claim) for claim in rows]

    def claim_context(session, claim_id, lock=False):
        claim = session.get(Claim, str(claim_id))
        if claim is None:
            raise HTTPException(404, "Afirmación no encontrada")
        run = session.get(AnalysisRun, claim.analysis_run_id)
        recording = session.scalar(select(Recording).where(Recording.id == run.recording_id).with_for_update())
        if recording is None:
            raise HTTPException(404, "Grabación no encontrada")
        if lock:
            run = session.scalar(select(AnalysisRun).where(AnalysisRun.id == run.id).with_for_update())
            claim = session.scalar(select(Claim).where(Claim.id == claim.id).with_for_update())
            if run is None or claim is None:
                raise HTTPException(404, "Afirmación no encontrada")
        if run.status == "stale" or claim.status == "stale" or recording.revision != run.recording_revision:
            raise HTTPException(409, "La afirmación pertenece a una revisión desactualizada")
        return claim, run, recording

    @app.put("/api/claims/{claim_id}")
    def edit_claim(claim_id: UUID, body: ClaimUpdate):
        with sessions.begin() as session:
            claim, _, recording = claim_context(session, claim_id, lock=True)
            if claim.revision != body.revision:
                raise HTTPException(409, "Hay una versión más reciente de la afirmación")
            by_id = {str(segment.get("id")): segment for segment in recording.segments or []}
            missing = [segment_id for segment_id in body.segment_ids if segment_id not in by_id]
            if missing:
                raise HTTPException(422, f"Segmento desconocido: {missing[0]}")
            linked = [by_id[segment_id] for segment_id in body.segment_ids]
            context_ids = set(session.scalars(select(ClaimSegment.segment_id).where(ClaimSegment.claim_id == claim.id, ClaimSegment.relation == "context")))
            has_remaining_context = bool(context_ids - set(body.segment_ids))
            speaker_names = {str(speaker["id"]): speaker.get("name") or None for speaker in recording.speakers or []}
            changed = session.execute(
                update(Claim)
                .where(Claim.id == claim.id, Claim.revision == body.revision)
                .values(
                    normalized_text=body.normalized_text,
                    standalone_text=body.normalized_text,
                    context_required=claim.context_required and has_remaining_context,
                    category=body.category,
                    start_ms=min(int(segment["start_ms"]) for segment in linked),
                    end_ms=max(int(segment["end_ms"]) for segment in linked),
                    status="edited",
                    revision=body.revision + 1,
                )
            )
            if changed.rowcount != 1:
                raise HTTPException(409, "Hay una versión más reciente de la afirmación")
            session.execute(
                delete(ClaimSegment).where(
                    ClaimSegment.claim_id == claim.id,
                    (ClaimSegment.relation == "source") | ClaimSegment.segment_id.in_(body.segment_ids),
                )
            )
            for position, segment in enumerate(linked):
                speaker_id = segment.get("speaker_id")
                session.add(
                    ClaimSegment(
                        claim_id=claim.id,
                        segment_id=str(segment["id"]),
                        start_ms=int(segment["start_ms"]),
                        end_ms=int(segment["end_ms"]),
                        speaker_id=speaker_id,
                        speaker_name=speaker_names.get(str(speaker_id)) if speaker_id else None,
                        relation="source",
                        position=position,
                    )
                )
            session.refresh(claim)
            session.flush()
            return describe_claim(session, claim)

    def select_claim(claim_id, body, status):
        with sessions.begin() as session:
            claim, _, _ = claim_context(session, claim_id, lock=True)
            if claim.revision != body.revision:
                raise HTTPException(409, "Hay una versión más reciente de la afirmación")
            changed = session.execute(
                update(Claim)
                .where(Claim.id == claim.id, Claim.revision == body.revision)
                .values(status=status, revision=body.revision + 1)
            )
            if changed.rowcount != 1:
                raise HTTPException(409, "Hay una versión más reciente de la afirmación")
            session.refresh(claim)
            return describe_claim(session, claim)

    @app.post("/api/claims/{claim_id}/accept")
    def accept_claim(claim_id: UUID, body: ClaimSelection):
        return select_claim(claim_id, body, "accepted")

    @app.post("/api/claims/{claim_id}/discard")
    def discard_claim(claim_id: UUID, body: ClaimSelection):
        return select_claim(claim_id, body, "discarded")

    @app.post("/api/recordings/{recording_id}/cancel")
    def cancel(recording_id: UUID):
        with sessions.begin() as session:
            item = get(session, recording_id, lock=True)
            job = session.scalar(select(Job).where(Job.recording_id == item.id))
            if job and job.status in ("queued", "running"):
                job.status, job.token = "cancelled", None
                item.status = "cancelled"
            return describe(item)

    return app


app = create_app()
