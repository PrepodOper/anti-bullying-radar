from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os

# Импортируем оба приложения
from backend.app import app as backend_app
from bot.bot_max import app as bot_app
from backend.app import ensure_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[main] lifespan start", flush=True)
    await ensure_db()
    yield
    print("[main] lifespan shutdown", flush=True)

# Единое приложение на одном порту 8000
app = FastAPI(
    title="Антибуллинг-радар — объединённый",
    version="1.0.0-mvp",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Копируем все маршруты из бэкенда и бота
for route in backend_app.routes:
    app.routes.append(route)

for route in bot_app.routes:
    # Пропускаем дубли (например /health если уже есть)
    exists = any(r.path == route.path and getattr(r, 'methods', None) == getattr(route, 'methods', None) for r in app.routes)
    if not exists:
        app.routes.append(route)

# Копируем обработчики событий on_startup если есть (для совместимости)
# Но lifespan уже покрывает инициализацию БД

@app.get("/health")
async def health_combined():
    return {"status": "ok", "service": "anti-bullying-radar-combined", "version": "1.0.0-mvp"}

print("[main] Объединённое приложение готово: backend + bot на одном порту 8000", flush=True)
