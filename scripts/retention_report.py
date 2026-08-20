"""Отчёт по retention закрытой беты (Фаза 9) — запускать вручную, не автоматизировано.

Активностью пользователя считается создание Task/Note/Transaction/EmailLog (не сам
факт /start — он даёт только onboarding_completed=True). Пересылка сообщений другому
пользователю (Фаза 17) не создаёт постоянной записи в БД по дизайну — не учитывается
здесь, как и раньше не учитывался сам факт входа в чат. N-недельный retention здесь —
упрощённая метрика "была ли активность не раньше, чем через N недель после первого
использования", не скользящее окно.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func

from db.models import EmailLog, Note, Task, Transaction, User
from db.session import SessionLocal


def classify_retention(cohort_start: datetime, last_active: datetime | None, now: datetime, weeks: int) -> str:
    threshold = timedelta(weeks=weeks)
    if now - cohort_start < threshold:
        return "рано"
    if last_active is None:
        return "нет"
    return "да" if last_active - cohort_start >= threshold else "нет"


def last_activity_at(session, user_id: int) -> datetime | None:
    timestamps = [
        session.query(func.max(model.created_at)).filter_by(user_id=user_id).scalar()
        for model in (Note, Task, Transaction, EmailLog)
    ]
    timestamps = [ts for ts in timestamps if ts is not None]
    return max(timestamps) if timestamps else None


def main() -> None:
    now = datetime.now(timezone.utc)
    with SessionLocal() as session:
        users = session.query(User).filter_by(onboarding_completed=True).order_by(User.created_at).all()

        header = f"{'telegram_id':<15}{'дней в бете':<14}{'посл. активность':<22}{'1нед':<8}{'2нед':<8}{'4нед':<8}"
        print(header)
        for user in users:
            last_active = last_activity_at(session, user.id)
            days_in_beta = (now - user.created_at).days
            last_active_str = last_active.date().isoformat() if last_active else "—"

            row = (
                f"{user.telegram_id:<15}{days_in_beta:<14}{last_active_str:<22}"
                f"{classify_retention(user.created_at, last_active, now, 1):<8}"
                f"{classify_retention(user.created_at, last_active, now, 2):<8}"
                f"{classify_retention(user.created_at, last_active, now, 4):<8}"
            )
            print(row)


if __name__ == "__main__":
    main()
