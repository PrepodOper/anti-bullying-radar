from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List

# --- Mood ---
class MoodCreate(BaseModel):
    max_user_id: str = Field(..., description="MAX user ID — не сохраняется, только хешируется")
    mood_level: int = Field(..., ge=1, le=5)
    class_group: Optional[str] = Field(None, description="Параллель/класс, например '8А' или '8-параллель'. Если ученик уже есть — игнорируется")
    # created_at опционально для тестов
    created_at: Optional[datetime] = None

class MoodEntryOut(BaseModel):
    id: int
    mood_level: int
    created_at: datetime
    class Config:
        from_attributes = True

class MoodHistoryOut(BaseModel):
    pseudo_id: str
    class_group: str
    entries: List[MoodEntryOut]
    trigger_3day: bool = False
    trigger_message: Optional[str] = None

# --- SOS ---
class SosCreate(BaseModel):
    max_user_id: str
    trigger_type: str = Field(..., pattern="^(manual_sos|3day_decline|risk_marker)$")
    risk_level: str = Field("standard", pattern="^(standard|elevated)$")
    class_group: Optional[str] = None

class SosEventOut(BaseModel):
    id: int
    trigger_type: str
    risk_level: str
    class_group: str
    created_at: datetime
    resolved_by_psych: bool
    class Config:
        from_attributes = True

# --- Psych ---
class PsychReportRow(BaseModel):
    class_group: str
    sos_count_week: int
    avg_mood_trend: Optional[float]  # средний уровень за неделю
    last_event_at: Optional[datetime]
    unresolved_count: int

class PsychReportOut(BaseModel):
    generated_at: datetime
    rows: List[PsychReportRow]
    total_sos_week: int

class ConsentDisclose(BaseModel):
    max_user_id: str
    consent: bool = True
