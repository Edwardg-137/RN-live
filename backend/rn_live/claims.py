import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .openrouter import Completion
from .schemas import ClaimCategory


class ClaimExtractionError(ValueError):
    """The model response cannot be converted into valid claims."""


class ClaimDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segment_ids: list[str] = Field(min_length=1, max_length=20)
    context_segment_ids: list[str] = Field(max_length=20)
    conversation_relation: Literal["standalone", "answer", "reply", "rebuttal", "reported_speech"]
    context_required: bool
    standalone_text: str = Field(min_length=1, max_length=2000)
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


def normalize_claims(
    raw: dict[str, Any],
    segments: list[dict[str, Any]],
    target_ids: set[str] | None = None,
) -> list[ExtractedClaim]:
    try:
        payload = ClaimPayload.model_validate(raw)
    except Exception as exc:
        raise ClaimExtractionError(f"JSON de afirmaciones inválido: {exc}") from exc
    by_id = {str(segment.get("id")): segment for segment in segments if segment.get("id") is not None}
    result: list[ExtractedClaim] = []
    seen: set[str] = set()
    for draft in payload.claims:
        ids = list(dict.fromkeys(draft.segment_ids))
        context_ids = list(dict.fromkeys(draft.context_segment_ids))
        missing = [segment_id for segment_id in ids + context_ids if segment_id not in by_id]
        if missing:
            raise ClaimExtractionError(f"La afirmación referencia un segment inexistente: {missing[0]}")
        if target_ids is not None and any(segment_id not in target_ids for segment_id in ids):
            raise ClaimExtractionError("La afirmación usa un segmento de contexto como fuente")
        if set(ids) & set(context_ids):
            raise ClaimExtractionError("Un segmento no puede ser fuente y contexto a la vez")
        if draft.context_required and not context_ids:
            raise ClaimExtractionError("Una afirmación que requiere contexto debe referenciarlo")
        key = " ".join(draft.normalized_text.split()).casefold()
        if key in seen:
            continue
        seen.add(key)
        linked = [by_id[segment_id] for segment_id in ids]
        result.append(
            ExtractedClaim(
                **draft.model_dump(exclude={"segment_ids", "context_segment_ids", "standalone_text"}),
                segment_ids=ids,
                context_segment_ids=context_ids,
                standalone_text=draft.standalone_text,
                start_ms=min(int(segment.get("start_ms", 0)) for segment in linked),
                end_ms=max(int(segment.get("end_ms", 0)) for segment in linked),
            )
        )
    return sorted(result, key=lambda claim: (claim.start_ms, claim.end_ms, claim.normalized_text.casefold()))


def _word_count(text: str) -> int:
    return len(re.findall(r"\w+", text, flags=re.UNICODE))


def _conversation_blocks(segments: list[dict[str, Any]]) -> list[tuple[list[dict[str, Any]], set[str]]]:
    targets = [
        index
        for index, segment in enumerate(segments)
        if segment.get("id") is not None and _word_count(str(segment.get("text", ""))) > 3
    ]
    blocks: list[tuple[list[dict[str, Any]], set[str]]] = []
    cursor = 0
    while cursor < len(targets):
        first = targets[cursor]
        start = max(0, first - 6)
        first_start = int(segments[first].get("start_ms", 0))
        while start < first and first_start - int(segments[start].get("end_ms", 0)) > 60_000:
            start += 1
        last_cursor = cursor
        while last_cursor + 1 < len(targets):
            candidate = targets[last_cursor + 1]
            if min(len(segments), candidate + 3) - start > 30:
                break
            last_cursor += 1
        last = targets[last_cursor]
        end = min(len(segments), last + 3)
        block = segments[start:end]
        target_ids = {str(segments[index]["id"]) for index in targets[cursor : last_cursor + 1]}
        blocks.append((block, target_ids))
        cursor = last_cursor + 1
    return blocks


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
    instructions = {
        "interview": (
            "En entrevistas distingue la pregunta de la respuesta: no atribuyas al invitado la premisa "
            "del entrevistador; usa question_premise para esa premisa y resuelve pronombres solo con contexto declarado."
        ),
        "debate": (
            "En debates distingue la posición propia de citas al oponente, negaciones, refutaciones y modalidad; "
            "separa proposiciones diferentes y no conviertas retórica u opinión en hechos."
        ),
    }
    system = (
        "Extrae afirmaciones explícitas del transcript. No inventes hechos, citas, hablantes ni segmentos. "
        "Solo los segmentos TARGET pueden ser segment_ids; CONTEXT_ONLY puede usarse únicamente en "
        "context_segment_ids. standalone_text debe ser comprensible fuera del diálogo sin añadir información. "
        "Indica conversation_relation y si el contexto es imprescindible. "
        "Devuelve únicamente JSON con la forma {claims:[...]}. Clasifica cada afirmación como fact, opinion, "
        "prediction, question_premise o unverifiable; no determines si es verdadera. "
        + instructions.get(kind, "Conserva literalmente la atribución y el grado de certeza de quien habla.")
    )
    blocks = _conversation_blocks(segments)
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
    speaker_by_id = {str(speaker.get("id")): speaker for speaker in (speakers or [])}
    for block, target_ids in blocks:
        turns: list[int] = []
        turn = 0
        previous_speaker = object()
        for segment in block:
            speaker_id = segment.get("speaker_id")
            if speaker_id != previous_speaker:
                turn += 1
                previous_speaker = speaker_id
            turns.append(turn)
        lines = []
        for segment, turn_number in zip(block, turns):
            segment_id = str(segment.get("id"))
            speaker = speaker_by_id.get(str(segment.get("speaker_id")), {})
            lines.append(
                f"[{segment_id}] {'TARGET' if segment_id in target_ids else 'CONTEXT_ONLY'} "
                f"turn={turn_number} {segment.get('start_ms', 0)}-{segment.get('end_ms', 0)} ms "
                f"(speaker={segment.get('speaker_id') or 'unknown'}, name={speaker.get('name') or 'unknown'}, "
                f"role={speaker.get('role') or 'unspecified'}): {segment.get('text', '')}"
            )
        context = "\n".join(lines)
        user = (
            f"{metadata} "
            "Cada afirmación debe citar uno o más segment_ids TARGET existentes y conservar original_quote. "
            "Los segmentos de tres palabras o menos nunca son fuente por sí solos.\n"
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
        for claim in normalize_claims(_parse_payload(completion.text), block, target_ids):
            key = " ".join(claim.normalized_text.split()).casefold()
            if key not in seen and len(results) < 30:
                seen.add(key)
                results.append(claim)
        if len(results) >= 30:
            break
    results.sort(key=lambda claim: (claim.start_ms, claim.end_ms, claim.normalized_text.casefold()))
    return ExtractionResult(results, ", ".join(models), usage or None)
