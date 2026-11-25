"""HTTP API журнала ключей и раздача собранного интерфейса."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import FastAPI, Query, Response
from pydantic import BaseModel, Field, field_validator

from . import service, web
from .db import connect, migrate
from .web import Conn, CurrentUser, require_role

DUTY = ("duty", "admin")


@asynccontextmanager
async def lifespan(_: FastAPI):
    conn = connect()
    try:
        migrate(conn)
        if web.env_flag("SEED_DEMO"):
            from .seed import seed

            seed(conn)
    finally:
        conn.close()
    yield


app = FastAPI(title="Журнал выдачи ключей", version="1.0.0", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
web.install(app)


def _clean(v: str) -> str:
    return " ".join(v.split())


class KeyIn(BaseModel):
    label: str = Field(min_length=1, max_length=40)
    room: str = Field(min_length=1, max_length=120)
    note: str = Field(default="", max_length=300)
    copies: int = Field(default=1, ge=1, le=20)

    @field_validator("label", "room", "note")
    @classmethod
    def clean(cls, v: str) -> str:
        return _clean(v)

    @field_validator("label", "room")
    @classmethod
    def required(cls, v: str) -> str:
        if not v:
            raise ValueError("Заполните поле")
        return v


class CopyPatch(BaseModel):
    retired: bool


class StaffIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    department: str = Field(default="", max_length=120)

    @field_validator("name", "department")
    @classmethod
    def clean(cls, v: str) -> str:
        return _clean(v)

    @field_validator("name")
    @classmethod
    def required(cls, v: str) -> str:
        if not v:
            raise ValueError("Введите имя")
        return v


class LoanIn(BaseModel):
    copy_id: int
    staff_id: int
    due_at: str = Field(description="Плановый срок возврата, ISO 8601 с часовым поясом")


@app.get("/api/keys")
def keys(
    conn: Conn,
    user: CurrentUser,
    q: str = "",
    available: bool = False,
    limit: Annotated[int, Query(ge=1, le=5000)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    brief: bool = False,
) -> dict[str, object]:
    """Страница ключей. brief=true — только id, метка и помещение (для списка в фильтре истории)."""
    require_role(user, *DUTY)
    return service.list_keys(conn, q, available, limit, offset, brief)


@app.post("/api/keys", status_code=201)
def create_key(body: KeyIn, conn: Conn, user: CurrentUser) -> dict[str, object]:
    require_role(user, "admin", message="Регистрировать ключи может администратор")
    kid = service.create_key(conn, user.id, body.label, body.room, body.note, body.copies)
    return {"key": service.key_card(conn, kid)}


@app.post("/api/keys/{key_id}/copies", status_code=201)
def add_copy(key_id: int, conn: Conn, user: CurrentUser) -> dict[str, object]:
    require_role(user, "admin", message="Добавлять экземпляры может администратор")
    service.add_copy(conn, user.id, key_id)
    return {"key": service.key_card(conn, key_id)}


@app.patch("/api/copies/{copy_id}")
def patch_copy(copy_id: int, body: CopyPatch, conn: Conn, user: CurrentUser) -> dict[str, object]:
    require_role(user, "admin", message="Списывать экземпляры может администратор")
    return {"changed": service.set_retired(conn, user.id, copy_id, body.retired)}


@app.get("/api/staff")
def staff(conn: Conn, user: CurrentUser, q: str = "") -> dict[str, object]:
    require_role(user, *DUTY)
    return {"staff": service.list_staff(conn, q)}


@app.post("/api/staff", status_code=201)
def create_staff(body: StaffIn, conn: Conn, user: CurrentUser) -> dict[str, object]:
    require_role(user, "admin", message="Добавлять сотрудников может администратор")
    sid = service.create_staff(conn, user.id, body.name, body.department)
    return {"staff": next(s for s in service.list_staff(conn) if s["id"] == sid)}


@app.post("/api/key-loans", status_code=201)
def issue(body: LoanIn, conn: Conn, user: CurrentUser, response: Response) -> dict[str, object]:
    require_role(user, *DUTY, message="Выдавать ключи может дежурный")
    loan, created = service.issue(conn, user.id, body.copy_id, body.staff_id, body.due_at)
    if not created:
        response.status_code = 200
    return {"loan": loan, "created": created}


@app.post("/api/key-loans/{loan_id}/return")
def return_loan(loan_id: int, conn: Conn, user: CurrentUser) -> dict[str, object]:
    require_role(user, *DUTY, message="Принимать ключи может дежурный")
    loan, changed = service.return_loan(conn, user.id, loan_id)
    return {"loan": loan, "changed": changed}


@app.get("/api/key-loans")
def loans(
    conn: Conn,
    user: CurrentUser,
    status: Literal["active", "overdue", "returned", "all"] = "active",
    key_id: int | None = None,
    staff_id: int | None = None,
) -> dict[str, object]:
    require_role(user, *DUTY)
    return {"loans": service.list_loans(conn, status, key_id, staff_id), "now": service.iso(service.now())}


EventKind = Literal["issue", "return", "key_create", "copy_add", "copy_retire", "copy_restore", "staff_create"]


@app.get("/api/events")
def events(
    conn: Conn,
    user: CurrentUser,
    key_id: int | None = None,
    kind: EventKind | None = None,
    date_from: Annotated[str | None, Query(alias="from")] = None,
    date_to: Annotated[str | None, Query(alias="to")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    require_role(user, *DUTY)
    return service.list_events(conn, key_id, kind, date_from, date_to, limit, offset)


@app.get("/api/events.csv")
def events_csv(
    conn: Conn,
    user: CurrentUser,
    key_id: int | None = None,
    kind: EventKind | None = None,
    date_from: Annotated[str | None, Query(alias="from")] = None,
    date_to: Annotated[str | None, Query(alias="to")] = None,
) -> Response:
    require_role(user, *DUTY)
    body = service.events_csv(conn, key_id, kind, date_from, date_to)
    stamp = service.now().strftime("%Y%m%d-%H%M")
    return Response(body, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="zhurnal-klyuchey-{stamp}.csv"'})


web.mount_static(app)
