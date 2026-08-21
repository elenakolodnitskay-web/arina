import enum
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func

from db.crypto import EncryptedString

# Размерность эмбеддинга openai/text-embedding-3-small (см. llm/embeddings.py) —
# фиксированная константа, а не настройка: смена модели эмбеддингов потребует
# новой миграции (менять размер существующей колонки vector нельзя без пересчёта
# всех эмбеддингов заново).
EMBEDDING_DIM = 1536


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


class ReplyMode(str, enum.Enum):
    text = "text"
    voice = "voice"


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
    # Голосом или текстом отвечать (/voice_mode) — переключается вручную,
    # независимо от формата вопроса пользователя (можно спросить голосом и
    # получить текст, и наоборот). По умолчанию text — прежнее поведение.
    reply_mode: Mapped[ReplyMode] = mapped_column(
        SAEnum(ReplyMode, native_enum=False, length=8),
        default=ReplyMode.text,
        server_default="text",
        nullable=False,
    )


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
    # Когда задача перешла в done (автоматически после отправки разового
    # напоминания или вручную кнопкой «Выполнено») — используется, чтобы показать
    # недавно выполненные в /tasks (Фаза 25). NULL для задач, ставших done ещё до
    # появления этого поля — они не попадут в список "недавно выполненных" за
    # отсутствием даты, это ожидаемо, не баг.
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Note(Base):
    __tablename__ = "notes"
    __table_args__ = (
        Index(
            "ix_notes_embedding_cosine",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    content: Mapped[str] = mapped_column(EncryptedString, nullable=False)
    context: Mapped[Context] = mapped_column(SAEnum(Context, native_enum=False, length=16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Фаза 27 — семантическая память. В отличие от content, НЕ зашифровано Fernet:
    # поиск по смыслу (ближайшие по косинусному расстоянию) должен считаться прямо
    # в Postgres через pgvector, а Fernet-шифрование недетерминировано и уничтожило
    # бы саму структуру вектора, по которой считается расстояние — encrypted-at-rest
    # для векторов тут технически невозможно при сохранении векторного поиска.
    # NULL — либо запись создана до этой миграции (не бэкфиллено), либо вычисление
    # эмбеддинга не удалось (сетевая ошибка) — в обоих случаях запись просто не
    # участвует в семантическом поиске, но не теряется и остаётся в окне Фазы 19.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)


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


class EmailLog(Base):
    """Лог отправленных писем — не адресная книга: получатель не переиспользуется
    для поиска (та же причина, что и у остальных EncryptedString-полей — Fernet не
    детерминирован, WHERE по значению не сработает), каждый раз email указывается
    заново в самом запросе. Хранится только как история/аудит для пользователя.
    """

    __tablename__ = "email_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    recipient_email: Mapped[str] = mapped_column(EncryptedString, nullable=False)
    subject: Mapped[str] = mapped_column(EncryptedString, nullable=False)
    body: Mapped[str] = mapped_column(EncryptedString, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
