import io
import wave

import pytest
from fastapi.testclient import TestClient


def wav_bytes(seconds=2):
    target = io.BytesIO()
    with wave.open(target, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b"\0\0" * 16000 * seconds)
    return target.getvalue()


@pytest.fixture
def client(tmp_path):
    from rn_live.app import create_app
    from rn_live.config import Settings

    settings = Settings(database_url=f"sqlite:///{tmp_path}/test.db", storage_dir=tmp_path / "media")
    with TestClient(create_app(settings)) as instance:
        yield instance


def upload(client, **fields):
    return client.post("/api/recordings", data={"title": "Entrevista", "kind": "interview", "speaker_count": "2", **fields}, files={"file": ("clip.wav", wav_bytes(), "audio/wav")})


def test_upload_persists_metadata_and_serves_range(client):
    response = upload(client)
    assert response.status_code == 201, response.text
    recording = response.json()
    assert recording["kind"] == "interview"
    assert recording["duration_ms"] == 2000
    assert recording["speaker_count"] == 2
    assert client.get("/api/recordings").json()[0]["id"] == recording["id"]
    audio = client.get(f'/api/recordings/{recording["id"]}/media', headers={"Range": "bytes=0-3"})
    assert audio.status_code == 206
    assert audio.content == b"RIFF"


def test_invalid_media_leaves_no_recording(client):
    response = client.post("/api/recordings", data={"title": "Mal", "kind": "speech", "speaker_count": 1}, files={"file": ("fake.wav", b"not audio", "audio/wav")})
    assert response.status_code == 422
    assert client.get("/api/recordings").json() == []


def test_delete_removes_file_and_metadata(client):
    recording = upload(client).json()
    assert client.delete(f'/api/recordings/{recording["id"]}').status_code == 204
    assert client.get(f'/api/recordings/{recording["id"]}/media').status_code == 404
    assert list(client.app.state.settings.storage_dir.iterdir()) == []


def test_review_rejects_invalid_times_and_unknown_speaker(client):
    item = upload(client).json()
    url = f'/api/recordings/{item["id"]}/segments'
    for segment in [
        {"start_ms": 1000, "end_ms": 500, "text": "No"},
        {"start_ms": 0, "end_ms": 3000, "text": "No"},
        {"start_ms": 0, "end_ms": 1000, "text": "No", "speaker_id": "unknown"},
    ]:
        assert client.put(url, json={"revision": 0, "segments": [segment]}).status_code == 422


def test_review_persists_and_protects_against_stale_edits(client):
    item = upload(client).json()
    base = f'/api/recordings/{item["id"]}'
    assert client.put(base + "/speakers", json={"revision": 0, "speakers": [{"id": "speaker-1", "name": "Ana", "role": "interviewer"}]}).status_code == 200
    payload = {"revision": 1, "segments": [{"start_ms": 100, "end_ms": 1900, "text": "Una pregunta", "speaker_id": "speaker-1"}]}
    result = client.put(base + "/segments", json=payload)
    assert result.status_code == 200, result.text
    assert result.json()["revision"] == 2
    segments = client.get(base + "/segments").json()
    assert segments["segments"][0]["start_ms"] == 100
    assert segments["segments"][0]["reviewed"] is True
    assert client.put(base + "/segments", json=payload).status_code == 409


def test_single_pending_job_and_cancel(client):
    item = upload(client).json()
    base = f'/api/recordings/{item["id"]}'
    assert client.post(base + "/transcribe").status_code == 202
    assert client.post(base + "/transcribe").status_code == 409
    assert client.put(base + "/segments", json={"revision": 0, "segments": []}).status_code == 409
    assert client.post(base + "/cancel").status_code == 200
    assert client.get(base).json()["status"] == "cancelled"
    assert client.post(base + "/transcribe").status_code == 202


def test_truncated_wav_is_rejected(client):
    response = client.post('/api/recordings', data={'title':'Cortado','kind':'speech'}, files={'file':('clip.wav',wav_bytes()[:-40],'audio/wav')})
    assert response.status_code == 422


def test_speaker_edits_reject_stale_revision(client):
    item = upload(client).json()
    url = f'/api/recordings/{item["id"]}/speakers'
    body = {"revision":0,"speakers":[{"id":"a","name":"Ana"}]}
    assert client.put(url,json=body).status_code == 200
    body['speakers'][0]['name'] = 'Sobrescritura'
    assert client.put(url,json=body).status_code == 409
    assert client.get(f'/api/recordings/{item["id"]}').json()['speakers'][0]['name'] == 'Ana'


def test_detail_is_single_revision_snapshot(client):
    item = upload(client).json()
    detail = client.get(f'/api/recordings/{item["id"]}').json()
    assert detail['segments'] == []
    assert detail['speakers'] == []
    assert detail['revision'] == 0


def test_oversize_body_rejected_before_multipart_processing(client):
    client.app.state.settings.max_upload_bytes = 100
    response = client.post('/api/recordings', content=b'x' * 70000, headers={'Content-Type':'multipart/form-data; boundary=bad'})
    assert response.status_code == 413
