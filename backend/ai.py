"""
GigaChat Lite — гибридный детектор риска для Антибуллинг-радара
Level 1: ключевые слова — мгновенно, без API
Level 2: если не сработало — GigaChat Lite (если есть ключи), иначе fallback
Не ставит диагнозов, только risk standard/elevated + эмпатичный reply
"""
import os
import time
import uuid
import httpx
import json
import base64

# --- Ключевые маркеры (мгновенный путь, без API) ---
RISK_KEYWORDS = [
    "не хочу жить", "хочу умереть", "покончить с собой", "суицид",
    "вскрою", "прыгну", "повешусь", "не хочу просыпаться",
    "лучше бы меня не было", "ненавижу себя", "я лишний",
]

def keyword_risk(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in RISK_KEYWORDS)

# --- GigaChat OAuth ---
GIGACHAT_CLIENT_ID = os.getenv("GIGACHAT_CLIENT_ID", "")
GIGACHAT_CLIENT_SECRET = os.getenv("GIGACHAT_CLIENT_SECRET", "")
GIGACHAT_SCOPE = os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")
GIGACHAT_MODEL = os.getenv("GIGACHAT_MODEL", "GigaChat")

_token_cache = {"access_token": None, "expires_at": 0}

async def get_gigachat_token() -> str | None:
    if not GIGACHAT_CLIENT_ID or not GIGACHAT_CLIENT_SECRET:
        return None
    # кэш
    if _token_cache["access_token"] and time.time() < _token_cache["expires_at"] - 60:
        return _token_cache["access_token"]
    try:
        # GigaChat OAuth: POST https://ngw.devices.sberbank.ru:9443/api/v2/oauth
        # Authorization: Basic base64(client_id:client_secret)
        creds = f"{GIGACHAT_CLIENT_ID}:{GIGACHAT_CLIENT_SECRET}"
        basic = base64.b64encode(creds.encode()).decode()
        url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "RqUID": str(uuid.uuid4()),
            "Authorization": f"Basic {basic}",
        }
        data = {"scope": GIGACHAT_SCOPE}
        async with httpx.AsyncClient(timeout=10, verify=False) as client:
            r = await client.post(url, headers=headers, data=data)
            if r.status_code != 200:
                print(f"[GigaChat OAuth] {r.status_code} {r.text[:500]}")
                return None
            j = r.json()
            _token_cache["access_token"] = j.get("access_token")
            exp = j.get("expires_in") or j.get("expires_at") or 1800
            try:
                exp = int(exp)
                # если это timestamp а не seconds
                if exp > 1000000000:
                    exp = exp - int(time.time())
            except:
                exp = 1800
            _token_cache["expires_at"] = time.time() + exp
            print(f"[GigaChat OAuth] token ok, expires_in={exp}")
            return _token_cache["access_token"]
    except Exception as e:
        print(f"[GigaChat OAuth error] {e}")
        return None

SYSTEM_PROMPT = (
    "Ты — чуткий помощник Антибуллинг-радара для подростков. "
    "Твоя задача — поддержать, не навредить. "
    "Правила:\n"
    "- НЕ ставь диагнозов, не пиши «у тебя депрессия».\n"
    "- НЕ давай медицинских советов.\n"
    "- Определи уровень риска: elevated (мысли о самоповреждении, суициде, безнадежности) или standard (грусть, конфликт, стресс).\n"
    "- Если elevated: дай короткий эмпатичный ответ (2-3 предложения), скажи что человек не один, предложи горячую линию 8-800-2000-122 (круглосуточно, бесплатно) и кнопку «Передать контакт психологу».\n"
    "- Если standard: поддержи, предложи рассказать подробнее или отметить настроение.\n"
    "Ответь строго JSON без пояснений: {\"risk\": \"standard\"|\"elevated\", \"reply\": \"текст\"}"
)

async def gigachat_classify(text: str) -> dict | None:
    token = await get_gigachat_token()
    if not token:
        return None
    try:
        url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        }
        body = {
            "model": GIGACHAT_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text[:1000]},
            ],
            "temperature": 0.2,
            "max_tokens": 300,
        }
        async with httpx.AsyncClient(timeout=12, verify=False) as client:
            r = await client.post(url, headers=headers, json=body)
            if r.status_code != 200:
                print(f"[GigaChat chat] {r.status_code} {r.text[:700]}")
                return None
            j = r.json()
            content = j["choices"][0]["message"]["content"].strip()
            # Попытка распарсить JSON, если модель вернула с ```json
            if "```" in content:
                content = content.split("```")[1]
                content = content.replace("json", "").strip()
            data = json.loads(content)
            risk = data.get("risk", "standard")
            reply = data.get("reply", "")
            if risk not in ("standard", "elevated"):
                risk = "standard"
            return {"risk": risk, "reply": reply}
    except Exception as e:
        print(f"[GigaChat classify error] {e}")
        return None

async def ai_dialog(text: str) -> dict:
    """
    Возвращает {"risk": "standard"|"elevated", "reply": str|None}
    reply=None значит использовать дефолтный шаблон из texts.py
    """
    # 1. Мгновенный путь — ключевые слова
    if keyword_risk(text):
        print(f"[AI] keyword elevated: {text[:60]}")
        # Пробуем получить эмпатичный reply от LLM, но если нет ключа — вернем None (бэкенд подставит шаблон)
        llm = await gigachat_classify(text)
        if llm and llm["risk"] == "elevated":
            return llm
        return {"risk": "elevated", "reply": None}

    # 2. LLM-путь (если есть ключи)
    if GIGACHAT_CLIENT_ID and GIGACHAT_CLIENT_SECRET:
        llm = await gigachat_classify(text)
        if llm:
            print(f"[AI] LLM {llm['risk']}: {text[:60]}")
            return llm

    # 3. Fallback — без ИИ
    return {"risk": "standard", "reply": None}

# Тест локально: python -m backend.ai "мне грустно"
if __name__ == "__main__":
    import asyncio
    async def _t():
        for txt in ["мне грустно", "не хочу жить", "меня булят в школе"]:
            print(txt, "=>", await ai_dialog(txt))
    asyncio.run(_t())
