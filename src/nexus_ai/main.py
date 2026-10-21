
import logging

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_ai.database import get_db
from nexus_ai.models import WorkspaceTask
from nexus_ai.ollama import (
    OllamaClient,
    OllamaResponseError,
    OllamaTimeoutError,
    OllamaUnavailableError,
)
from nexus_ai.schemas import (
    LLMGenerateRequest,
    LLMGenerateResponse,
    TaskCreate,
    TaskRead,
    TaskUpdate,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("nexus_ai")


class HealthResponse(BaseModel):
    status: str


app = FastAPI(
    title="Nexus AI Workspace",
    description="A local-first multi-agent AI workspace.",
    version="0.1.0",
)


@app.exception_handler(Exception)
async def handle_unexpected_exception(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    logger.exception(
        "Unhandled exception while processing %s %s",
        request.method,
        request.url.path,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


@app.get("/")
def read_root() -> dict[str, str]:
    return {"message": "Welcome to Nexus AI Workspace"}


@app.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    return HealthResponse(status="ok")


def get_ollama_client() -> OllamaClient:
    return OllamaClient()


@app.post("/llm/generate", response_model=LLMGenerateResponse)
def generate_llm(
    payload: LLMGenerateRequest,
    client: OllamaClient = Depends(get_ollama_client),
) -> LLMGenerateResponse:
    try:
        return client.generate(
            prompt=payload.prompt,
            model=payload.model,
        )
    except OllamaTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ollama request timed out",
        ) from exc
    except OllamaUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ollama service is unavailable",
        ) from exc
    except OllamaResponseError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Ollama returned an invalid response",
        ) from exc


@app.post(
    "/tasks",
    response_model=TaskRead,
    status_code=status.HTTP_201_CREATED,
)
def create_task(
    task_data: TaskCreate,
    db: Session = Depends(get_db),
) -> WorkspaceTask:
    task = WorkspaceTask(title=task_data.title)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@app.get("/tasks", response_model=list[TaskRead])
def list_tasks(
    db: Session = Depends(get_db),
) -> list[WorkspaceTask]:
    statement = select(WorkspaceTask).order_by(WorkspaceTask.id)
    return list(db.scalars(statement).all())


@app.get("/tasks/{task_id}", response_model=TaskRead)
def get_task(
    task_id: int,
    db: Session = Depends(get_db),
) -> WorkspaceTask:
    task = db.get(WorkspaceTask, task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )
    return task


@app.patch("/tasks/{task_id}", response_model=TaskRead)
def update_task(
    task_id: int,
    updates: TaskUpdate,
    db: Session = Depends(get_db),
) -> WorkspaceTask:
    task = db.get(WorkspaceTask, task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )

    changes = updates.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one field must be provided",
        )

    if "title" in changes:
        title = changes["title"]
        if title is None or not title.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Title cannot be blank or null",
            )
        changes["title"] = title.strip()

    if "status" in changes and changes["status"] is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Status cannot be null",
        )

    for field, value in changes.items():
        setattr(task, field, value)

    db.commit()
    db.refresh(task)
    return task


@app.delete(
    "/tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_task(
    task_id: int,
    db: Session = Depends(get_db),
) -> Response:
    task = db.get(WorkspaceTask, task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )

    db.delete(task)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
