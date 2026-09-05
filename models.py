from sqlalchemy import Column, Integer, String, Text, DateTime, Date, Boolean, ForeignKey, Enum
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from database import Base
import enum

class UserRole(str, enum.Enum):
    admin = "admin"
    manager = "manager"
    executor = "executor"

class TaskStatus(str, enum.Enum):
    new = "new"
    in_progress = "in_progress"
    on_review = "on_review"
    completed = "completed"

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    telegram_id = Column(String, nullable=True)
    full_name = Column(String, nullable=True)
    role = Column(Enum(UserRole), default=UserRole.executor)
    theme_preference = Column(String, default="auto")   # auto, light, dark
    sound_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    tasks = relationship("Task", secondary="task_assignees", back_populates="assignees")

class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, default="")
    status = Column(Enum(TaskStatus), default=TaskStatus.new)
    priority = Column(String, default="normal")  # low, normal, high
    deadline = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    scheduled_date = Column(Date, nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"))

    created_by = relationship("User", foreign_keys=[created_by_id])
    assignees = relationship("User", secondary="task_assignees", back_populates="tasks")
    comments = relationship("Comment", back_populates="task", cascade="all, delete-orphan")

class TaskAssignee(Base):
    __tablename__ = "task_assignees"

    task_id = Column(Integer, ForeignKey("tasks.id"), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)

class Comment(Base):
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    task = relationship("Task", back_populates="comments")
    user = relationship("User")