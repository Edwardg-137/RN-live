from datetime import timedelta

from test_recordings import client, upload


def test_worker_publishes_segments_and_preserves_original_times(client):
    from rn_live.worker import run_once

    item = upload(client).json()
    client.post(f'/api/recordings/{item["id"]}/transcribe')

    def processor(path, count, settings):
        assert path.is_file()
        assert count == 2
        return [{"id": "s1", "name": "", "role": "unspecified"}], [{"start_ms": 250, "end_ms": 1750, "text": "Texto", "speaker_id": "s1"}]

    assert run_once(client.app.state.settings, processor=processor)
    base = f'/api/recordings/{item["id"]}'
    assert client.get(base).json()["status"] == "ready_for_review"
    output = client.get(base + "/segments").json()
    assert output["segments"][0]["start_ms"] == 250
    assert output["segments"][0]["original_text"] == "Texto"
    assert output["segments"][0]["reviewed"] is False


def test_worker_failure_is_visible_and_retryable(client):
    from rn_live.worker import run_once

    item = upload(client).json()
    base = f'/api/recordings/{item["id"]}'
    client.post(base + "/transcribe")

    def fail(*args):
        raise RuntimeError("Modelo no configurado")

    run_once(client.app.state.settings, processor=fail)
    result = client.get(base).json()
    assert result["status"] == "failed"
    assert result["error"] == "Modelo no configurado"
    assert client.post(base + "/transcribe").status_code == 202


def test_cancelled_worker_cannot_publish_late_results(client):
    from rn_live.worker import run_once

    item = upload(client).json()
    base = f'/api/recordings/{item["id"]}'
    client.post(base + "/transcribe")

    def cancelled(*args):
        client.post(base + "/cancel")
        return [], [{"start_ms": 0, "end_ms": 1000, "text": "Obsoleto", "speaker_id": None}]

    run_once(client.app.state.settings, processor=cancelled)
    assert client.get(base).json()["status"] == "cancelled"
    assert client.get(base + "/segments").json()["segments"] == []


def test_expired_job_can_be_recovered(client):
    from rn_live.db import Job, now
    from rn_live.worker import claim, run_once

    item = upload(client).json()
    client.post(f'/api/recordings/{item["id"]}/transcribe')
    first = claim(client.app.state.sessions, client.app.state.settings)
    assert first is not None
    with client.app.state.sessions.begin() as session:
        job = session.get(Job, first[0])
        job.lease_until = now() - timedelta(seconds=1)
    assert run_once(client.app.state.settings, processor=lambda *args: ([], []))
    assert client.get(f'/api/recordings/{item["id"]}').json()["status"] == "ready_for_review"


def test_token_is_not_written_to_error_or_logs(client, caplog):
    from rn_live.worker import run_once

    settings = client.app.state.settings
    settings.hf_token = 'test-secret-token'
    item = upload(client).json()
    base = f'/api/recordings/{item["id"]}'
    client.post(base + '/transcribe')

    def failure(*args):
        raise RuntimeError('fallo con test-secret-token')

    run_once(settings, processor=failure)
    assert settings.hf_token not in caplog.text
    assert settings.hf_token not in client.get(base).json()['error']


def test_new_transcription_marks_completed_claims_stale(client):
    from rn_live.db import AnalysisRun, Claim
    from rn_live.worker import run_once

    item = upload(client).json()
    base = f'/api/recordings/{item["id"]}'
    client.put(base + "/segments", json={"revision": 0, "segments": [{"id": "old", "start_ms": 0, "end_ms": 1000, "text": "Texto anterior"}]})
    with client.app.state.sessions.begin() as session:
        run = AnalysisRun(recording_id=item["id"], recording_revision=1, status="completed")
        session.add(run)
        session.flush()
        session.add(Claim(analysis_run_id=run.id, normalized_text="Texto anterior", original_quote="Texto anterior", category="fact", verifiable=True, start_ms=0, end_ms=1000))

    assert client.post(base + "/transcribe").status_code == 202
    assert run_once(
        client.app.state.settings,
        processor=lambda *args: ([], [{"start_ms": 100, "end_ms": 900, "text": "Texto nuevo", "speaker_id": None}]),
    )
    result = client.get(base + "/claim-extraction").json()
    assert result["status"] == "stale"
    assert result["claims"][0]["status"] == "stale"
