from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from test_recordings import upload

from rn_live.db import AnalysisRun, Claim, ClaimSegment


def reviewed_recording(client):
    item = upload(client).json()
    base = f"/api/recordings/{item['id']}"
    assert client.put(base + "/speakers", json={"revision": 0, "speakers": [{"id": "a", "name": "Ana"}]}).status_code == 200
    result = client.put(base + "/segments", json={"revision": 1, "segments": [{"id": "s1", "start_ms": 0, "end_ms": 1500, "text": "Júpiter es grande", "speaker_id": "a"} ]})
    assert result.status_code == 200
    return item["id"]


def test_claim_extraction_run_is_queued_and_is_revision_bound(client):
    recording_id = reviewed_recording(client)
    response = client.post(f"/api/recordings/{recording_id}/claim-extraction")
    assert response.status_code == 202
    run = response.json()
    assert run["status"] == "queued"
    assert run["recording_revision"] == 2
    assert run["prompt_version"] == "claims-v2-conversation"
    status = client.get(f"/api/recordings/{recording_id}/claim-extraction")
    assert status.status_code == 200
    assert status.json()["id"] == run["id"]
    assert client.post(f"/api/recordings/{recording_id}/claim-extraction").json()["id"] == run["id"]


def test_claim_extraction_requires_transcript(client):
    item = upload(client).json()
    response = client.post(f"/api/recordings/{item['id']}/claim-extraction")
    assert response.status_code == 409


def test_claim_candidates_expose_selection_status_and_revision(client):
    recording_id = reviewed_recording(client)
    with client.app.state.sessions.begin() as session:
        run = AnalysisRun(recording_id=recording_id, recording_revision=2, status="completed")
        session.add(run)
        session.flush()
        session.add(
            Claim(
                analysis_run_id=run.id,
                normalized_text="Júpiter es grande.",
                original_quote="Júpiter es grande",
                category="fact",
                verifiable=True,
                start_ms=0,
                end_ms=1500,
            )
        )

    response = client.get(f"/api/recordings/{recording_id}/claim-extraction")
    assert response.status_code == 200
    claim = response.json()["claims"][0]
    assert claim["status"] == "proposed"
    assert claim["revision"] == 0
    assert claim["conversation_relation"] == "standalone"
    assert claim["standalone_text"] == "Júpiter es grande."
    assert claim["context_segments"] == []


def test_claim_candidates_expose_context_separately_from_source_segments(client):
    recording_id, _, claim_id = claim_fixture(client)
    with client.app.state.sessions.begin() as session:
        claim = session.get(Claim, claim_id)
        claim.conversation_relation = "answer"
        claim.context_required = True
        claim.standalone_text = "Ana afirmó que Júpiter es grande."
        session.add(ClaimSegment(claim_id=claim.id, segment_id="s2", start_ms=800, end_ms=1500, speaker_id="b", speaker_name="Beto", relation="context", position=0))

    claim = client.get(f"/api/recordings/{recording_id}/claims").json()[0]

    assert [link["segment_id"] for link in claim["segments"]] == ["s1"]
    assert [link["segment_id"] for link in claim["context_segments"]] == ["s2"]
    assert (claim["start_ms"], claim["end_ms"]) == (0, 700)

    edited = client.put(
        f"/api/claims/{claim_id}",
        json={"revision": 0, "normalized_text": "Júpiter tiene lunas.", "category": "fact", "segment_ids": ["s2"]},
    ).json()
    assert [link["segment_id"] for link in edited["segments"]] == ["s2"]
    assert edited["context_segments"] == []
    assert edited["context_required"] is False


def test_claim_extraction_can_be_cancelled(client):
    recording_id = reviewed_recording(client)
    base = f"/api/recordings/{recording_id}/claim-extraction"
    run = client.post(base).json()

    response = client.post(base + "/cancel")

    assert response.status_code == 200
    assert response.json()["id"] == run["id"]
    assert response.json()["status"] == "cancelled"
    assert response.json()["completed_at"] is not None


def test_running_claim_extraction_can_be_cancelled(client):
    recording_id = reviewed_recording(client)
    base = f"/api/recordings/{recording_id}/claim-extraction"
    run_id = client.post(base).json()["id"]
    with client.app.state.sessions.begin() as session:
        session.get(AnalysisRun, run_id).status = "running"
    assert client.post(base + "/cancel").json()["status"] == "cancelled"


def test_transcript_change_marks_existing_claim_results_stale(client):
    recording_id = reviewed_recording(client)
    with client.app.state.sessions.begin() as session:
        run = AnalysisRun(recording_id=recording_id, recording_revision=2, status="completed")
        session.add(run)
        session.flush()
        claim = Claim(
            analysis_run_id=run.id,
            normalized_text="Júpiter es grande.",
            original_quote="Júpiter es grande",
            category="fact",
            verifiable=True,
            start_ms=0,
            end_ms=1500,
        )
        session.add(claim)

    response = client.put(
        f"/api/recordings/{recording_id}/segments",
        json={
            "revision": 2,
            "segments": [
                {"id": "s1", "start_ms": 0, "end_ms": 1500, "text": "Júpiter es enorme", "speaker_id": "a"}
            ],
        },
    )
    assert response.status_code == 200
    result = client.get(f"/api/recordings/{recording_id}/claim-extraction").json()
    assert result["status"] == "stale"
    assert result["claims"][0]["status"] == "stale"


def claim_fixture(client):
    item = upload(client).json()
    base = f"/api/recordings/{item['id']}"
    client.put(
        base + "/speakers",
        json={"revision": 0, "speakers": [{"id": "a", "name": "Ana"}, {"id": "b", "name": "Beto"}]},
    )
    client.put(
        base + "/segments",
        json={
            "revision": 1,
            "segments": [
                {"id": "s1", "start_ms": 0, "end_ms": 700, "text": "Júpiter es grande", "speaker_id": "a"},
                {"id": "s2", "start_ms": 800, "end_ms": 1500, "text": "y tiene lunas", "speaker_id": "b"},
            ],
        },
    )
    with client.app.state.sessions.begin() as session:
        run = AnalysisRun(recording_id=item["id"], recording_revision=2, status="completed")
        session.add(run)
        session.flush()
        claim = Claim(
            analysis_run_id=run.id,
            normalized_text="Júpiter es grande.",
            original_quote="Júpiter es grande",
            category="fact",
            verifiable=True,
            start_ms=0,
            end_ms=700,
        )
        session.add(claim)
        session.flush()
        session.add(ClaimSegment(claim_id=claim.id, segment_id="s1", start_ms=0, end_ms=700, speaker_id="a", speaker_name="Ana"))
        return item["id"], run.id, claim.id


def test_claims_can_be_listed_for_a_run_and_not_from_another_recording(client):
    recording_id, run_id, claim_id = claim_fixture(client)
    response = client.get(f"/api/recordings/{recording_id}/claims", params={"run_id": run_id})
    assert response.status_code == 200
    assert [claim["id"] for claim in response.json()] == [claim_id]

    other_id = upload(client).json()["id"]
    assert client.get(f"/api/recordings/{other_id}/claims", params={"run_id": run_id}).status_code == 404


def test_claim_edit_recalculates_links_and_keeps_original_quote_immutable(client):
    recording_id, _, claim_id = claim_fixture(client)
    response = client.put(
        f"/api/claims/{claim_id}",
        json={"revision": 0, "normalized_text": "Júpiter tiene lunas.", "category": "fact", "segment_ids": ["s2"]},
    )
    assert response.status_code == 200, response.text
    claim = response.json()
    assert claim["status"] == "edited"
    assert claim["revision"] == 1
    assert claim["original_quote"] == "Júpiter es grande"
    assert (claim["start_ms"], claim["end_ms"]) == (800, 1500)
    assert claim["segments"][0]["speaker_id"] == "b"
    assert claim["segments"][0]["speaker_name"] == "Beto"

    forbidden = client.put(
        f"/api/claims/{claim_id}",
        json={"revision": 1, "normalized_text": "Cambio", "category": "fact", "segment_ids": ["s2"], "original_quote": "Sobrescrita"},
    )
    assert forbidden.status_code == 422
    stale = client.put(
        f"/api/claims/{claim_id}",
        json={"revision": 0, "normalized_text": "Vieja", "category": "opinion", "segment_ids": ["s1"]},
    )
    assert stale.status_code == 409


def test_claim_edit_rejects_unknown_segments(client):
    _, _, claim_id = claim_fixture(client)
    response = client.put(
        f"/api/claims/{claim_id}",
        json={"revision": 0, "normalized_text": "Júpiter", "category": "fact", "segment_ids": ["missing"]},
    )
    assert response.status_code == 422


def test_claim_accept_and_discard_use_optimistic_revision(client):
    _, _, claim_id = claim_fixture(client)
    accepted = client.post(f"/api/claims/{claim_id}/accept", json={"revision": 0})
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"
    assert accepted.json()["revision"] == 1

    assert client.post(f"/api/claims/{claim_id}/discard", json={"revision": 0}).status_code == 409
    discarded = client.post(f"/api/claims/{claim_id}/discard", json={"revision": 1})
    assert discarded.status_code == 200
    assert discarded.json()["status"] == "discarded"
    assert discarded.json()["revision"] == 2


def test_concurrent_claim_decisions_allow_only_one_revision_winner(client):
    _, _, claim_id = claim_fixture(client)
    barrier = Barrier(2)

    def decide(action):
        barrier.wait()
        return client.post(f"/api/claims/{claim_id}/{action}", json={"revision": 0})

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(decide, ("accept", "discard")))

    assert sorted(response.status_code for response in responses) == [200, 409]
    final = next(response.json() for response in responses if response.status_code == 200)
    assert final["revision"] == 1


def test_stale_claim_cannot_be_changed(client):
    recording_id, _, claim_id = claim_fixture(client)
    client.put(
        f"/api/recordings/{recording_id}/segments",
        json={"revision": 2, "segments": [{"id": "s1", "start_ms": 0, "end_ms": 700, "text": "Cambio", "speaker_id": "a"}]},
    )
    assert client.post(f"/api/claims/{claim_id}/accept", json={"revision": 1}).status_code == 409


def test_speaker_change_stales_claim_but_keeps_historical_speaker_name(client):
    recording_id, run_id, _ = claim_fixture(client)
    response = client.put(
        f"/api/recordings/{recording_id}/speakers",
        json={"revision": 2, "speakers": [{"id": "a", "name": "Alicia"}, {"id": "b", "name": "Beto"}]},
    )
    assert response.status_code == 200
    run = client.get(f"/api/recordings/{recording_id}/claim-extraction").json()
    assert run["id"] == run_id
    assert run["status"] == "stale"
    assert run["claims"][0]["segments"][0]["speaker_name"] == "Ana"

    replacement = client.post(f"/api/recordings/{recording_id}/claim-extraction").json()
    assert replacement["id"] != run_id
    assert replacement["recording_revision"] == 3


def test_run_reports_unreviewed_segments_and_cancelled_history_stays_cancelled(client):
    item = upload(client).json()
    with client.app.state.sessions.begin() as session:
        from rn_live.db import Recording

        recording = session.get(Recording, item["id"])
        recording.segments = [{"id": "raw", "start_ms": 0, "end_ms": 1000, "text": "Dato", "original_text": "Dato", "speaker_id": None, "reviewed": False}]
        recording.revision = 1
        recording.status = "ready_for_review"

    base = f"/api/recordings/{item['id']}/claim-extraction"
    run = client.post(base).json()
    assert run["unreviewed_segment_count"] == 1
    assert client.post(base + "/cancel").json()["status"] == "cancelled"

    client.put(
        f"/api/recordings/{item['id']}/segments",
        json={"revision": 1, "segments": [{"id": "raw", "start_ms": 0, "end_ms": 1000, "text": "Dato revisado"}]},
    )
    assert client.get(base).json()["status"] == "cancelled"
