import json
import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .openrouter import Completion
from .schemas import ClaimCategory


class ClaimExtractionError(ValueError):
    """The model response cannot be converted into valid claims."""


class ClaimDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segment_ids: list[str] = Field(min_length=1, max_length=20)
    category: ClaimCategory
    verifiable: bool
    normalized_text: str = Field(min_length=1, max_length=2000)
    original_quote: str = Field(min_length=1, max_length=4000)
    ambiguity_notes: list[str] = Field(default_factory=list, max_length=10)
    missing_context: list[str] = Field(default_factory=list, max_length=10)


class ClaimPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claims: list[ClaimDraft] = Field(max_length=30)


class ExtractedClaim(ClaimDraft):
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class ExtractionResult:
    claims: list[ExtractedClaim]
    model: str
    usage: dict[str, Any] | None = None


def _parse_payload(text: str) -> dict[str, Any]:
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL)
    candidate = fenced.group(1).strip() if fenced else text.strip()
    if not fenced:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start >= 0 and end > start:
            candidate = candidate[start : end + 1]
    try:
        payload = json.loads(candidate)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ClaimExtractionError("La respuesta del modelo no contiene JSON válido") from exc
    if not isinstance(payload, dict):
        raise ClaimExtractionError("El JSON de afirmaciones debe ser un objeto")
    return payload


def normalize_claims(raw: dict[str, Any], segments: list[dict[str, Any]]) -> list[ExtractedClaim]:
    try:
        payload = ClaimPayload.model_validate(raw)
    except Exception as exc:
        raise ClaimExtractionError(f"JSON de afirmaciones inválido: {exc}") from exc
    by_id = {str(segment.get("id")): segment for segment in segments if segment.get("id") is not None}
    result: list[ExtractedClaim] = []
    seen: set[str] = set()
    for draft in payload.claims:
        ids = list(dict.fromkeys(draft.segment_ids))
        missing = [segment_id for segment_id in ids if segment_id not in by_id]
        if missing:
            raise ClaimExtractionError(f"La afirmación referencia un segment inexistente: {missing[0]}")
        key = " ".join(draft.normalized_text.split()).casefold()
        if key in seen:
            continue
        seen.add(key)
        linked = [by_id[segment_id] for segment_id in ids]
        result.append(
            ExtractedClaim(
                **draft.model_dump(exclude={"segment_ids"}),
                segment_ids=ids,
                start_ms=min(int(segment.get("start_ms", 0)) for segment in linked),
                end_ms=max(int(segment.get("end_ms", 0)) for segment in linked),
            )
        )
    return sorted(result, key=lambda claim: (claim.start_ms, claim.end_ms, claim.normalized_text.casefold()))


def extract_claims(
    client: Any,
    segments: list[dict[str, Any]],
    kind: str,
    speaker_count: int,
    *,
    speakers: list[dict[str, Any]] | None = None,
    content_date: str | None = None,
    scope: str = "",
) -> ExtractionResult:
    system = (
        "Extrae afirmaciones explícitas del transcript. No inventes hechos, citas ni segmentos. "
        "Devuelve únicamente JSON con la forma {claims:[...]}. Clasifica cada afirmación como "
        "fact, opinion, prediction, question_premise o unverifiable; no determines si es verdadera."
    )
    blocks = []
    offset = 0
    while offset < len(segments):
        blocks.append(segments[offset : offset + 30])
        if offset + 30 >= len(segments):
            break
        offset += 28
    results: list[ExtractedClaim] = []
    models: list[str] = []
    usage: dict[str, Any] = {}
    seen: set[str] = set()
    speaker_context = ", ".join(
        f"{speaker.get('name') or speaker.get('id') or 'Sin nombre'} ({speaker.get('role') or 'unspecified'})"
        for speaker in (speakers or [])
    ) or "sin nombres o roles asignados"
    metadata = (
        f"Tipo de pieza: {kind}. Participantes detectados: {speaker_count}. "
        f"Hablantes: {speaker_context}. Fecha del contenido: {content_date or 'no indicada'}. "
        f"Alcance: {scope or 'no indicado'}."
    )
    for block in blocks:
        context = "\n".join(
            f"[{segment.get('id')}] {segment.get('start_ms', 0)}-{segment.get('end_ms', 0)} ms "
            f"(speaker={segment.get('speaker_id') or 'unknown'}): {segment.get('text', '')}"
            for segment in block
        )
        user = (
            f"{metadata} "
            "Cada afirmación debe citar uno o más segment_ids existentes y conservar original_quote.\n"
            f"TRANSCRIPT:\n{context}"
        )
        completion: Completion = client.complete(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=4000,
            temperature=0.1,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "claim_extraction",
                    "strict": True,
                    "schema": ClaimPayload.model_json_schema(),
                },
            },
            reasoning={"max_tokens": 512, "exclude": True},
        )
        if completion.model not in models:
            models.append(completion.model)
        for key, value in (completion.usage or {}).items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                usage[key] = usage.get(key, 0) + value
        for claim in normalize_claims(_parse_payload(completion.text), block):
            key = " ".join(claim.normalized_text.split()).casefold()
            if key not in seen and len(results) < 30:
                seen.add(key)
                results.append(claim)
        if len(results) >= 30:
            break
    results.sort(key=lambda claim: (claim.start_ms, claim.end_ms, claim.normalized_text.casefold()))
    return ExtractionResult(results, ", ".join(models), usage or None)
