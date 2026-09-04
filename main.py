from fastapi import FastAPI, Request, Response, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.exceptions import HTTPException as StarletteHTTPException
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from database import init_db, AsyncSessionLocal
from models import User, Task, TaskStatus, TaskAssignee, Comment
from auth import get_current_user, set_user_cookie, COOKIE_NAME
from jinja2 import Environment, FileSystemLoader
from datetime import datetime

# Настройка Jinja2
env = Environment(loader=FileSystemLoader('templates'))

def render_template(name: str, **kwargs) -> str:
    template = env.get_template(name)
    return template.render(**kwargs)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(lifespan=lifespan)

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 401:
        return RedirectResponse("/login", status_code=302)
    return HTMLResponse(content=str(exc.detail), status_code=exc.status_code)

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, user=Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        # Получаем ВСЕ задачи, без фильтрации по пользователю
        result = await session.execute(
            select(Task)
            .options(selectinload(Task.assignees))
            .order_by(Task.created_at.desc())
        )
        tasks = result.scalars().all()
    html = render_template("index.html", user=user, tasks=tasks, TaskStatus=TaskStatus)
    return HTMLResponse(content=html)

@app.get("/login", response_class=HTMLResponse)
async def login_page():
    html = render_template("login.html", user=None)
    return HTMLResponse(content=html)

@app.post("/login")
async def login(username: str = Form(...)):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        if not user:
            user = User(
                telegram_id=f"temp_{username}",
                username=username,
                full_name=username,
                role="executor"
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
        user_id = user.id
    response = RedirectResponse("/", status_code=302)
    set_user_cookie(response, user_id)
    return response

@app.get("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie(COOKIE_NAME)
    return response

@app.post("/tasks/create")
async def create_task(
    title: str = Form(...),
    description: str = Form(""),
    deadline: str = Form(""),
    user=Depends(get_current_user)
):
    async with AsyncSessionLocal() as session:
        # Преобразуем deadline из строки в datetime, если задан
        deadline_dt = None
        if deadline:
            try:
                deadline_dt = datetime.fromisoformat(deadline)
            except ValueError:
                deadline_dt = None

        # Создаем задачу
        task = Task(
            title=title,
            description=description,
            deadline=deadline_dt,
            created_by_id=user["id"],
            status=TaskStatus.new
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)

        # Назначаем создателя исполнителем (пока только он)
        assignee = TaskAssignee(task_id=task.id, user_id=user["id"])
        session.add(assignee)
        await session.commit()

    return RedirectResponse("/", status_code=302)

@app.get("/tasks/{task_id}", response_class=HTMLResponse)
async def task_detail(task_id: int, request: Request, user=Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        # Получаем задачу с загрузкой исполнителей и комментариев с авторами
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

        # Доступ открыт для всех авторизованных пользователей
        # (проверка доступа удалена)

        # Комментарии уже загружены через selectinload
        comments = task.comments  # используем уже загруженную связь

    html = render_template("task_detail.html", task=task, comments=comments, user=user)
    return HTMLResponse(content=html)

@app.post("/tasks/{task_id}/comments")
async def add_comment(
    task_id: int,
    text: str = Form(...),
    user=Depends(get_current_user)
):
    async with AsyncSessionLocal() as session:
        # Проверяем существование задачи
        result = await session.execute(select(Task).where(Task.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            raise StarletteHTTPException(status_code=404, detail="Задача не найдена")

        # Доступ открыт всем авторизованным пользователям
        # (проверка доступа удалена)

        # Создаем комментарий
        comment = Comment(
            task_id=task_id,
            user_id=user["id"],
            text=text
        )
        session.add(comment)
        await session.commit()

    return RedirectResponse(f"/tasks/{task_id}", status_code=302)

@app.post("/tasks/{task_id}/complete")
async def complete_task(task_id: int, user=Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Task).where(Task.id == task_id))
        task = result.scalar_one_or_none()
        if task:
            task.status = TaskStatus.completed
            await session.commit()
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