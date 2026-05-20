from typing import Literal, Optional

from pydantic import BaseModel, Field


SUPPORTED_SCHEMA_VERSIONS = {1}


class GoalIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    entered_at_ms: int


class DisplayIn(BaseModel):
    x: int
    y: int
    width: int
    height: int
    scale_factor: float


class ManifestIn(BaseModel):
    recording_id: str
    schema_version: int
    started_at_ms: int
    ended_at_ms: Optional[int] = None
    display: DisplayIn
    goal: GoalIn
    app_version: str
    aborted: bool


class PointIn(BaseModel):
    x: int
    y: int


class ScrollIn(BaseModel):
    start_frame_id: str
    end_frame_id: str
    dx: int
    dy: int
    duration_ms: int
    direction: str


class KeyIn(BaseModel):
    key_code: int
    characters: Optional[str] = None
    modifiers: list[str] = Field(default_factory=list)


class EventIn(BaseModel):
    id: str
    timestamp_ms: int
    kind: Literal["click", "scroll", "key_down", "flags"]
    cursor: PointIn
    button: Optional[Literal["left", "right", "other"]] = None
    scroll: Optional[ScrollIn] = None
    key: Optional[KeyIn] = None
    frame_id: Optional[str] = None
    target_crop_path: Optional[str] = None
    context_crop_path: Optional[str] = None


class RecordingStatus(BaseModel):
    id: str
    status: Literal["pending", "enriching", "ready", "failed"]
    goal: str
    total: int
    completed: int
    failed: int
    created_at: int
    updated_at: int


class UploadResponse(BaseModel):
    recording_id: str
    status: Literal["pending"]
    total_events: int
