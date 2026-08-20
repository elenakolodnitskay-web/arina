from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import Base, Context, EmailLog, Note, Task, Transaction, User
from scripts.retention_report import classify_retention, last_activity_at

NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)


@pytest.fixture()
def db_session_factory():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    yield factory
    engine.dispose()


@pytest.fixture()
def user_id(db_session_factory):
    with db_session_factory() as session:
        user = User(telegram_id=111)
        session.add(user)
        session.commit()
        return user.id


def test_last_activity_at_returns_none_without_any_records(db_session_factory, user_id):
    with db_session_factory() as session:
        assert last_activity_at(session, user_id) is None


def test_last_activity_at_counts_transaction_activity(db_session_factory, user_id):
    # Пользователь, который только фиксирует траты — раньше (до Фазы 22) не
    # учитывался как активный вовсе, потому что last_activity_at смотрел только
    # на Note/Task.
    with db_session_factory() as session:
        session.add(Transaction(user_id=user_id, amount=500, transaction_type="expense"))
        session.commit()

    with db_session_factory() as session:
        assert last_activity_at(session, user_id) is not None


def test_last_activity_at_counts_email_log_activity(db_session_factory, user_id):
    with db_session_factory() as session:
        session.add(
            EmailLog(user_id=user_id, recipient_email="a@b.com", subject="тема", body="текст")
        )
        session.commit()

    with db_session_factory() as session:
        assert last_activity_at(session, user_id) is not None


def test_last_activity_at_picks_the_most_recent_across_all_sources(db_session_factory, user_id):
    with db_session_factory() as session:
        session.add(Note(user_id=user_id, content="старое", context=Context.work))
        session.commit()
        note = session.query(Note).one()
        note.created_at = NOW - timedelta(days=10)
        session.add(Transaction(user_id=user_id, amount=100, transaction_type="income"))
        session.commit()
        transaction = session.query(Transaction).one()
        transaction.created_at = NOW - timedelta(days=1)
        session.commit()

    with db_session_factory() as session:
        result = last_activity_at(session, user_id)
        # SQLite не хранит tzinfo — сравниваем наивные значения.
        assert result == (NOW - timedelta(days=1)).replace(tzinfo=None)


def test_too_early_to_tell():
    cohort_start = NOW - timedelta(days=3)
    assert classify_retention(cohort_start, None, NOW, weeks=1) == "рано"


def test_no_activity_after_window_is_churned():
    cohort_start = NOW - timedelta(weeks=2)
    assert classify_retention(cohort_start, None, NOW, weeks=1) == "нет"


def test_activity_within_first_week_does_not_count_as_week_1_retention():
    cohort_start = NOW - timedelta(weeks=2)
    last_active = cohort_start + timedelta(days=2)
    assert classify_retention(cohort_start, last_active, NOW, weeks=1) == "нет"


def test_activity_after_threshold_counts_as_retained():
    cohort_start = NOW - timedelta(weeks=2)
    last_active = cohort_start + timedelta(days=10)
    assert classify_retention(cohort_start, last_active, NOW, weeks=1) == "да"
