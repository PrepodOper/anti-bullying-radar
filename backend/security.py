import hmac
import hashlib
import os

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-me-32-chars")

def get_pseudo_id(max_user_id: str) -> str:
    """
    Вычисляет обезличенный псевдо-ID.
    pseudo_id = HMAC_SHA256(secret_key, max_user_id)
    - max_user_id никогда не сохраняется
    - один и тот же max_user_id -> один и тот же pseudo_id (история между сессиями)
    - ключ хранится только в .env, не логируется
    """
    if not max_user_id:
        raise ValueError("max_user_id required")
    secret = SECRET_KEY.encode("utf-8")
    msg = str(max_user_id).encode("utf-8")
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()

def verify_secret_configured() -> bool:
    return SECRET_KEY != "dev-secret-key-change-me-32-chars" and len(SECRET_KEY) >= 16
