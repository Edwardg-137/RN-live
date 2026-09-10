from datetime import timedelta

from sqlalchemy import func, select

from rn_live.claims_worker import run_claim_once
from rn_live.db import AnalysisRun, Claim, Recording, database, now
from rn_live.openrouter import Completion
from test_recordings import upload


class FakeClient:
    def complete(self, messages, **kwargs):
        return Completion('{"claims":[{"segment_ids":["s1"],"category":"fact","verifiable":true,"normalized_text":"Júpiter es grande.","original_quote":"Júpiter es grande","ambiguity_notes":[],"missing_context":[]}]}', "free-model", {"total_tokens": 20})


def test_claim_worker_persists_temporal_links(client):
    item = upload(client).json()
    base = f"/api/recordings/{item['id']}"
    client.put(base + "/speakers", json={"revision": 0, "speakers": [{"id": "a", "name": "Ana"}]})
    client.put(base + "/segments", json={"revision": 1, "segments": [{"id": "s1", "start_ms": 100, "end_ms": 900, "text": "Júpiter es grande", "speaker_id": "a"}]})
    run = client.post(base + "/claim-extraction").json()
    settings = client.app.state.settings
    assert run_claim_once(settings, FakeClient()) is True
    result = client.get(base + "/claim-extraction").json()
    assert result["status"] == "completed"
    assert result["claims"][0]["segments"][0]["segment_id"] == "s1"
    assert result["claims"][0]["segments"][0]["speaker_name"] == "Ana"
    assert result["claims"][0]["start_ms"] == 100
    engine, sessions = database(settings.database_url)
    try:
        with sessions() as session:
            stored = session.get(AnalysisRun, run["id"])
            assert stored.attempts == 1
            assert stored.token is None
            assert stored.lease_until is None
    finally:
        engine.dispose()


def test_claim_worker_recovers_an_expired_running_lease(client):
    item = upload(client).json()
    base = f"/api/recordings/{item['id']}"
    client.put(base + "/segments", json={"revision": 0, "segments": [{"id": "s1", "start_ms": 100, "end_ms": 900, "text": "Júpiter es grande"}]})
    run_id = client.post(base + "/claim-extraction").json()["id"]
    settings = client.app.state.settings
    engine, sessions = database(settings.database_url)
    try:
        with sessions.begin() as session:
            run = session.get(AnalysisRun, run_id)
            run.status = "running"
            run.token = "worker-caido"
            run.lease_until = now() - timedelta(seconds=1)
            run.attempts = 1
    finally:
        engine.dispose()

    assert run_claim_once(settings, FakeClient()) is True
    result = client.get(base + "/claim-extraction").json()
    assert result["status"] == "completed"
    engine, sessions = database(settings.database_url)
    try:
        with sessions() as session:
            stored = session.get(AnalysisRun, run_id)
            assert stored.attempts == 2
            assert stored.token is None
            assert stored.lease_until is None
    finally:
        engine.dispose()


def test_claim_worker_does_not_publish_after_cancellation(client):
    item = upload(client).json()
    base = f"/api/recordings/{item['id']}"
    client.put(base + "/segments", json={"revision": 0, "segments": [{"id": "s1", "start_ms": 100, "end_ms": 900, "text": "Júpiter es grande"}]})
    run_id = client.post(base + "/claim-extraction").json()["id"]
    settings = client.app.state.settings

    class CancellingClient(FakeClient):
        def complete(self, messages, **kwargs):
            engine, sessions = database(settings.database_url)
            try:
                with sessions.begin() as session:
                    run = session.get(AnalysisRun, run_id)
                    run.status = "cancelled"
                    run.completed_at = now()
            finally:
                engine.dispose()
            return super().complete(messages, **kwargs)

    assert run_claim_once(settings, CancellingClient()) is True
    engine, sessions = database(settings.database_url)
    try:
        with sessions() as session:
            assert session.get(AnalysisRun, run_id).status == "cancelled"
            assert session.scalar(select(func.count()).select_from(Claim)) == 0
    finally:
        engine.dispose()


def test_claim_worker_marks_run_stale_when_recording_revision_changes(client):
    item = upload(client).json()
    base = f"/api/recordings/{item['id']}"
    client.put(base + "/segments", json={"revision": 0, "segments": [{"id": "s1", "start_ms": 100, "end_ms": 900, "text": "Júpiter es grande"}]})
    run_id = client.post(base + "/claim-extraction").json()["id"]
    settings = client.app.state.settings

    class EditingClient(FakeClient):
        def complete(self, messages, **kwargs):
            engine, sessions = database(settings.database_url)
            try:
                with sessions.begin() as session:
                    recording = session.get(Recording, item["id"])
                    recording.revision += 1
            finally:
                engine.dispose()
            return super().complete(messages, **kwargs)

    assert run_claim_once(settings, EditingClient()) is True
    engine, sessions = database(settings.database_url)
    try:
        with sessions() as session:
            assert session.get(AnalysisRun, run_id).status == "stale"
            assert session.scalar(select(func.count()).select_from(Claim)) == 0
    finally:
        engine.dispose()


def test_claim_worker_hides_openrouter_key_and_records_completion_time(client, caplog):
    item = upload(client).json()
    base = f"/api/recordings/{item['id']}"
    client.put(base + "/segments", json={"revision": 0, "segments": [{"id": "s1", "start_ms": 100, "end_ms": 900, "text": "Dato"}]})
    client.post(base + "/claim-extraction")
    settings = client.app.state.settings
    settings.openrouter_api_key = "claim-secret-key"

    class FailingClient:
        def complete(self, *args, **kwargs):
            raise RuntimeError("fallo con claim-secret-key")

    assert run_claim_once(settings, FailingClient()) is True
    result = client.get(base + "/claim-extraction").json()
    assert result["status"] == "failed"
    assert result["completed_at"] is not None
    assert settings.openrouter_api_key not in result["error"]
    assert settings.openrouter_api_key not in caplog.text
