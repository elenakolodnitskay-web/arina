import enum
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func

from db.crypto import EncryptedString


class Base(DeclarativeBase):
    pass


class Context(str, enum.Enum):
    work = "work"
    personal = "personal"


class TaskStatus(str, enum.Enum):
    active = "active"
    done = "done"
    cancelled = "cancelled"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    onboarding_completed: Mapped[bool] = mapped_column(default=False)
    profile_summary: Mapped[str | None] = mapped_column(EncryptedString, nullable=True)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(EncryptedString, nullable=False)
    context: Mapped[Context] = mapped_column(SAEnum(Context, native_enum=False, length=16), nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recurrence_rule: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[TaskStatus] = mapped_column(
        SAEnum(TaskStatus, native_enum=False, length=16), default=TaskStatus.active, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    content: Mapped[str] = mapped_column(EncryptedString, nullable=False)
    context: Mapped[Context] = mapped_column(SAEnum(Context, native_enum=False, length=16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DialogSummary(Base):
    __tablename__ = "dialog_summaries"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    context: Mapped[Context] = mapped_column(SAEnum(Context, native_enum=False, length=16), nullable=False)
    summary_text: Mapped[str | None] = mapped_column(EncryptedString, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    message_count_since_update: Mapped[int] = mapped_column(Integer, default=0)
