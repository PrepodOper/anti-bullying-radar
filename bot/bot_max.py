import os
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

try:
    from bot.texts import *
    from bot.keyboards import main_keyboard, mood_keyboard, trigger_keyboard, sos_keyboard, risk_keyboard
except ImportError:
    from texts import *
    from keyboards import main_keyboard, mood_keyboard, trigger_keyboard, sos_keyboard, risk_keyboard

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
MAX_BOT_TOKEN = os.getenv("MAX_BOT_TOKEN", "")
MAX_API_BASE = os.getenv("MAX_API_BASE", "https://platform-api.max.ru")

app = FastAPI(title="MAX Bot — Антибуллинг-радар", version="1.0.0-mvp")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

sessions = {}

async def call_backend(path: str, method="POST", json=None, params=None):
    async with httpx.AsyncClient(timeout=10) as client:
        url = f"{BACKEND_URL}{path}"
        if method == "GET":
            r = await client.get(url, params=params)
        else:
            r = await client.post(url, json=json)
        try:
            return r.json()
        except:
            return {"raw": r.text, "status": r.status_code}

async def send_max_message(chat_id: str, text: str, keyboard=None):
    if not MAX_BOT_TOKEN or MAX_BOT_TOKEN == "your_max_bot_token_here":
        print(f"[MAX MOCK → {chat_id}] {text[:120]}")
        return {"ok": True}

    # Преобразуем наши keyboard {"buttons": [["A","B"]]} в формат MAX: attachments -> inline_keyboard
    attachments = []
    if keyboard:
        try:
            buttons = []
            if "buttons" in keyboard:
                for row in keyboard["buttons"]:
                    max_row = []
                    for btn in row:
                        label = btn if isinstance(btn, str) else btn.get("label", str(btn))
                        # Определяем тип: SOS/Дневник/История — callback, ссылка — link, web_app — link
                        if "http" in label:
                            max_row.append({"type": "link", "text": label, "url": label})
                        else:
                            max_row.append({"type": "callback", "text": label, "payload": label})
                    buttons.append(max_row)
            elif "inline_keyboard" in keyboard:
                buttons = keyboard["inline_keyboard"]
            if buttons:
                attachments.append({
                    "type": "inline_keyboard",
                    "payload": {"buttons": buttons}
                })
        except Exception as e:
            print(f"[keyboard convert error] {e}")

    payload = {"text": text}
    if attachments:
        payload["attachments"] = attachments

    # MAX принимает либо ?chat_id= либо ?user_id= для лички. Пробуем оба.
    bases = [MAX_API_BASE, "https://platform-api.max.ru", "https://platform-api2.max.ru"]
    bases = list(dict.fromkeys(bases))
    last_err = None
    for base in bases:
        for param_name in ["chat_id", "user_id"]:
            url = f"{base}/messages"
            params = {param_name: str(chat_id)}
            headers = {"Authorization": MAX_BOT_TOKEN, "Content-Type": "application/json"}
            try:
                async with httpx.AsyncClient(timeout=10, verify=False) as client:
                    r = await client.post(url, params=params, json=payload, headers=headers)
                    print(f"[MAX SEND {base} ?{param_name}={chat_id}] HTTP {r.status_code} {r.text[:700]}")
                    if r.status_code < 300:
                        try: return r.json()
                        except: return {"status": r.status_code}
                    if r.status_code == 401:
                        # пробуем с Bearer
                        headers2 = {"Authorization": f"Bearer {MAX_BOT_TOKEN}", "Content-Type": "application/json"}
                        r2 = await client.post(url, params=params, json=payload, headers=headers2)
                        print(f"[MAX SEND Bearer retry {base}] HTTP {r2.status_code} {r2.text[:700]}")
                        if r2.status_code < 300:
                            try: return r2.json()
                            except: return {"status": r2.status_code}
                    # если 400 с "chat not found" пробуем другой param
                    if r.status_code == 400 and "chat" in r.text.lower():
                        continue
                    last_err = f"{base} ?{param_name} -> {r.status_code} {r.text[:200]}"
                    if r.status_code < 500:
                        break
            except Exception as e:
                print(f"[MAX SEND ERROR {base} ?{param_name}] {e}")
                last_err = str(e)
                continue
        if last_err and "200" in last_err:
            break
    print(f"[MAX SEND FAILED] {last_err}")
    return {"ok": False, "error": last_err}

def get_session(uid: str):
    if uid not in sessions:
        sessions[uid] = {"class_group": None, "state": "new"}
    return sessions[uid]

def extract_max_update(data: dict):
    if "max_user_id" in data:
        return data.get("max_user_id"), data.get("text",""), data.get("chat_id") or data.get("max_user_id"), data
    updates = data.get("updates") if "updates" in data else [data]
    for upd in updates:
        msg = upd.get("message") or upd
        sender = msg.get("sender") or {}
        body = msg.get("body") or {}
        chat_id = msg.get("chat_id") or msg.get("recipient", {}).get("chat_id") or sender.get("user_id") or upd.get("chat_id")
        user_id = sender.get("user_id") or msg.get("user_id") or chat_id
        text = body.get("text") or msg.get("text") or upd.get("text") or ""
        payload = msg.get("payload") or body.get("payload") or upd.get("payload")
        if payload and not text:
            text = payload
        if upd.get("callback", {}).get("payload"):
            text = upd["callback"]["payload"]
        # callback payload может быть в message.callback
        if msg.get("callback", {}).get("payload"):
            text = msg["callback"]["payload"]
        if user_id and chat_id:
            return str(user_id), str(text or ""), str(chat_id), upd
    return "test_user_1", data.get("text",""), "test_user_1", data

async def handle_logic(max_user_id: str, text: str, sess: dict):
    raw_text = text.strip()
    low = raw_text.lower()

    # --- старт ---
    if low in ["/start", "начать", "привет", "старт", "start", "поехали", "привет!"]:
        sess["state"] = "await_class"
        return WELCOME, {"buttons": [["8-параллель", "9-параллель", "10-параллель", "11-параллель"]]}

    # --- класс ---
    if sess.get("state") == "await_class" or low in ["8-параллель","9-параллель","10-параллель","11-параллель","8а","9б","10в","8б","9а","10а","11а"] or raw_text in ["8-параллель","9-параллель","10-параллель","11-параллель","8А","9Б","10В","8Б","9А","10А","11А"]:
        normalized = raw_text
        if len(raw_text) >= 1 and raw_text[0].isdigit():
            normalized = f"{raw_text[0]}-параллель"
            if raw_text.upper() in ["8А","8Б","9А","9Б","10А","11А"]:
                normalized = raw_text.upper()
        sess["class_group"] = normalized
        sess["state"] = "ready"
        return f"Отлично, запомнил: {normalized}. Теперь всё анонимно — психолог видит только это.\n\n" + MOOD_ASK, mood_keyboard()

    # --- оценка настроения 1-5 ---
    if low in ["1","2","3","4","5"] or raw_text in MOOD_LABELS.values() or any(str(i) in raw_text for i in [1,2,3,4,5]):
        level = None
        for k,v in MOOD_LABELS.items():
            if str(k) == raw_text or v == raw_text or str(k) in raw_text:
                level = k
                break
        if level is None:
            try: level = int(raw_text[0])
            except: pass
        if level:
            cg = sess.get("class_group") or "не указано"
            res = await call_backend("/api/mood", json={"max_user_id": max_user_id, "mood_level": level, "class_group": cg})
            reply = res.get("message", MOOD_THANKS)
            kb = main_keyboard()
            if res.get("trigger_3day"):
                reply = TRIGGER_3DAY
                kb = trigger_keyboard()
            return reply, kb

    # --- команды человеческими словами (без слэшей, case-insensitive) ---
    if low in ["/mood", "дневник", "📓 дневник", "дневник настроения", "настроение", "дневник настроения".lower()] or "дневник" in low:
        return MOOD_ASK, mood_keyboard()

    if low in ["/sos", "🆘 sos", "sos", "сос", "тревога", "помогите"] or "sos" in low:
        return SOS_CONFIRM, sos_keyboard()

    if low in ["отправить sos", "подтвердить sos", "да, отправить", "отправить", "да отправить"]:
        cg = sess.get("class_group") or "не указано"
        res = await call_backend("/api/sos", json={"max_user_id": max_user_id, "trigger_type": "manual_sos", "risk_level": "standard", "class_group": cg})
        return SOS_SENT, main_keyboard()

    if low in ["поговорить с психологом", "да, хочу поговорить", "хочу поговорить", "психолог"]:
        cg = sess.get("class_group") or "не указано"
        res = await call_backend("/api/sos", json={"max_user_id": max_user_id, "trigger_type": "3day_decline", "risk_level": "standard", "class_group": cg})
        return "Заявка отправлена психологу (анонимно, только параллель). Он получит уведомление и предложит время. Если хочешь — можешь раскрыть контакт позже.", main_keyboard()

    if low in ["пока не готов", "не сейчас", "потом", "не хочу"]:
        return "Понимаю. Я рядом — можешь написать в любой момент или нажать SOS. А пока — хочешь посмотреть график настроения?", main_keyboard()

    if low in ["дать номер горячей линии", "горячая линия", "телефон доверия", "горячая линия".lower()]:
        return HOTLINE, main_keyboard()

    if low in ["передать контакт психологу", "раскрыть контакт", "передать контакт"]:
        res = await call_backend("/api/consent/disclose", json={"max_user_id": max_user_id, "consent": True})
        return DISCLOSE_DONE + "\n\n" + HOTLINE, main_keyboard()

    if low in ["/privacy", "конфиденциальность", "приватность", "анонимность"]:
        return PRIVACY_NOTE, main_keyboard()

    if low in ["/help", "помощь", "что ты умеешь", "помоги", "help"]:
        return HELP_TEXT, main_keyboard()

    if low in ["/history", "📊 история", "история", "моя история", "график", "график настроения"]:
        return f"Твоя история настроения — в мини-приложении:\n{BACKEND_URL}/miniapp/student.html?uid={max_user_id}", main_keyboard()
    if text:
        cg = sess.get("class_group") or "не указано"
        res = await call_backend("/api/dialog", json={"max_user_id": max_user_id, "text": text, "class_group": cg})
        if res.get("risk_level") == "elevated":
            return res["reply"] + "\n\n" + LEVEL2_RISK + "\n\nГорячая линия: " + res.get("hotline","8-800-2000-122"), risk_keyboard()
        else:
            return res.get("reply", "Спасибо, что написал."), main_keyboard()
    return "Не понял. Нажми кнопку ниже или напиши сообщение.", main_keyboard()

@app.post("/webhook")
async def webhook(req: Request):
    data = await req.json()
    print(f"[WEBHOOK IN] {str(data)[:900]}")
    is_emulator = "max_user_id" in data
    if is_emulator:
        max_user_id = data.get("max_user_id", "test_user_1")
        text = data.get("text","")
        chat_id = data.get("chat_id") or max_user_id
        sess = get_session(max_user_id)
        reply, kb = await handle_logic(max_user_id, text, sess)
        return JSONResponse({"reply": reply, "keyboard": kb, "chat_id": chat_id})
    else:
        try:
            max_user_id, text, chat_id, raw = extract_max_update(data)
            print(f"[MAX PARSED] user={max_user_id} chat={chat_id} text={text!r}")
            if not text and not raw.get("message"):
                return JSONResponse({"success": True})
            sess = get_session(str(max_user_id))
            reply, kb = await handle_logic(str(max_user_id), str(text), sess)
            await send_max_message(chat_id, reply, kb)
            return JSONResponse({"success": True})
        except Exception as e:
            import traceback
            print(f"[WEBHOOK ERROR] {e}\n{traceback.format_exc()}")
            return JSONResponse({"success": True, "error": str(e)})

@app.get("/", response_class=HTMLResponse)
async def demo_page():
    return """
<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MAX Бот — Антибуллинг-радар (демо)</title>
<style>
*{box-sizing:border-box;font-family: -apple-system, Inter, Segoe UI, Roboto, sans-serif}
body{margin:0;background:#f0f2f5;display:flex;flex-direction:column;height:100vh}
header{background:#1a6cff;color:#fff;padding:14px 20px;display:flex;align-items:center;gap:12px}
header b{font-size:18px}
header span{opacity:.9;font-size:13px}
.wrap{flex:1;display:flex;gap:16px;padding:16px;max-width:1100px;width:100%;margin:0 auto}
.chat{flex:1;background:#fff;border-radius:16px;box-shadow:0 4px 24px rgba(0,0,0,.08);display:flex;flex-direction:column;overflow:hidden}
.log{flex:1;overflow:auto;padding:16px;display:flex;flex-direction:column;gap:10px;background:#f7f8fa}
.bubble{max-width:78%;padding:10px 14px;border-radius:16px;line-height:1.45;font-size:14px;white-space:pre-wrap;word-break:break-word}
.me{align-self:flex-end;background:#1a6cff;color:#fff;border-bottom-right-radius:4px}
.bot{align-self:flex-start;background:#fff;border:1px solid #e6e8eb;color:#111;border-bottom-left-radius:4px}
.input{display:flex;gap:8px;padding:12px;border-top:1px solid #eee;background:#fff}
.input input{flex:1;padding:12px 14px;border:1px solid #ddd;border-radius:24px;outline:none;font-size:14px}
.input button{padding:10px 18px;border:0;background:#1a6cff;color:#fff;border-radius:24px;cursor:pointer;font-weight:600}
.kb{display:flex;flex-wrap:wrap;gap:6px;padding:8px 12px;border-top:1px dashed #eee;background:#fafbff}
.kb button{padding:7px 12px;border:1px solid #dbe4ff;background:#eef3ff;color:#1a3a8a;border-radius:20px;cursor:pointer;font-size:13px}
.kb button.sos{background:#ff2e55;color:#fff;border-color:#ff2e55;font-weight:700}
.side{width:360px;background:#fff;border-radius:16px;box-shadow:0 4px 24px rgba(0,0,0,.08);padding:16px;overflow:auto}
.side h3{margin:0 0 8px;font-size:14px}
.side p, .side li{font-size:12.5px;color:#333;line-height:1.5}
code{background:#f0f2f5;padding:2px 6px;border-radius:6px;font-size:12px}
a{color:#1a6cff}
</style>
</head>
<body>
<header>
  <div style="width:36px;height:36px;background:#fff;color:#1a6cff;border-radius:10px;display:grid;place-items:center;font-weight:800">M</div>
  <div><b>Антибуллинг-радар</b> · Чат-бот MAX <span>демо-эмулятор</span></div>
  <div style="margin-left:auto;display:flex;gap:8px;align-items:center">
    <input id="uid" value="test_user_1" style="padding:6px 10px;border-radius:20px;border:0;width:140px" placeholder="MAX user id">
    <select id="cg" style="padding:6px 10px;border-radius:20px;border:0">
      <option>8-параллель</option><option>9-параллель</option><option>10-параллель</option><option>11-параллель</option>
    </select>
  </div>
</header>
<div class="wrap">
  <div class="chat">
    <div id="log" class="log"></div>
    <div id="kb" class="kb" style="display:none"></div>
    <div class="input">
      <input id="inp" placeholder="Напиши сообщение... (попробуй: мне очень плохо, не хочу жить)" onkeydown="if(event.key==='Enter')send()">
      <button onclick="send()">Отправить</button>
      <button onclick="sendSOS()" style="background:#ff2e55">SOS</button>
    </div>
  </div>
  <div class="side">
    <h3>🧪 Быстрые сценарии</h3>
    <ul>
      <li><a href="#" onclick="quick('/start');return false">/start — вход</a></li>
      <li><a href="#" onclick="quick('5');return false">Отметить 5 → 3 → 2 (триггер 3 дня)</a></li>
      <li><a href="#" onclick="quick('я не хочу жить');return false">Тест маркера риска (Уровень 2)</a></li>
      <li><a href="#" onclick="quick('/history');return false">История / мини-приложение</a></li>
      <li><a href="#" onclick="quick('/privacy');return false">Конфиденциальность</a></li>
    </ul>
    <p><b>Потоки данных:</b> ученик → MAX → webhook → бэкенд (HMAC) → уведомление психолога</p>
    <p><b>Бэкенд:</b> <code id="backendUrl"></code></p>
    <p><b>Мини-приложение (ученик):</b> <a id="miniStudent" href="#" target="_blank">открыть</a></p>
    <p><b>Сводка психолога:</b> <a id="miniPsych" href="#" target="_blank">открыть</a></p>
    <p style="background:#fff7e6;border:1px solid #ffe2a8;padding:8px;border-radius:10px">⚠️ MVP: тестовые данные, без реальной интеграции MAX. Для прода — указать токен в .env.</p>
    <h3>Формулировки бота</h3>
    <p><code>Приветствие, триггер 3 дня, SOS, Уровень 2 — см. bot/texts.py</code></p>
  </div>
</div>
<script>
const backend = location.protocol + '//' + location.hostname + ':8000';
document.getElementById('backendUrl').textContent = backend;
document.getElementById('miniStudent').href = backend + '/miniapp/student.html';
document.getElementById('miniPsych').href = backend + '/miniapp/psych.html';
const log = document.getElementById('log');
const kb = document.getElementById('kb');
function bubble(text, who){
  const d=document.createElement('div');
  d.className='bubble '+(who==='me'?'me':'bot');
  d.textContent=text;
  log.appendChild(d);
  log.scrollTop=log.scrollHeight;
}
function renderKB(buttons){
  if(!buttons || !buttons.length){ kb.style.display='none'; kb.innerHTML=''; return;}
  kb.style.display='flex'; kb.innerHTML='';
  buttons.forEach(b=>{
    const btn=document.createElement('button');
    btn.textContent=b.label||b;
    if((b.label||b).includes('SOS')) btn.classList.add('sos');
    btn.onclick=()=>quick(b.label||b);
    kb.appendChild(btn);
  });
}
async function quick(text){
  document.getElementById('inp').value=text;
  await send();
}
async function send(){
  const inp=document.getElementById('inp');
  const text=inp.value.trim();
  if(!text) return;
  const uid=document.getElementById('uid').value.trim()||'test_user_1';
  inp.value='';
  bubble(text,'me');
  const res = await fetch('/webhook', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({max_user_id: uid, text, class_group: document.getElementById('cg').value})
  }).then(r=>r.json()).catch(e=>({reply:'Ошибка соединения с эмулятором: '+e.message}));
  bubble(res.reply||JSON.stringify(res,null,2),'bot');
  const k = res.keyboard;
  if(k){
    let btns=[];
    if(k.buttons) btns = k.buttons.flat().map(x=>({label:x}));
    else if(k.inline_keyboard) btns = k.inline_keyboard.flat();
    else if(Array.isArray(k)) btns = k;
    renderKB(btns);
  }
  if(res.hotline){ bubble(res.hotline,'bot'); }
  if(res.backend){ console.log('backend:',res.backend); }
}
function sendSOS(){ quick('🆘 SOS'); }
bubble(`Привет! Я — Антибуллинг-радар 🤖\\n\\nПсихолог и одноклассники не узнают, что это ты, пока сам не решишь раскрыться.\\n\\nНажми /start чтобы начать.`, 'bot');
renderKB([{label:'/start'},{label:'📓 Дневник'},{label:'🆘 SOS'},{label:'/privacy'}]);
</script>
</body>
</html>
    """

@app.get("/health")
async def health():
    return {"status": "ok", "service": "max-bot-mock"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("BOT_PORT", "8001")))
