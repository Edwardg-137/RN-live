import pytest

from rn_live.claims import ClaimExtractionError, extract_claims, normalize_claims


def segments():
    return [
        {"id":"s1","start_ms":0,"end_ms":4000,"text":"Júpiter es el planeta más grande y tiene la Gran Mancha Roja.","speaker_id":"a"},
        {"id":"s2","start_ms":4000,"end_ms":7000,"text":"Creo que sería imposible enviar personas allí.","speaker_id":"a"},
    ]


def test_normalize_claims_keeps_quote_and_rejects_unknown_segment():
    raw = {"claims":[{"segment_ids":["s1"],"category":"fact","verifiable":True,"normalized_text":"Júpiter es el planeta más grande.","original_quote":"Júpiter es el planeta más grande","ambiguity_notes":[],"missing_context":[]}]}
    result = normalize_claims(raw, segments())
    assert result[0].normalized_text.startswith("Júpiter")
    assert result[0].segment_ids == ["s1"]
    assert result[0].start_ms == 0 and result[0].end_ms == 4000

    with pytest.raises(ClaimExtractionError, match="segment"):
        normalize_claims({"claims":[{**raw["claims"][0],"segment_ids":["unknown"]}]}, segments())


def test_normalize_claims_deduplicates_by_normalized_text():
    raw = {"claims":[
        {"segment_ids":["s1"],"category":"fact","verifiable":True,"normalized_text":"Dato repetido.","original_quote":"A","ambiguity_notes":[],"missing_context":[]},
        {"segment_ids":["s1"],"category":"fact","verifiable":True,"normalized_text":" dato repetido. ","original_quote":"B","ambiguity_notes":[],"missing_context":[]},
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
            return Completion('```json {"claims": [{"segment_ids":["s1"],"category":"fact","verifiable":true,"normalized_text":"Júpiter es grande.","original_quote":"Júpiter es grande","ambiguity_notes":[],"missing_context":[]}]} ```', "free-model", {"total_tokens": 10})
    result = extract_claims(
        FakeClient(), segments(), "debate", 2,
        speakers=[{"id": "a", "name": "Ana", "role": "moderator"}],
        content_date="2026-08-20", scope="Audiencia general",
    )
    assert result.model == "free-model"
    assert result.claims[0].category == "fact"


def test_extract_claims_rejects_non_json_response():
    class BadClient:
        def complete(self, *args, **kwargs):
            from rn_live.openrouter import Completion
            return Completion("No puedo", "free-model")
    with pytest.raises(ClaimExtractionError, match="JSON"):
        extract_claims(BadClient(), segments(), "speech", 1)


def test_normalize_claims_rejects_unknown_root_fields_and_too_many_claims():
    base = {"segment_ids": ["s1"], "category": "fact", "verifiable": True, "normalized_text": "Dato", "original_quote": "Dato", "ambiguity_notes": [], "missing_context": []}
    with pytest.raises(ClaimExtractionError, match="inválid"):
        normalize_claims({"claims": [base], "verdict": True}, segments())
    with pytest.raises(ClaimExtractionError, match="30"):
        normalize_claims({"claims": [{**base, "normalized_text": f"Dato {index}"} for index in range(31)]}, segments())


def test_normalize_claims_orders_candidates_by_time():
    raw = {"claims": [
        {"segment_ids": ["s2"], "category": "opinion", "verifiable": False, "normalized_text": "Segunda", "original_quote": "Creo", "ambiguity_notes": [], "missing_context": []},
        {"segment_ids": ["s1"], "category": "fact", "verifiable": True, "normalized_text": "Primera", "original_quote": "Júpiter", "ambiguity_notes": [], "missing_context": []},
    ]}
    assert [claim.normalized_text for claim in normalize_claims(raw, segments())] == ["Primera", "Segunda"]


def test_extract_claims_splits_long_transcripts_and_aggregates_usage():
    long_segments = [
        {"id": f"s{index}", "start_ms": index * 1000, "end_ms": index * 1000 + 900, "text": f"Dato {index}", "speaker_id": "a"}
        for index in range(31)
    ]

    class BlockClient:
        def __init__(self):
            self.blocks = []

        def complete(self, messages, **kwargs):
            lines = [line for line in messages[1]["content"].splitlines() if line.startswith("[")]
            assert len(lines) <= 30
            self.blocks.append(lines)
            segment_id = lines[0].split("]", 1)[0][1:]
            from rn_live.openrouter import Completion
            return Completion(
                '{"claims":[{"segment_ids":["%s"],"category":"fact","verifiable":true,"normalized_text":"Dato %s","original_quote":"Dato","ambiguity_notes":[],"missing_context":[]}]}' % (segment_id, segment_id),
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
        {"id": f"s{index}", "start_ms": index * 1000, "end_ms": index * 1000 + 900, "text": f"Dato {index}", "speaker_id": "a"}
        for index in range(60)
    ]

    class FullBlockClient:
        def __init__(self):
            self.calls = 0

        def complete(self, messages, **kwargs):
            self.calls += 1
            from rn_live.openrouter import Completion
            claims = [
                {"segment_ids": [f"s{index}"], "category": "fact", "verifiable": True, "normalized_text": f"Dato {index}", "original_quote": f"Dato {index}", "ambiguity_notes": [], "missing_context": []}
                for index in range(30)
            ]
            import json
            return Completion(json.dumps({"claims": claims}), "free-model", {"total_tokens": 100})

    provider = FullBlockClient()
    result = extract_claims(provider, long_segments, "speech", 1)
    assert len(result.claims) == 30
    assert provider.calls == 1
