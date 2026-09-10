from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ClaimCategory = Literal["fact", "opinion", "prediction", "question_premise", "unverifiable"]


class Speaker(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(default="", max_length=100)
    role: Literal["unspecified", "speaker", "moderator", "interviewer", "guest"] = "unspecified"


class Segment(BaseModel):
    id: str | None = Field(default=None, max_length=80)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=10000)
    speaker_id: str | None = None
    reviewed: bool = False

    @model_validator(mode="after")
    def valid_interval(self):
        if self.end_ms <= self.start_ms or not self.text.strip():
            raise ValueError("Intervalo o texto inválido")
        return self


class SegmentReview(BaseModel):
    revision: int = Field(ge=0)
    segments: list[Segment] = Field(max_length=10000)


class SpeakerReview(BaseModel):
    revision: int = Field(ge=0)
    speakers: list[Speaker] = Field(max_length=4)


class ClaimUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    revision: int = Field(ge=0)
    normalized_text: str = Field(min_length=1, max_length=2000)
    category: ClaimCategory
    segment_ids: list[str] = Field(min_length=1, max_length=20)

    @field_validator("segment_ids")
    @classmethod
    def unique_segment_ids(cls, values):
        if any(not value.strip() for value in values) or len(set(values)) != len(values):
            raise ValueError("Los segmentos deben ser únicos y no vacíos")
        return values


class ClaimSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
