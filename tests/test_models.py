import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from db.models import Base, Context, Note, Task, TaskStatus, User


@pytest.fixture()
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine)()
    engine.dispose()


def test_task_title_is_encrypted_at_rest(session):
    user = User(telegram_id=42)
    session.add(user)
    session.flush()

    task = Task(user_id=user.id, title="написать отчёт для клиента", context=Context.work)
    session.add(task)
    session.commit()

    raw_value = session.connection().exec_driver_sql(
        "select title from tasks where id = ?", (task.id,)
    ).scalar_one()
    assert raw_value != "написать отчёт для клиента"

    session.expire_all()
    reloaded = session.get(Task, task.id)
    assert reloaded.title == "написать отчёт для клиента"
    assert reloaded.status == TaskStatus.active


def test_note_content_roundtrip(session):
    user = User(telegram_id=7)
    session.add(user)
    session.flush()

    note = Note(user_id=user.id, content="идея для подарка", context=Context.personal)
    session.add(note)
    session.commit()
    session.expire_all()

    reloaded = session.get(Note, note.id)
    assert reloaded.content == "идея для подарка"
    assert reloaded.context == Context.personal
