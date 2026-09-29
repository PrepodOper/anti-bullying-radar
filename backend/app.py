import os
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

# поддерживаем запуск как `uvicorn backend.app:app` и как `uvicorn app:app` из папки backend
try:
    from backend.database import get_db, init_db, engine, AsyncSessionLocal
    from backend.models import Student, MoodEntry, SosEvent
    from backend.schemas import (
        MoodCreate, MoodHistoryOut, MoodEntryOut,
        SosCreate, SosEventOut,
        PsychReportOut, PsychReportRow, ConsentDisclose
    )
    from backend.security import get_pseudo_id
    import backend.crud as crud
    try:
        from backend.ai import ai_dialog
    except ImportError:
        from ai import ai_dialog
except ImportError:
    from database import get_db, init_db, engine, AsyncSessionLocal
    from models import Student, MoodEntry, SosEvent
    from schemas import (
        MoodCreate, MoodHistoryOut, MoodEntryOut,
        SosCreate, SosEventOut,
        PsychReportOut, PsychReportRow, ConsentDisclose
    )
    from security import get_pseudo_id
    import crud
    try:
        from ai import ai_dialog
    except ImportError:
        ai_dialog = None

_db_ready = False

async def ensure_db():
    global _db_ready
    if _db_ready:
        return
    try:
        print("[lifespan] init_db start", flush=True)
        await init_db()
        print("[lifespan] init_db done", flush=True)
    except Exception as e:
        print(f"[lifespan] init_db error: {e}", flush=True)
    # seed если пусто
    try:
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(func.count(Student.pseudo_id)))
            cnt = r.scalar()
            print(f"[lifespan] students cnt={cnt}", flush=True)
            if cnt == 0:
                import hashlib, hmac
                secret = os.getenv("SECRET_KEY", "dev-secret-key-change-me-32-chars")
                def pid(uid): return hmac.new(secret.encode(), uid.encode(), hashlib.sha256).hexdigest()
                students = [
                    Student(pseudo_id=pid("test_user_1"), class_group="8-параллель"),
                    Student(pseudo_id=pid("test_user_2"), class_group="9-параллель"),
                    Student(pseudo_id=pid("test_user_3"), class_group="8-параллель"),
                ]
                db.add_all(students)
                await db.flush()
                now = datetime.now(timezone.utc)
                entries = [
                    MoodEntry(pseudo_id=pid("test_user_1"), mood_level=4, created_at=now - timedelta(days=2)),
                    MoodEntry(pseudo_id=pid("test_user_1"), mood_level=3, created_at=now - timedelta(days=1)),
                    MoodEntry(pseudo_id=pid("test_user_1"), mood_level=2, created_at=now),
                    MoodEntry(pseudo_id=pid("test_user_2"), mood_level=5, created_at=now - timedelta(days=1)),
                    MoodEntry(pseudo_id=pid("test_user_2"), mood_level=5, created_at=now),
                ]
                db.add_all(entries)
                sos = SosEvent(pseudo_id=pid("test_user_1"), trigger_type="3day_decline", risk_level="standard", class_group="8-параллель", created_at=now)
                db.add(sos)
                await db.commit()
                print(f"[seed] Создано {len(students)} тестовых учеников, {len(entries)} записей настроения, 1 SOS", flush=True)
    except Exception as e:
        print(f"[seed] error: {e}", flush=True)
    _db_ready = True

@asynccontextmanager
async def lifespan(app: FastAPI):
    await ensure_db()
    yield
    print("[lifespan] shutdown", flush=True)

app = FastAPI(
    title="Антибуллинг-радар — Бэкенд",
    version="1.0.0-mvp",
    description="Бэкенд для бота MAX: хеширование, дневник настроения, триггеры, SOS, сводка психолога. ФЗ-152, тестовые данные.",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Fallback для старых раннеров без lifespan
@app.on_event("startup")
async def _startup_fallback():
    await ensure_db()

# ===================== MOOD =====================

@app.post("/api/mood", response_model=dict, tags=["mood"])
async def post_mood(body: MoodCreate, db: AsyncSession = Depends(get_db)):
    if body.mood_level not in [1,2,3,4,5]:
        raise HTTPException(400, "mood_level должен быть 1-5")
    pseudo = get_pseudo_id(body.max_user_id)
    student = await crud.get_or_create_student(db, pseudo, body.class_group or "не указано")
    entry = MoodEntry(
        pseudo_id=pseudo,
        mood_level=body.mood_level,
        created_at=body.created_at or datetime.now(timezone.utc)
    )
    db.add(entry)
    await db.flush()

    is_decline = await crud.check_3day_decline(db, pseudo)
    sos_created = None
    if is_decline:
        recent = await db.execute(select(SosEvent).where(
            and_(SosEvent.pseudo_id == pseudo, SosEvent.trigger_type == "3day_decline", SosEvent.created_at > datetime.now(timezone.utc) - timedelta(hours=24))
        ))
        if not recent.scalar_one_or_none():
            sos = SosEvent(pseudo_id=pseudo, trigger_type="3day_decline", risk_level="standard", class_group=student.class_group)
            db.add(sos)
            await db.flush()
            sos_created = sos.id
            print(f"[TRIGGER] 3-day decline for {pseudo[:8]}... class {student.class_group} -> SOS #{sos.id}")

    await db.commit()
    return {
        "ok": True,
        "pseudo_id": pseudo[:12] + "...",
        "mood_id": entry.id,
        "trigger_3day": is_decline,
        "sos_event_id": sos_created,
        "message": "Заметил, что последние три дня тебе непросто… Хочешь поговорить с психологом? [Поговорить с психологом] [Пока не готов]" if is_decline else "Спасибо, запись сохранена. Психолог и одноклассники не узнают, что это ты, пока сам не решишь раскрыться."
    }

@app.get("/api/mood/history", response_model=MoodHistoryOut, tags=["mood"])
async def get_mood_history(max_user_id: str = Query(..., description="MAX user ID"), db: AsyncSession = Depends(get_db)):
    pseudo = get_pseudo_id(max_user_id)
    result = await db.execute(select(Student).where(Student.pseudo_id == pseudo))
    student = result.scalar_one_or_none()
    if not student:
        raise HTTPException(404, "Ученик не найден. Сначала сделайте отметку настроения.")
    result = await db.execute(select(MoodEntry).where(MoodEntry.pseudo_id == pseudo).order_by(MoodEntry.created_at.asc()))
    entries = result.scalars().all()
    is_decline = await crud.check_3day_decline(db, pseudo)
    return MoodHistoryOut(
        pseudo_id=pseudo[:12]+"...",
        class_group=student.class_group,
        entries=[MoodEntryOut.model_validate(e) for e in entries],
        trigger_3day=is_decline,
        trigger_message="Заметил, что последние три дня тебе непросто…" if is_decline else None
    )

# ===================== SOS =====================

@app.post("/api/sos", response_model=dict, tags=["sos"])
async def post_sos(body: SosCreate, db: AsyncSession = Depends(get_db)):
    pseudo = get_pseudo_id(body.max_user_id)
    student = await crud.get_or_create_student(db, pseudo, body.class_group or "не указано")
    cg = student.class_group
    event = SosEvent(pseudo_id=pseudo, trigger_type=body.trigger_type, risk_level=body.risk_level, class_group=cg)
    db.add(event)
    await db.commit()
    await db.refresh(event)
    print(f"[SOS] {body.trigger_type} | risk={body.risk_level} | class={cg} | event #{event.id}")
    return {
        "ok": True,
        "event_id": event.id,
        "message": "Сигнал отправлен. Психолог увидит только класс/параллель и что нужна поддержка. Ты остаёшься анонимным.",
        "risk_level": body.risk_level
    }

@app.post("/api/dialog", response_model=dict, tags=["dialog"])
async def post_dialog(body: dict, db: AsyncSession = Depends(get_db)):
    max_user_id = body.get("max_user_id")
    text = body.get("text", "")
    class_group = body.get("class_group")
    if not max_user_id or not text:
        raise HTTPException(400, "max_user_id и text обязательны")
    pseudo = get_pseudo_id(max_user_id)
    student = await crud.get_or_create_student(db, pseudo, class_group or "не указано")
    # --- GigaChat Lite гибрид ---
    ai_res = None
    if 'ai_dialog' in globals() and ai_dialog is not None:
        try:
            ai_res = await ai_dialog(text)
            is_risk = ai_res.get("risk") == "elevated"
            ai_reply = ai_res.get("reply")
        except Exception as e:
            print(f"[AI fallback] {e}")
            is_risk = crud.detect_risk_markers(text)
            ai_reply = None
    else:
        is_risk = crud.detect_risk_markers(text)
        ai_reply = None
    if is_risk:
        event = SosEvent(pseudo_id=pseudo, trigger_type="risk_marker", risk_level="elevated", class_group=student.class_group)
        db.add(event)
        await db.commit()
        await db.refresh(event)
        print(f"[RISK] marker detected | class={student.class_group} | event #{event.id} | text snippet: {text[:60]}")
        # Если GigaChat вернул кастомный эмпатичный reply — используем его, иначе шаблон
        elevated_reply = ai_reply if ai_reply else "То, что ты написал, звучит серьёзно. Ты не один — давай подумаем, как тебе помочь прямо сейчас."
        return {
            "risk_level": "elevated",
            "reply": elevated_reply,
            "choices": [
                {"id": "hotline", "label": "Дать номер горячей линии", "action": "hotline"},
                {"id": "disclose", "label": "Передать контакт психологу (добровольно)", "action": "disclose"}
            ],
            "hotline": "8-800-2000-122 — Всероссийский детский телефон доверия (круглосуточно, бесплатно, анонимно)",
            "event_id": event.id,
            "notice": "Психолог пока видит только параллель и факт обращения. Раскрытие — только с твоего согласия."
        }
    else:
        # standard — тоже можем обогатить LLM-ответом
        std_reply = ai_reply if ai_reply else "Спасибо, что поделился. Хочешь рассказать подробнее или записать настроение?"
        return {
            "risk_level": "standard",
            "reply": std_reply,
            "choices": []
        }

# ===================== CONSENT =====================

@app.post("/api/consent/disclose", response_model=dict, tags=["consent"])
async def post_consent(body: ConsentDisclose, db: AsyncSession = Depends(get_db)):
    pseudo = get_pseudo_id(body.max_user_id)
    result = await db.execute(select(Student).where(Student.pseudo_id == pseudo))
    student = result.scalar_one_or_none()
    if not student:
        raise HTTPException(404, "Ученик не найден")
    student.consent_disclosed = bool(body.consent)
    await db.commit()
    status = "раскрыт" if body.consent else "отозван"
    print(f"[CONSENT] {pseudo[:8]}... consent {status}")
    return {"ok": True, "consent_disclosed": student.consent_disclosed, "message": f"Согласие {status}. Психолог сможет связаться с тобой через MAX." if body.consent else "Остаёшься анонимным. Можешь обратиться на горячую линию: 8-800-2000-122"}

# ===================== PSYCH =====================

@app.get("/api/psych/report", response_model=PsychReportOut, tags=["psych"])
async def get_psych_report(db: AsyncSession = Depends(get_db)):
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    result = await db.execute(select(SosEvent.class_group, func.count(SosEvent.id), func.max(SosEvent.created_at)).where(SosEvent.created_at >= week_ago).group_by(SosEvent.class_group))
    sos_by_class = {row[0]: (row[1], row[2]) for row in result.all()}

    result2 = await db.execute(select(SosEvent.class_group, func.count(SosEvent.id)).where(and_(SosEvent.created_at >= week_ago, SosEvent.resolved_by_psych == False)).group_by(SosEvent.class_group))
    unresolved_by_class = {row[0]: row[1] for row in result2.all()}

    result3 = await db.execute(
        select(Student.class_group, func.avg(MoodEntry.mood_level))
        .join(MoodEntry, MoodEntry.pseudo_id == Student.pseudo_id)
        .where(MoodEntry.created_at >= week_ago)
        .group_by(Student.class_group)
    )
    avg_by_class = {row[0]: round(float(row[1]), 2) if row[1] else None for row in result3.all()}

    result4 = await db.execute(select(Student.class_group).distinct())
    all_groups = [r[0] for r in result4.all()]
    for g in sos_by_class.keys():
        if g not in all_groups:
            all_groups.append(g)

    rows = []
    total = 0
    for cg in sorted(all_groups):
        cnt, last = sos_by_class.get(cg, (0, None))
        total += cnt
        rows.append(PsychReportRow(
            class_group=cg,
            sos_count_week=cnt,
            avg_mood_trend=avg_by_class.get(cg),
            last_event_at=last,
            unresolved_count=unresolved_by_class.get(cg, 0)
        ))
    return PsychReportOut(generated_at=datetime.now(timezone.utc), rows=rows, total_sos_week=total)

@app.post("/api/psych/resolve/{event_id}", tags=["psych"])
async def psych_resolve(event_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SosEvent).where(SosEvent.id == event_id))
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(404, "Событие не найдено")
    event.resolved_by_psych = True
    await db.commit()
    return {"ok": True, "event_id": event_id, "resolved": True}

@app.get("/api/psych/events", tags=["psych"])
async def psych_events(limit: int = 20, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SosEvent).order_by(SosEvent.created_at.desc()).limit(limit))
    events = result.scalars().all()
    return [
        {
            "id": e.id,
            "class_group": e.class_group,
            "trigger_type": e.trigger_type,
            "risk_level": e.risk_level,
            "created_at": e.created_at.isoformat(),
            "resolved": e.resolved_by_psych
        } for e in events
    ]

# ===================== ADMIN / CRON =====================

@app.post("/api/admin/cleanup", tags=["admin"])
async def admin_cleanup(days: int = 30, db: AsyncSession = Depends(get_db)):
    deleted = await crud.cleanup_old_records(db, days=days)
    return {"ok": True, "deleted": deleted, "days": days}

@app.get("/api/health", tags=["system"])
async def health():
    return {"status": "ok", "service": "anti-bullying-radar", "version": "1.0.0-mvp"}

# Static for mini-app
import pathlib
miniapp_path = pathlib.Path(__file__).parent.parent / "miniapp"
if miniapp_path.exists():
    app.mount("/miniapp", StaticFiles(directory=str(miniapp_path), html=True), name="miniapp")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("BACKEND_PORT", "8000")))
