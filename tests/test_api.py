from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus_ai.main import app, handle_unexpected_exception


client = TestClient(app)


def test_root_returns_welcome_message() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "message": "Welcome to Nexus AI Workspace"
    }


def test_health_returns_expected_response() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_schema_is_available() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200

    schema = response.json()
    assert "/health" in schema["paths"]
    assert "/" in schema["paths"]


def test_unexpected_exception_returns_generic_error() -> None:
    test_app = FastAPI()
    test_app.add_exception_handler(
        Exception,
        handle_unexpected_exception,
    )

    @test_app.get("/trigger-error")
    def trigger_error() -> None:
        raise RuntimeError("sensitive internal detail")

    test_client = TestClient(
        test_app,
        raise_server_exceptions=False,
    )

    response = test_client.get("/trigger-error")

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Internal server error"
    }
    assert "sensitive internal detail" not in response.text


def test_unexpected_exception_handler_is_registered() -> None:
    assert (
        app.exception_handlers[Exception]
        is handle_unexpected_exception
    )
