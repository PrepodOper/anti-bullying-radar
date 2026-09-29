# Антибуллинг-радар — MVP для MAX (конкурсная версия)

> **Назначение:** раннее выявление буллинга и ухудшения эмоционального состояния школьников через анонимный дневник настроения, триггеры и кнопку SOS с GigaChat Lite. Бот не ставит диагнозы и не заменяет специалиста.

**Ссылка на работающее решение в MAX:** `https://botv2-operprepod.amvera.io/` — эмулятор чата MAX (для проверки без токена MAX). В продакшене — webhook `https://botv2-operprepod.amvera.io/webhook` с подпиской `platform-api.max.ru`. Мини-приложения: `/miniapp/student.html?uid=test_user_1`, `/miniapp/psych.html`. API docs: `/docs`.

---

## 1. Основной пользовательский сценарий (человеческими словами, без слэшей)

```
Эл. дневник → ссылка / QR → вход в бота
  ↓
/start или "привет" / "начать" → выбор параллели 8-11
  ↓
"дневник" → отметить 1-5 → запись HMAC(pseudo_id)
  ↓
Триггер 3 дня подряд (5→3→2) → "Заметил, что последние три дня тебе непросто…"
  [Поговорить с психологом] / [Пока не готов]
  ↓
Свободный диалог: "меня булят", "мне плохо" → GigaChat Lite анализ
  elevated: "хочу исчезнуть" → горячая линия 8-800-2000-122 + кнопки
  [Дать номер горячей линии] / [Передать контакт психологу]
  ↓
"сос" / "SOS" → подтверждение → SOS_SENT (только параллель)
  ↓
"история" / "ИСТОРИЯ" / "История" (регистронезависимо, без /) → ссылка на график
"помощь", "конфиденциальность" → справка
```

Все команды работают без `/` и в любом регистре — исправлено для конкурса.

---

## 2. Состав и архитектура

```
MAX Bot (bot/bot_max.py)  ──webhook──►  Backend FastAPI (backend/app.py + ai.py)
      │                                  │ HMAC-SHA256, 3-day decline, risk_marker
      │                                  │ GigaChat Lite гибрид (keyword мгновенно + LLM)
      │                                  ├──► SQLite / Postgres (students, mood_entries, sos_events)
      │                                  └──► MAX API уведомление психолога
      │
      └──► MiniApp (miniapp/student.html, psych.html) через /miniapp (StaticFiles)
```

| Компонент | Путь | Порт | Описание |
|---|---|---|---|
| Backend + Bot (Amvera) | `main.py` | 8000 | Объединённый FastAPI, один порт для Amvera |
| Backend (локально) | `backend/` | 8000 | FastAPI, SQLAlchemy, GigaChat |
| Bot (локально) | `bot/` | 8001 | webhook /webhook, эмулятор / |
| MiniApp | `miniapp/` | через backend | student, psych |
| DB | `radar.db` | — | SQLite для MVP, Postgres опционально |

Поток: ученик → MAX → webhook → backend (pseudo_id) → проверка триггеров → уведомление психолога (только class_group + факт).

---

## 3. Одна команда для запуска всех локальных компонентов через Docker

```bash
cp .env.example .env
# в .env укажи SECRET_KEY (32+ символов) и GIGACHAT ключи (опционально)
docker compose up --build
```

Открой:
- http://localhost:8000/docs — API
- http://localhost:8000/miniapp/student.html?uid=test_user_1
- http://localhost:8000/miniapp/psych.html
- http://localhost:8001/ — эмулятор MAX

Сборка < 2 мин (python:3.11-slim, только необходимые зависимости).

**Остановка / повторный запуск:**
```bash
docker compose down
docker compose down -v  # удалить БД
docker compose restart backend
docker compose logs -f backend
```

---

## 4. Необходимые параметры окружения (.env.example без токенов)

```
SECRET_KEY=change-me-32-chars
MAX_BOT_TOKEN=your_max_bot_token
MAX_API_BASE=https://platform-api.max.ru
BACKEND_URL=https://botv2-operprepod.amvera.io  # для ссылок в боте, без localhost
DATABASE_URL=sqlite+aiosqlite:///./radar.db
GIGACHAT_CLIENT_ID=  # из developers.sber.ru/studio/
GIGACHAT_CLIENT_SECRET=
GIGACHAT_SCOPE=GIGACHAT_API_PERS
GIGACHAT_MODEL=GigaChat
```

Без GIGACHAT ключей бот работает на ключевых словах (fallback). С ключами — гибрид.

---

## 5. Используемые порты

- 8000 — backend + combined main (Amvera, miniapp, /docs, /health)
- 8001 — bot эмулятор (локально docker-compose)

---

## 6. Зависимости

`requirements.txt`: fastapi==0.110.2, uvicorn[standard]==0.29.0, sqlalchemy==2.0.30, greenlet==3.0.3, pydantic==2.11.7, python-dotenv==1.0.1, httpx==0.27.0, aiosqlite==0.20.0. Установка `pip install -r requirements.txt`.

---

## 7. Внешние сервисы и интеграции

- **MAX Bot API**: `POST https://platform-api.max.ru/messages?chat_id=...` с `Authorization: Bearer TOKEN`, attachments inline_keyboard. Webhook `POST /webhook`. Если токена нет — mock режим (логи).
- **GigaChat API**: `https://ngw.devices.sberbank.ru:9443/api/v2/oauth` (Basic base64 id:secret, RqUID, scope PERS) → access_token → `https://gigachat.devices.sberbank.ru/api/v1/chat/completions` model GigaChat, temperature 0.2, max_tokens 300, SYSTEM_PROMPT без диагнозов, JSON {risk, reply}. Токен кэшируется, verify=False (самоподписанный сертификат Сбера). Freemium 1M токенов/12 мес, 1 поток.
- **Amvera**: хостинг Docker, persistenceMount /app, домен botv2-operprepod.amvera.io, HTTPS.

---

## 8. Описание работы с данными

- Не собираем: ФИО, телефон, точный класс, гео.
- Собираем: HMAC-SHA256(max_user_id) → pseudo_id, class_group (параллель вручную), mood_entries, sos_events.
- Агрегаты психологу: без pseudo_id, только class_group, sos_count_week, avg_mood_trend, last_event_at.
- Автоудаление: `POST /api/admin/cleanup` удаляет записи старше 30 дней без consent_disclosed.
- ФЗ-152: на MVP только синтетические данные, тестовые аккаунты.

---

## 9. Порядок работы с тестовыми данными

При старте `lifespan` в `backend/app.py` создаёт:
- 3 ученика test_user_1..3 с историей 5,4,3,2 и одним SOS
- Параллели 8,9,10

Ручное создание:
```bash
curl -X POST http://localhost:8000/api/mood -H "Content-Type: application/json" -d '{"max_user_id":"demo_8A_01","mood_level":2,"class_group":"8-параллель"}'
```

---

## 10. Пошаговый сценарий проверки (включая психолога)

1. Открой https://botv2-operprepod.amvera.io/ → введи "привет" → выбери 9-параллель
2. Напиши "дневник" → отметь 5, потом 3, потом 2 → должен сработать триггер 3 дня
3. Напиши "история" (маленькими, без слэша) → должна прийти ссылка, открой /miniapp/student.html?uid=test_final — график
4. Напиши "сос" → "Отправить SOS" → "Сигнал отправлен"
5. Напиши "не хочу жить" или "хочу исчезнуть" (GigaChat ловит скрытые) → Уровень2: горячая линия + 2 кнопки
6. Напиши "передать контакт психологу" → consent_disclosed
7. Открой /miniapp/psych.html → сводка только по параллелям, без имён
8. /docs — проверить все эндпоинты
9. Проверить без слэшей: "ИСТОРИЯ", "ДНЕВНИК", "ПОМОЩЬ", "КОНФИДЕНЦИАЛЬНОСТЬ" — всё работает

---

## 11. Примеры ожидаемого поведения

- `история` → `Твоя история настроения — в мини-приложении: https://.../miniapp/student.html?uid=...` (без комментария про MVP)
- `не хочу жить` → risk elevated, reply эмпатичный от GigaChat, choices hotline/disclose, hotline 8-800-2000-122, event_id, notice про конфиденциальность
- `мне так одиноко` → standard + поддержка, choices []
- `дневник` → клавиатура 1-5 + SOS
- `сос` → SOS_CONFIRM

---

## 12. Известные ограничения

- Бот не ставит диагнозов, не заменяет специалиста
- На MVP эмулятор чата на :8001, реальный MAX требует токена и webhook
- Порог 3 дня — гипотеза, требует валидации
- GigaChat Freemium 1 поток, 1M токенов/год, без него — только ключевые слова
- Утечка SECRET_KEY → деанонимизация pseudo_id, нужна ротация

---

## 13. Структура репозитория для сдачи

```
.
├── backend/ (app.py, ai.py, models.py, schemas.py, security.py, crud.py, database.py)
├── bot/ (bot_max.py, texts.py, keyboards.py)
├── miniapp/ (student.html, psych.html, app.js, style.css)
├── Dockerfile (FROM python:3.11-slim, uvicorn main:app --port 8000)
├── docker-compose.yml (backend 8000, bot 8001)
├── .dockerignore
├── .env.example (без токенов)
├── requirements.txt
├── main.py (объединённый для Amvera)
├── README.md (этот файл)
└── Презентация_Антибуллинг_радар.pdf (первый слайд — техинфо)
```

**Docker-образ собирается < 5 мин, без избыточных операций.**

**Фиксированная версия:** commit hash в GitHub после дедлайна не меняется, архив с контрольной суммой `sha256sum anti-bullying-radar-final.zip`.

