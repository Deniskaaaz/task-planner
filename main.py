import os
import json
from fastapi import FastAPI, Request, Response, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.exceptions import HTTPException as StarletteHTTPException
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from database import init_db, AsyncSessionLocal
from models import User, Task, TaskStatus, TaskAssignee, Comment
from auth import get_current_user, set_user_cookie, COOKIE_NAME, hash_password, verify_password
from jinja2 import Environment, FileSystemLoader
from datetime import datetime, date, timedelta
from notifications import start_bot_background, send_telegram_notification

# Настройка Jinja2
env = Environment(loader=FileSystemLoader('templates'))

def render_template(name: str, **kwargs) -> str:
    template = env.get_template(name)
    return template.render(**kwargs)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    start_bot_background()   # Запускаем Telegram-бота в фоне
    yield

app = FastAPI(lifespan=lifespan)

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 401:
        return RedirectResponse("/login", status_code=302)
    return HTMLResponse(content=str(exc.detail), status_code=exc.status_code)

# ---------- Главная страница ----------
@app.get("/", response_class=HTMLResponse)
async def index(request: Request, user=Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Task)
            .options(selectinload(Task.assignees))
            .order_by(Task.created_at.desc())
        )
        tasks = result.scalars().all()
    html = render_template("index.html", user=user, tasks=tasks, TaskStatus=TaskStatus)
    return HTMLResponse(content=html)

# ---------- Аутентификация ----------
@app.get("/login", response_class=HTMLResponse)
async def login_page():
    html = render_template("login.html", user=None)
    return HTMLResponse(content=html)

@app.post("/login")
async def login(
    username: str = Form(...),
    password: str = Form(...)
):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        if not user or not verify_password(password, user.password_hash):
            return HTMLResponse(render_template("login.html", error="Неверный логин или пароль", user=None), status_code=400)
        user_id = user.id
    response = RedirectResponse("/", status_code=302)
    set_user_cookie(response, user_id)
    return response

@app.get("/register", response_class=HTMLResponse)
async def register_page():
    html = render_template("register.html", user=None)
    return HTMLResponse(content=html)

@app.post("/register")
async def register(
    username: str = Form(...),
    password: str = Form(...),
    full_name: str = Form("")
):
    async with AsyncSessionLocal() as session:
        # Проверяем, существует ли пользователь
        result = await session.execute(select(User).where(User.username == username))
        existing = result.scalar_one_or_none()
        if existing:
            return HTMLResponse(render_template("register.html", error="Пользователь уже существует", user=None), status_code=400)

        hashed = hash_password(password)
        new_user = User(
            username=username,
            password_hash=hashed,
            full_name=full_name or username,
            telegram_id=None,
            role="executor"
        )
        session.add(new_user)
        await session.commit()
        await session.refresh(new_user)

    response = RedirectResponse("/", status_code=302)
    set_user_cookie(response, new_user.id)
    return response

@app.get("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie(COOKIE_NAME)
    return response

# ---------- Профиль ----------
@app.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request, user=Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.id == user.id))
        db_user = result.scalar_one_or_none()
    html = render_template("profile.html", user=db_user, error=None)
    return HTMLResponse(content=html)

@app.post("/profile", response_class=HTMLResponse)
async def update_profile(
    telegram_id: str = Form(""),
    user=Depends(get_current_user)
):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.id == user.id))
        db_user = result.scalar_one_or_none()
        if db_user:
            db_user.telegram_id = telegram_id.strip() or None
            await session.commit()
            await session.refresh(db_user)
            html = render_template("profile.html", user=db_user, error=None)
            return HTMLResponse(content=html)
        else:
            html = render_template("profile.html", user=user, error="Пользователь не найден")
            return HTMLResponse(content=html)

# ---------- Задачи ----------
@app.post("/tasks/create")
async def create_task(
    title: str = Form(...),
    description: str = Form(""),
    deadline: str = Form(""),
    scheduled_date: str = Form(""),
    priority: str = Form("normal"),
    user=Depends(get_current_user)
):
    async with AsyncSessionLocal() as session:
        deadline_dt = None
        if deadline:
            try:
                deadline_dt = datetime.fromisoformat(deadline)
            except ValueError:
                deadline_dt = None

        scheduled_date_dt = None
        if scheduled_date:
            try:
                scheduled_date_dt = date.fromisoformat(scheduled_date)
            except ValueError:
                scheduled_date_dt = None

        task = Task(
            title=title,
            description=description,
            deadline=deadline_dt,
            scheduled_date=scheduled_date_dt,
            priority=priority,
            created_by_id=user.id,          # было user["id"]
            status=TaskStatus.new
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)

        assignee = TaskAssignee(task_id=task.id, user_id=user.id)  # было user["id"]
        session.add(assignee)
        await session.commit()

        # Уведомление создателю задачи
        creator = await session.get(User, user.id)  # было user["id"]
        if creator and creator.telegram_id:
            await send_telegram_notification(creator.telegram_id, f"Создана задача: {title}")

    return RedirectResponse("/", status_code=302)

@app.get("/tasks/{task_id}", response_class=HTMLResponse)
async def task_detail(task_id: int, request: Request, user=Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Task)
            .options(
                selectinload(Task.assignees),
                selectinload(Task.comments).selectinload(Comment.user)
            )
            .where(Task.id == task_id)
        )
        task = result.scalar_one_or_none()
        if not task:
            raise StarletteHTTPException(status_code=404, detail="Задача не найдена")

        comments = task.comments

    html = render_template("task_detail.html", task=task, comments=comments, user=user)
    return HTMLResponse(content=html)

@app.post("/tasks/{task_id}/comments")
async def add_comment(
    task_id: int,
    text: str = Form(...),
    user=Depends(get_current_user)
):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Task)
            .options(selectinload(Task.assignees))
            .where(Task.id == task_id)
        )
        task = result.scalar_one_or_none()
        if not task:
            raise StarletteHTTPException(status_code=404, detail="Задача не найдена")

        comment = Comment(
            task_id=task_id,
            user_id=user.id,              # было user["id"]
            text=text
        )
        session.add(comment)
        await session.commit()

        # Уведомляем всех участников задачи, кроме автора комментария
        recipients = [a for a in task.assignees if a.id != user.id]   # было user["id"]
        for recipient in recipients:
            if recipient.telegram_id:
                await send_telegram_notification(
                    recipient.telegram_id,
                    f"Новый комментарий в задаче «{task.title}»"
                )

    return RedirectResponse(f"/tasks/{task_id}", status_code=302)

@app.post("/tasks/{task_id}/complete")
async def complete_task(task_id: int, user=Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Task)
            .options(selectinload(Task.created_by))
            .where(Task.id == task_id)
        )
        task = result.scalar_one_or_none()
        if task:
            task.status = TaskStatus.completed
            await session.commit()
            if task.created_by and task.created_by.telegram_id:
                await send_telegram_notification(
                    task.created_by.telegram_id,
                    f"Задача «{task.title}» отмечена как выполненная"
                )
    return RedirectResponse("/", status_code=302)

@app.post("/tasks/{task_id}/delete")
async def delete_task(task_id: int, user=Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Task).where(Task.id == task_id))
        task = result.scalar_one_or_none()
        if task:
            await session.delete(task)
            await session.commit()
    return RedirectResponse("/", status_code=302)

# ---------- Календарь ----------
@app.get("/calendar", response_class=HTMLResponse)
async def calendar_page(request: Request, user=Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Task)
            .options(selectinload(Task.assignees))
            .order_by(Task.scheduled_date)
        )
        tasks = result.scalars().all()

    today = date.today()
    start_of_week = today - timedelta(days=today.weekday())
    days = [start_of_week + timedelta(days=i) for i in range(7)]

    tasks_by_day = {d: [] for d in days}
    for task in tasks:
        if task.scheduled_date and task.scheduled_date in days:
            tasks_by_day[task.scheduled_date].append(task)

    html = render_template(
        "calendar.html",
        user=user,
        days=days,
        tasks_by_day=tasks_by_day,
        TaskStatus=TaskStatus
    )
    return HTMLResponse(content=html)

@app.post("/tasks/{task_id}/move")
async def move_task(task_id: int, scheduled_date: str = Form(...), user=Depends(get_current_user)):
    try:
        new_date = date.fromisoformat(scheduled_date)
    except ValueError:
        return JSONResponse({"error": "Invalid date"}, status_code=400)

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Task).where(Task.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            return JSONResponse({"error": "Task not found"}, status_code=404)

        task.scheduled_date = new_date
        await session.commit()

    return JSONResponse({"success": True})

# ---------- Статистика ----------
@app.get("/stats", response_class=HTMLResponse)
async def stats_page(request: Request, user=Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Task).options(selectinload(Task.assignees)))
        tasks = result.scalars().all()

    total = len(tasks)
    completed = sum(1 for t in tasks if t.status == TaskStatus.completed)
    in_progress = sum(1 for t in tasks if t.status == TaskStatus.in_progress)
    new_tasks = sum(1 for t in tasks if t.status == TaskStatus.new)
    on_review = sum(1 for t in tasks if t.status == TaskStatus.on_review)

    now = datetime.now()
    overdue = []
    for t in tasks:
        if t.deadline and t.deadline < now and t.status != TaskStatus.completed:
            overdue.append(t)

    upcoming = sorted(
        [t for t in tasks if t.deadline and t.deadline >= now and t.status != TaskStatus.completed],
        key=lambda x: x.deadline
    )[:5]

    html = render_template(
        "stats.html",
        user=user,
        total=total,
        completed=completed,
        in_progress=in_progress,
        new_tasks=new_tasks,
        on_review=on_review,
        overdue=overdue,
        upcoming=upcoming,
        now=now
    )
    return HTMLResponse(content=html)