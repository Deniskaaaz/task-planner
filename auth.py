import hashlib
import os
import base64
from fastapi import Request, HTTPException

COOKIE_NAME = "user_id"

def hash_password(password: str) -> str:
    """Хэширует пароль с использованием PBKDF2 и случайной соли."""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    # Сохраняем соль и хэш в виде одной строки
    return base64.b64encode(salt + dk).decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Проверяет пароль против хэша."""
    try:
        decoded = base64.b64decode(hashed_password.encode('utf-8'))
        salt = decoded[:16]
        stored_hash = decoded[16:]
        dk = hashlib.pbkdf2_hmac('sha256', plain_password.encode('utf-8'), salt, 100000)
        return dk == stored_hash
    except Exception:
        return False

async def get_current_user(request: Request) -> dict:
    user_id = request.cookies.get(COOKIE_NAME)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"id": int(user_id)}

def set_user_cookie(response, user_id: int):
    response.set_cookie(COOKIE_NAME, str(user_id), httponly=True, max_age=30*24*3600)