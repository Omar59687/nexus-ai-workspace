
from fastapi.testclient import TestClient

from nexus_ai.database import SessionLocal
from nexus_ai.main import app
from nexus_ai.models import WorkspaceTask


client = TestClient(app)


def test_task_api_crud_lifecycle() -> None:
    task_id: int | None = None

    try:
        # Create
        create_response = client.post(
            "/tasks",
            json={"title": "  API integration test  "},
        )
        assert create_response.status_code == 201

        created = create_response.json()
        task_id = created["id"]

        assert created["title"] == "API integration test"
        assert created["status"] == "pending"
        assert created["created_at"] is not None

        # Read one task
        read_response = client.get(f"/tasks/{task_id}")
        assert read_response.status_code == 200
        assert read_response.json()["title"] == "API integration test"

        # Read task list
        list_response = client.get("/tasks")
        assert list_response.status_code == 200
        assert any(task["id"] == task_id for task in list_response.json())

        # Update
        update_response = client.patch(
            f"/tasks/{task_id}",
            json={"status": "completed"},
        )
        assert update_response.status_code == 200
        assert update_response.json()["status"] == "completed"

        # Delete
        delete_response = client.delete(f"/tasks/{task_id}")
        assert delete_response.status_code == 204

        # Verify deletion
        missing_response = client.get(f"/tasks/{task_id}")
        assert missing_response.status_code == 404

        task_id = None

    finally:
        # Remove the test record if an earlier assertion failed.
        if task_id is not None:
            with SessionLocal() as session:
                task = session.get(WorkspaceTask, task_id)
                if task is not None:
                    session.delete(task)
                    session.commit()


def test_create_task_rejects_blank_title() -> None:
    response = client.post("/tasks", json={"title": "   "})

    assert response.status_code == 422


def test_update_task_rejects_invalid_status() -> None:
    response = client.patch(
        "/tasks/2147483647",
        json={"status": "unknown"},
    )

    assert response.status_code == 422


def test_task_api_returns_404_for_missing_task() -> None:
    response = client.get("/tasks/2147483647")

    assert response.status_code == 404
    assert response.json()["detail"] == "Task not found"
