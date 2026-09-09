from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import delete, select, update

from .config import Settings
from .db import Base, Job, Recording, database, uid
from .media import MediaError, probe
from .openrouter import OpenRouterClient
from .schemas import SegmentReview, SpeakerReview
from .limits import BodyLimit


def describe(recording):
    return {name: getattr(recording, name) for name in ("id", "title", "kind", "speaker_count", "content_date", "scope", "filename", "duration_ms", "status", "error", "revision", "speakers", "created_at")}


def create_app(settings=None):
    settings = settings or Settings()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    if settings.database_url.startswith("sqlite:///"):
        Path(settings.database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine, sessions = database(settings.database_url)

    @asynccontextmanager
    async def lifespan(_):
        Base.metadata.create_all(engine)
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
