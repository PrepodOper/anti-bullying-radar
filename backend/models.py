from sqlalchemy import String, Integer, DateTime, Boolean, ForeignKey, func, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime, timezone
from .database import Base

def utcnow():
    return datetime.now(timezone.utc)

class Student(Base):
    __tablename__ = "students"
    pseudo_id: Mapped[str] = mapped_column(String(64), primary_key=True)  # HMAC hex
    class_group: Mapped[str] = mapped_column(String(20), nullable=False)  # например "8А" или "8-параллель"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    consent_disclosed: Mapped[bool] = mapped_column(Boolean, default=False)  # Уровень 2: согласие раскрыть контакт

    mood_entries = relationship("MoodEntry", back_populates="student", cascade="all, delete-orphan")
    sos_events = relationship("SosEvent", back_populates="student", cascade="all, delete-orphan")

class MoodEntry(Base):
    __tablename__ = "mood_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pseudo_id: Mapped[str] = mapped_column(String(64), ForeignKey("students.pseudo_id", ondelete="CASCADE"), nullable=False, index=True)
    mood_level: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-5
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    student = relationship("Student", back_populates="mood_entries")

    __table_args__ = (
        Index("ix_mood_pseudo_created", "pseudo_id", "created_at"),
    )

class SosEvent(Base):
    __tablename__ = "sos_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pseudo_id: Mapped[str] = mapped_column(String(64), ForeignKey("students.pseudo_id", ondelete="CASCADE"), nullable=False, index=True)
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False)  # manual_sos / 3day_decline / risk_marker
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False, default="standard")  # standard / elevated
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    resolved_by_psych: Mapped[bool] = mapped_column(Boolean, default=False)
    # Для аналитики психолога храним class_group денормализованно (не требует join и не раскрывает pseudo_id)
    class_group: Mapped[str] = mapped_column(String(20), nullable=False)

    student = relationship("Student", back_populates="sos_events")
