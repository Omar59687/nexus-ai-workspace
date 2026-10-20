
from uuid import uuid4

from nexus_ai.database import SessionLocal
from nexus_ai.models import WorkspaceTask


def test_workspace_task_crud_lifecycle() -> None:
    session = SessionLocal()
    task_id: int | None = None

    try:
        # CREATE: add a new task.
        task = WorkspaceTask(title=f"CRUD test {uuid4()}")
        session.add(task)
        session.commit()
        session.refresh(task)

        task_id = task.id

        assert task.id is not None
        assert task.status == "pending"
        assert task.created_at is not None

        # READ: retrieve the persisted task.
        saved_task = session.get(WorkspaceTask, task_id)

        assert saved_task is not None
        assert saved_task.title == task.title
        assert saved_task.status == "pending"

        # UPDATE: change the task status.
        saved_task.status = "completed"
        session.commit()
        session.refresh(saved_task)

        assert saved_task.status == "completed"

        # DELETE: remove the task.
        session.delete(saved_task)
        session.commit()

        assert session.get(WorkspaceTask, task_id) is None

    finally:
        # Clean up the test record even if an assertion fails.
        session.rollback()

        if task_id is not None:
            remaining_task = session.get(WorkspaceTask, task_id)
            if remaining_task is not None:
                session.delete(remaining_task)
                session.commit()

        session.close()
