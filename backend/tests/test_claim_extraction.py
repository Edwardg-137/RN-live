import json

import pytest

from rn_live.claims import ClaimExtractionError, extract_claims, normalize_claims


def segments():
    return [
        {"id":"s1","start_ms":0,"end_ms":4000,"text":"Júpiter es el planeta más grande y tiene la Gran Mancha Roja.","speaker_id":"a"},
        {"id":"s2","start_ms":4000,"end_ms":7000,"text":"Creo que sería imposible enviar personas allí.","speaker_id":"a"},
    ]


def claim_data(**values):
    claim = {
        "context_segment_ids": [],
        "conversation_relation": "standalone",
        "context_required": False,
        "standalone_text": values.get("normalized_text", "Dato"),
    }
    claim.update(values)
    return claim


def test_normalize_claims_keeps_quote_and_rejects_unknown_segment():
    raw = {"claims":[claim_data(segment_ids=["s1"],category="fact",verifiable=True,normalized_text="Júpiter es el planeta más grande.",original_quote="Júpiter es el planeta más grande",ambiguity_notes=[],missing_context=[])]}
    result = normalize_claims(raw, segments())
    assert result[0].normalized_text.startswith("Júpiter")
    assert result[0].segment_ids == ["s1"]
    assert result[0].start_ms == 0 and result[0].end_ms == 4000

    with pytest.raises(ClaimExtractionError, match="segment"):
        normalize_claims({"claims":[{**raw["claims"][0],"segment_ids":["unknown"]}]}, segments())


def test_normalize_claims_deduplicates_by_normalized_text():
    raw = {"claims":[
        claim_data(segment_ids=["s1"],category="fact",verifiable=True,normalized_text="Dato repetido.",original_quote="A",ambiguity_notes=[],missing_context=[]),
        claim_data(segment_ids=["s1"],category="fact",verifiable=True,normalized_text=" dato repetido. ",original_quote="B",ambiguity_notes=[],missing_context=[]),
    ]}
    assert len(normalize_claims(raw, segments())) == 1


def test_extract_claims_parses_fenced_json_and_builds_prompt():
    class FakeClient:
        def complete(self, messages, max_tokens=800, temperature=0.1, **kwargs):
            assert messages[0]["role"] == "system"
            assert "No inventes" in messages[0]["content"]
            assert max_tokens == 4000
            assert kwargs["response_format"]["type"] == "json_schema"
            assert kwargs["response_format"]["json_schema"]["strict"] is True
            assert kwargs["reasoning"] == {"max_tokens": 512, "exclude": True}
            assert "Ana (moderator)" in messages[1]["content"]
            assert "2026-08-20" in messages[1]["content"]
            assert "Audiencia general" in messages[1]["content"]
            from rn_live.openrouter import Completion
            return Completion('```json {"claims": [{"segment_ids":["s1"],"context_segment_ids":[],"conversation_relation":"standalone","context_required":false,"standalone_text":"Júpiter es grande.","category":"fact","verifiable":true,"normalized_text":"Júpiter es grande.","original_quote":"Júpiter es grande","ambiguity_notes":[],"missing_context":[]}]} ```', "free-model", {"total_tokens": 10})
    result = extract_claims(
        FakeClient(), segments(), "debate", 2,
        speakers=[{"id": "a", "name": "Ana", "role": "moderator"}],
        content_date="2026-08-20", scope="Audiencia general",
    )
    assert result.model == "free-model"
    assert result.claims[0].category == "fact"


def test_extract_claims_uses_short_segments_only_as_conversation_context():
    transcript = [
        {"id": "question", "start_ms": 0, "end_ms": 500, "text": "¿Por qué?", "speaker_id": "interviewer"},
        {"id": "answer", "start_ms": 500, "end_ms": 2500, "text": "Porque el presupuesto aumentó este año.", "speaker_id": "guest"},
    ]

    class ConversationClient:
        def complete(self, messages, **kwargs):
            prompt = messages[1]["content"]
            assert "[question] CONTEXT_ONLY" in prompt
            assert "[answer] TARGET" in prompt
            assert "entrevistador" in messages[0]["content"].casefold()
            from rn_live.openrouter import Completion
            return Completion(
                '{"claims":[{"segment_ids":["answer"],"context_segment_ids":["question"],'
                '"conversation_relation":"answer","context_required":true,'
                '"standalone_text":"El invitado afirmó que el presupuesto aumentó este año.",'
                '"category":"fact","verifiable":true,"normalized_text":"El presupuesto aumentó este año.",'
                '"original_quote":"Porque el presupuesto aumentó este año.","ambiguity_notes":[],"missing_context":[]}]}',
                "free-model",
            )

    result = extract_claims(ConversationClient(), transcript, "interview", 2)

    assert result.claims[0].segment_ids == ["answer"]
    assert result.claims[0].context_segment_ids == ["question"]
    assert (result.claims[0].start_ms, result.claims[0].end_ms) == (500, 2500)


def test_extract_claims_skips_transcripts_without_segments_longer_than_three_words():
    class UnexpectedClient:
        def complete(self, *args, **kwargs):
            raise AssertionError("No debe consultar al modelo")

    result = extract_claims(
        UnexpectedClient(),
        [{"id": "short", "start_ms": 0, "end_ms": 500, "text": "De acuerdo.", "speaker_id": "a"}],
        "debate",
        2,
    )

    assert result.claims == []


def test_normalize_claims_rejects_context_used_as_the_only_source():
    raw = {"claims": [{
        "segment_ids": ["s1"], "context_segment_ids": [], "conversation_relation": "standalone",
        "context_required": False, "standalone_text": "Júpiter es grande.", "category": "fact",
        "verifiable": True, "normalized_text": "Júpiter es grande.", "original_quote": "Júpiter",
        "ambiguity_notes": [], "missing_context": [],
    }]}

    with pytest.raises(ClaimExtractionError, match="fuente"):
        normalize_claims(raw, segments(), target_ids={"s2"})


def test_extract_claims_rejects_non_json_response():
    class BadClient:
        def complete(self, *args, **kwargs):
            from rn_live.openrouter import Completion
            return Completion("No puedo", "free-model")
    with pytest.raises(ClaimExtractionError, match="JSON"):
        extract_claims(BadClient(), segments(), "speech", 1)


def test_normalize_claims_rejects_unknown_root_fields_and_too_many_claims():
    base = claim_data(segment_ids=["s1"], category="fact", verifiable=True, normalized_text="Dato", original_quote="Dato", ambiguity_notes=[], missing_context=[])
    with pytest.raises(ClaimExtractionError, match="inválid"):
        normalize_claims({"claims": [base], "verdict": True}, segments())
    with pytest.raises(ClaimExtractionError, match="30"):
        normalize_claims({"claims": [{**base, "normalized_text": f"Dato {index}"} for index in range(31)]}, segments())
    with pytest.raises(ClaimExtractionError, match="inválid"):
        normalize_claims({"claims": [{key: value for key, value in base.items() if key != "conversation_relation"}]}, segments())


def test_normalize_claims_orders_candidates_by_time():
    raw = {"claims": [
        claim_data(segment_ids=["s2"], category="opinion", verifiable=False, normalized_text="Segunda", original_quote="Creo", ambiguity_notes=[], missing_context=[]),
        claim_data(segment_ids=["s1"], category="fact", verifiable=True, normalized_text="Primera", original_quote="Júpiter", ambiguity_notes=[], missing_context=[]),
    ]}
    assert [claim.normalized_text for claim in normalize_claims(raw, segments())] == ["Primera", "Segunda"]


def test_extract_claims_splits_long_transcripts_and_aggregates_usage():
    long_segments = [
        {"id": f"s{index}", "start_ms": index * 1000, "end_ms": index * 1000 + 900, "text": f"Este es el dato {index}", "speaker_id": "a"}
        for index in range(31)
    ]

    class BlockClient:
        def __init__(self):
            self.blocks = []

        def complete(self, messages, **kwargs):
            lines = [line for line in messages[1]["content"].splitlines() if line.startswith("[")]
            assert len(lines) <= 30
            self.blocks.append(lines)
            segment_id = next(line for line in lines if " TARGET " in line).split("]", 1)[0][1:]
            from rn_live.openrouter import Completion
            return Completion(
                json.dumps({"claims": [claim_data(segment_ids=[segment_id], category="fact", verifiable=True, normalized_text=f"Dato {segment_id}", original_quote="Dato", ambiguity_notes=[], missing_context=[])]}),
                "free-model",
                {"prompt_tokens": 4, "completion_tokens": 6, "total_tokens": 10},
            )

    provider = BlockClient()
    result = extract_claims(provider, long_segments, "speech", 1)
    assert len(provider.blocks) == 2
    assert [claim.segment_ids[0] for claim in result.claims] == ["s0", "s28"]
    assert result.usage == {"prompt_tokens": 8, "completion_tokens": 12, "total_tokens": 20}


def test_extract_claims_stops_requesting_blocks_at_candidate_limit():
    long_segments = [
        {"id": f"s{index}", "start_ms": index * 1000, "end_ms": index * 1000 + 900, "text": f"Este es el dato {index}", "speaker_id": "a"}
        for index in range(60)
    ]

    class FullBlockClient:
        def __init__(self):
            self.calls = 0

        def complete(self, messages, **kwargs):
            self.calls += 1
            from rn_live.openrouter import Completion
            target_ids = [
                line.split("]", 1)[0][1:]
                for line in messages[1]["content"].splitlines()
                if line.startswith("[") and " TARGET " in line
            ]
            claims = [
                claim_data(segment_ids=[segment_id], category="fact", verifiable=True, normalized_text=f"Dato {segment_id}", original_quote=f"Dato {segment_id}", ambiguity_notes=[], missing_context=[])
                for segment_id in target_ids
            ]
            return Completion(json.dumps({"claims": claims}), "free-model", {"total_tokens": 100})

    provider = FullBlockClient()
    result = extract_claims(provider, long_segments, "speech", 1)
    assert len(result.claims) == 30
    assert provider.calls == 2
