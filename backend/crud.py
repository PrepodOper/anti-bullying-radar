from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from datetime import datetime, timedelta, timezone
from .models import Student, MoodEntry, SosEvent

# Маркеры острого риска (Уровень 2) — простой лексический детектор без диагнозов
RISK_KEYWORDS = [
    "не хочу жить", "хочу умереть", "покончить с собой", "суицид",
    "режу себя", "порезы", "избивают", "бьют каждый день",
    "угрожают убить", "хочу исчезнуть", "никому не нужен",
    "лучше бы меня не было"
]

def detect_risk_markers(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in RISK_KEYWORDS)

async def get_or_create_student(db: AsyncSession, pseudo_id: str, class_group: str) -> Student:
    result = await db.execute(select(Student).where(Student.pseudo_id == pseudo_id))
    student = result.scalar_one_or_none()
    if student:
        return student
    # class_group обязателен при создании; если не передан — используем "не указано"
    cg = class_group or "не указано"
    # Нормализуем: если передан точный класс "8А", для аналитики можно хранить как есть,
    # но в отчёте психолога агрегируем по параллели (первый символ цифры)
    student = Student(pseudo_id=pseudo_id, class_group=cg)
    db.add(student)
    await db.flush()
    return student

async def check_3day_decline(db: AsyncSession, pseudo_id: str) -> bool:
    """
    Триггер «3 дня подряд ухудшение»:
    Берём последние 3 записи (по дате, не более 1 в день — берём последнюю за день).
    Если mood_level строго убывает 3 дня подряд (например 4->3->2) — триггер.
    Гипотеза MVP, порог может пересматриваться.
    """
    result = await db.execute(
        select(MoodEntry).where(MoodEntry.pseudo_id == pseudo_id).order_by(MoodEntry.created_at.desc()).limit(10)
    )
    entries = result.scalars().all()
    if len(entries) < 3:
        return False
    # Группируем по дате (YYYY-MM-DD), берём последнюю запись за день
    by_day = {}
    for e in entries:
        day = e.created_at.date()
        if day not in by_day:
            by_day[day] = e
    sorted_days = sorted(by_day.keys(), reverse=True)
    if len(sorted_days) < 3:
        return False
    # Проверяем что это именно 3 последовательных календарных дня
    # Допуск: если записи были не каждый день, но 3 последние записи идут подряд по дням
    # Для MVP проверяем просто последние 3 дня по календарю с записями
    last3 = [by_day[d].mood_level for d in sorted_days[:3]]
    # last3[0] — сегодня, last3[2] — 2 дня назад. Ухудшение = убывание к сегодня
    # Пример: 2 дня назад 5, вчера 3, сегодня 2 => [2,3,5] -> строго возрастает при чтении от сегодня назад? Нет.
    # Правильно: проверяем что уровни падают: day-2 > day-1 > today
    # last3 = [today, yesterday, before_yesterday] => нужно before_yesterday > yesterday > today
    return last3[2] > last3[1] > last3[0]

async def cleanup_old_records(db: AsyncSession, days: int = 30) -> int:
    """Автоудаление записей без раскрытия личности старше 30 дней (cron)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    # Удаляем mood_entries и sos_events у которых consent_disclosed == False и старше cutoff
    # Находим pseudo_id без согласия
    result = await db.execute(select(Student.pseudo_id).where(Student.consent_disclosed == False))
    pseudo_ids = [r[0] for r in result.all()]
    deleted = 0
    for pid in pseudo_ids:
        # mood
        res = await db.execute(select(MoodEntry).where(and_(MoodEntry.pseudo_id == pid, MoodEntry.created_at < cutoff)))
        for e in res.scalars().all():
            await db.delete(e)
            deleted += 1
        # sos
        res2 = await db.execute(select(SosEvent).where(and_(SosEvent.pseudo_id == pid, SosEvent.created_at < cutoff)))
        for e in res2.scalars().all():
            await db.delete(e)
            deleted += 1
    await db.commit()
    return deleted
