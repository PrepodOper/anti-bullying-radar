def main_keyboard():
    return {
        "buttons": [
            ["📓 Дневник", "📊 История"],
            ["🆘 SOS", "💬 Поговорить"],
            ["Конфиденциальность", "Помощь"]
        ]
    }

def mood_keyboard():
    return {
        "buttons": [
            ["😢 1", "😕 2", "😐 3", "🙂 4", "😄 5"],
            ["🆘 SOS"]
        ],
        "hint": "Выбери 1–5"
    }

def trigger_keyboard():
    return {
        "buttons": [
            ["Поговорить с психологом"],
            ["Пока не готов", "📊 История"]
        ]
    }

def sos_keyboard():
    return {
        "buttons": [
            ["Отправить SOS"],
            ["Не сейчас"]
        ]
    }

def risk_keyboard():
    return {
        "buttons": [
            ["Дать номер горячей линии"],
            ["Передать контакт психологу"],
            ["🆘 SOS"]
        ]
    }
