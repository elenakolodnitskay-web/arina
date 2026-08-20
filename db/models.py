import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
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


class TransactionType(str, enum.Enum):
    expense = "expense"
    income = "income"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("platform", "telegram_id", name="uq_users_platform_telegram_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # Имя поля осталось из Фазы 2 (когда была только Telegram) — теперь это внешний ID
    # пользователя на любой платформе (для MAX сюда пишется MAX user id). Не
    # переименовано, чтобы не тянуть массовое переименование по всему проекту ради
    # красоты — уникальность обеспечивается парой (platform, telegram_id).
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    platform: Mapped[str] = mapped_column(String(16), default="telegram", server_default="telegram")
    # @username в Telegram — не зашифровано (нужно искать по точному совпадению, а
    # шифрование Fernet не детерминированное — WHERE по зашифрованному полю не
    # сработает, та же причина, что и у telegram_id/platform выше). Обновляется при
    # каждом /start — может немного отставать, если пользователь сменил username и
    # не перезапускал бота (известное упрощение, см. Plan.md Фаза 17).
    username: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    onboarding_completed: Mapped[bool] = mapped_column(default=False)
    profile_summary: Mapped[str | None] = mapped_column(EncryptedString, nullable=True)
    # Баланс — то, что пользователь последний раз назвал сам (нет банковской
    # интеграции и автоматического пересчёта из Transaction, см. CLAUDE.md/Plan.md
    # про известные упрощения Фазы 14).
    balance: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    low_balance_threshold: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)


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


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    transaction_type: Mapped[TransactionType] = mapped_column(
        SAEnum(TransactionType, native_enum=False, length=16), nullable=False
    )
    description: Mapped[str | None] = mapped_column(EncryptedString, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
