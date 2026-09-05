import hashlib
import os
import base64
from fastapi import Request, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database import AsyncSessionLocal
from models import User

COOKIE_NAME = "user_id"

def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return base64.b64encode(salt + dk).decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        decoded = base64.b64decode(hashed_password.encode('utf-8'))
        salt = decoded[:16]
        stored_hash = decoded[16:]
        dk = hashlib.pbkdf2_hmac('sha256', plain_password.encode('utf-8'), salt, 100000)
        return dk == stored_hash
    except Exception:
        return False

async def get_current_user(request: Request) -> User:
    user_id = request.cookies.get(COOKIE_NAME)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    async with AsyncSessionLocal() as session:
        user = await session.get(User, int(user_id))
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user

def set_user_cookie(response, user_id: int):
    response.set_cookie(COOKIE_NAME, str(user_id), httponly=True, max_age=30*24*3600)