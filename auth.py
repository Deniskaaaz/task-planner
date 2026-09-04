from fastapi import Request, Response, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from database import AsyncSessionLocal
import json

COOKIE_NAME = "user_id"

async def get_current_user(request: Request) -> dict:
    user_id = request.cookies.get(COOKIE_NAME)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    # десь можно загрузить пользователя из , но пока возвращаем просто id
    return {"id": int(user_id)}

def set_user_cookie(response: Response, user_id: int):
    response.set_cookie(COOKIE_NAME, str(user_id), httponly=True, max_age=30*24*3600)
