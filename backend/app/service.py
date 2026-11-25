"""Правила журнала ключей: каталог, экземпляры, сотрудники, выдача, возврат, просрочки, история.

Доступность — экземпляр без активной выдачи и не списан. Просрочка вычисляется при чтении:
now() строго позже due_at. Возврат фиксирует фактическое время, повторный возврат его не меняет.
Каждое изменение — одна транзакция BEGIN IMMEDIATE, событие журнала пишется в ней же.
"""
from __future__ import annotations

import csv
import io
import sqlite3
from datetime import UTC, datetime

from .db import write_tx
from .errors import BadRequest, Conflict, NotFound

KINDS = {
    "issue": "выдача",
    "return": "возврат",
    "key_create": "новый ключ",
    "copy_add": "новый экземпляр",
    "copy_retire": "экземпляр списан",
    "copy_restore": "экземпляр возвращён в работу",
    "staff_create": "новый сотрудник",
}
MAX_PAGE = 500


def now() -> datetime:
    """Текущее время. Тесты подменяют эту функцию, чтобы проверить точную границу срока."""
    return datetime.now(UTC).replace(microsecond=0)


def iso(d: datetime) -> str:
    return d.astimezone(UTC).isoformat(timespec="seconds")


def parse_dt(s: str) -> datetime:
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BadRequest("bad_datetime", "Неверная дата и время", field="due_at") from exc
    if d.tzinfo is None:
        raise BadRequest("bad_datetime", "Укажите время с часовым поясом", field="due_at")
    return d.astimezone(UTC).replace(microsecond=0)


def skey(*parts: str) -> str:
    """Ключ поиска в Python: lower() SQLite не меняет регистр кириллицы."""
    return " ".join(" ".join(parts).lower().replace("ё", "е").split())


def is_overdue(due_at: str, at: datetime | None = None) -> bool:
    return (at or now()) > datetime.fromisoformat(due_at)


def _event(conn: sqlite3.Connection, actor: int | None, kind: str, *, key_id=None, copy_id=None, loan_id=None, staff_id=None, details: str = "", at: str | None = None) -> None:
    conn.execute(
        "INSERT INTO events (at, actor_id, kind, key_id, copy_id, loan_id, staff_id, details) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (at or iso(now()), actor, kind, key_id, copy_id, loan_id, staff_id, details),
    )


# ---------- каталог ----------

LOAN_SQL = """
SELECT l.id, l.copy_id, l.staff_id, l.issued_at, l.due_at, l.returned_at,
       s.name AS staff, s.department, k.id AS key_id, k.label, k.room, c.copy_no,
       ui.display_name AS issued_by, ur.display_name AS returned_by
FROM loans l JOIN staff s ON s.id = l.staff_id JOIN key_copies c ON c.id = l.copy_id JOIN keys k ON k.id = c.key_id
JOIN users ui ON ui.id = l.issued_by LEFT JOIN users ur ON ur.id = l.returned_by
"""


def _loan_json(r: sqlite3.Row, at: datetime) -> dict[str, object]:
    d = dict(r)
    d["overdue"] = r["returned_at"] is None and is_overdue(r["due_at"], at)
    return d


def list_keys(conn: sqlite3.Connection, q: str = "", available: bool = False, limit: int = 50, offset: int = 0, brief: bool = False) -> dict[str, object]:
    """Страница ключей по метке. Доступность и фильтр «только доступные» считаются в SQL,
    экземпляры и активные выдачи подтягиваются только для ключей страницы (раунд 4: на 2 000 ключей
    полный список с экземплярами отдавался целиком и интерфейс рисовал 2 000 карточек)."""
    at = now()
    words = skey(q).split()
    where: list[str] = ["k.search_key LIKE ?" for _ in words]
    args: list[object] = [f"%{w}%" for w in words]
    if available:
        where.append(
            "EXISTS (SELECT 1 FROM key_copies c WHERE c.key_id = k.id AND c.retired_at IS NULL"
            " AND NOT EXISTS (SELECT 1 FROM loans l WHERE l.copy_id = c.id AND l.returned_at IS NULL))"
        )
    w = (" WHERE " + " AND ".join(where)) if where else ""
    total = conn.execute(f"SELECT COUNT(*) FROM keys k{w}", args).fetchone()[0]
    keys = [dict(r) for r in conn.execute(f"SELECT k.id, k.label, k.room, k.note FROM keys k{w} ORDER BY k.label LIMIT ? OFFSET ?", (*args, min(limit, 5000), offset))]
    if brief or not keys:
        return {"total": total, "keys": keys}
    ids = [k["id"] for k in keys]
    marks = ",".join("?" * len(ids))
    copies: dict[int, list[dict[str, object]]] = {}
    for c in conn.execute(f"SELECT id, key_id, copy_no, retired_at FROM key_copies WHERE key_id IN ({marks}) ORDER BY copy_no", ids):
        copies.setdefault(c["key_id"], []).append({"id": c["id"], "copy_no": c["copy_no"], "retired": c["retired_at"] is not None, "loan": None})
    active = {r["copy_id"]: _loan_json(r, at) for r in conn.execute(LOAN_SQL + f" WHERE l.returned_at IS NULL AND c.key_id IN ({marks})", ids)}
    for k in keys:
        cs = copies.get(k["id"], [])
        for c in cs:
            c["loan"] = active.get(c["id"])
        k["copies"] = cs
        k["available"] = sum(1 for c in cs if not c["retired"] and c["loan"] is None)
        k["overdue"] = sum(1 for c in cs if c["loan"] and c["loan"]["overdue"])
    return {"total": total, "keys": keys}


def key_card(conn: sqlite3.Connection, key_id: int) -> dict[str, object]:
    label = conn.execute("SELECT label FROM keys WHERE id = ?", (key_id,)).fetchone()
    if label is None:
        raise NotFound("not_found", "Ключ не найден")
    return next(k for k in list_keys(conn, label["label"], limit=5000)["keys"] if k["id"] == key_id)


def create_key(conn: sqlite3.Connection, actor: int, label: str, room: str, note: str, copies: int) -> int:
    with write_tx(conn):
        if conn.execute("SELECT 1 FROM keys WHERE label = ?", (label,)).fetchone():
            raise Conflict("label_taken", f"Метка «{label}» уже есть", field="label")
        kid = conn.execute(
            "INSERT INTO keys (label, room, note, search_key, created_at) VALUES (?, ?, ?, ?, ?) RETURNING id",
            (label, room, note, skey(label, room, note), iso(now())),
        ).fetchone()["id"]
        _event(conn, actor, "key_create", key_id=kid, details=f"{label} · {room}")
        for n in range(1, copies + 1):
            cid = conn.execute("INSERT INTO key_copies (key_id, copy_no) VALUES (?, ?) RETURNING id", (kid, n)).fetchone()["id"]
            _event(conn, actor, "copy_add", key_id=kid, copy_id=cid, details=f"{label} №{n}")
        return int(kid)


def add_copy(conn: sqlite3.Connection, actor: int, key_id: int) -> int:
    with write_tx(conn):
        k = conn.execute("SELECT label FROM keys WHERE id = ?", (key_id,)).fetchone()
        if k is None:
            raise NotFound("not_found", "Ключ не найден")
        n = conn.execute("SELECT COALESCE(MAX(copy_no), 0) + 1 FROM key_copies WHERE key_id = ?", (key_id,)).fetchone()[0]
        cid = conn.execute("INSERT INTO key_copies (key_id, copy_no) VALUES (?, ?) RETURNING id", (key_id, n)).fetchone()["id"]
        _event(conn, actor, "copy_add", key_id=key_id, copy_id=cid, details=f"{k['label']} №{n}")
        return int(cid)


def set_retired(conn: sqlite3.Connection, actor: int, copy_id: int, retired: bool) -> bool:
    with write_tx(conn):
        c = conn.execute("SELECT c.*, k.label FROM key_copies c JOIN keys k ON k.id = c.key_id WHERE c.id = ?", (copy_id,)).fetchone()
        if c is None:
            raise NotFound("not_found", "Экземпляр не найден")
        if (c["retired_at"] is not None) == retired:
            return False
        if retired and conn.execute("SELECT 1 FROM loans WHERE copy_id = ? AND returned_at IS NULL", (copy_id,)).fetchone():
            raise Conflict("copy_on_loan", "Экземпляр выдан: сначала примите возврат")
        conn.execute("UPDATE key_copies SET retired_at = ? WHERE id = ?", (iso(now()) if retired else None, copy_id))
        _event(conn, actor, "copy_retire" if retired else "copy_restore", key_id=c["key_id"], copy_id=copy_id, details=f"{c['label']} №{c['copy_no']}")
        return True


def list_staff(conn: sqlite3.Connection, q: str = "") -> list[dict[str, object]]:
    words = skey(q).split()
    sql = "SELECT id, name, department FROM staff WHERE active = 1"
    args = [f"%{w}%" for w in words]
    for _ in words:
        sql += " AND search_key LIKE ?"
    return [dict(r) for r in conn.execute(sql + " ORDER BY name", args)]


def create_staff(conn: sqlite3.Connection, actor: int, name: str, department: str) -> int:
    with write_tx(conn):
        sid = conn.execute("INSERT INTO staff (name, department, search_key) VALUES (?, ?, ?) RETURNING id", (name, department, skey(name, department))).fetchone()["id"]
        _event(conn, actor, "staff_create", staff_id=sid, details=f"{name} · {department}")
        return int(sid)


# ---------- выдача и возврат ----------

def loan(conn: sqlite3.Connection, loan_id: int) -> dict[str, object]:
    r = conn.execute(LOAN_SQL + " WHERE l.id = ?", (loan_id,)).fetchone()
    if r is None:
        raise NotFound("not_found", "Выдача не найдена")
    return _loan_json(r, now())


def issue(conn: sqlite3.Connection, actor: int, copy_id: int, staff_id: int, due_at: str) -> tuple[dict[str, object], bool]:
    """Выдача. Повтор тому же сотруднику, пока ключ у него, возвращает ту же выдачу (created=False)."""
    due = parse_dt(due_at)
    with write_tx(conn):
        c = conn.execute("SELECT c.*, k.label FROM key_copies c JOIN keys k ON k.id = c.key_id WHERE c.id = ?", (copy_id,)).fetchone()
        if c is None:
            raise NotFound("not_found", "Экземпляр не найден")
        s = conn.execute("SELECT id, name FROM staff WHERE id = ? AND active = 1", (staff_id,)).fetchone()
        if s is None:
            raise BadRequest("bad_staff", "Выберите сотрудника", field="staff_id")
        if c["retired_at"] is not None:
            raise Conflict("copy_retired", f"{c['label']} №{c['copy_no']} списан")
        cur = conn.execute("SELECT id, staff_id FROM loans WHERE copy_id = ? AND returned_at IS NULL", (copy_id,)).fetchone()
        if cur is not None:
            if cur["staff_id"] == staff_id:
                return loan(conn, cur["id"]), False
            holder = loan(conn, cur["id"])
            raise Conflict("copy_taken", f"{c['label']} №{c['copy_no']} уже выдан: {holder['staff']}, срок {holder['due_at']}", loan=holder)
        at = iso(now())
        try:
            lid = conn.execute(
                "INSERT INTO loans (copy_id, staff_id, issued_at, issued_by, due_at) VALUES (?, ?, ?, ?, ?) RETURNING id",
                (copy_id, staff_id, at, actor, iso(due)),
            ).fetchone()["id"]
        except sqlite3.IntegrityError as exc:  # вторая линия защиты: loans_one_active_per_copy
            raise Conflict("copy_taken", f"{c['label']} №{c['copy_no']} уже выдан") from exc
        _event(conn, actor, "issue", key_id=c["key_id"], copy_id=copy_id, loan_id=lid, staff_id=staff_id, details=f"{c['label']} №{c['copy_no']} → {s['name']}, срок {iso(due)}", at=at)
        return loan(conn, lid), True


def return_loan(conn: sqlite3.Connection, actor: int, loan_id: int) -> tuple[dict[str, object], bool]:
    """Возврат. Повторный вызов оставляет исходное время закрытия и не пишет событие."""
    with write_tx(conn):
        r = conn.execute("SELECT l.*, c.key_id, c.copy_no, k.label, s.name FROM loans l JOIN key_copies c ON c.id = l.copy_id JOIN keys k ON k.id = c.key_id JOIN staff s ON s.id = l.staff_id WHERE l.id = ?", (loan_id,)).fetchone()
        if r is None:
            raise NotFound("not_found", "Выдача не найдена")
        if r["returned_at"] is not None:
            return loan(conn, loan_id), False
        at = iso(now())
        conn.execute("UPDATE loans SET returned_at = ?, returned_by = ? WHERE id = ? AND returned_at IS NULL", (at, actor, loan_id))
        _event(conn, actor, "return", key_id=r["key_id"], copy_id=r["copy_id"], loan_id=loan_id, staff_id=r["staff_id"], details=f"{r['label']} №{r['copy_no']} ← {r['name']}", at=at)
        return loan(conn, loan_id), True


def list_loans(conn: sqlite3.Connection, status: str, key_id: int | None = None, staff_id: int | None = None) -> list[dict[str, object]]:
    at = now()
    where, args = [], []
    if status in ("active", "overdue"):
        where.append("l.returned_at IS NULL")
    elif status == "returned":
        where.append("l.returned_at IS NOT NULL")
    if status == "overdue":
        where.append("l.due_at < ?")  # строго позже срока
        args.append(iso(at))
    if key_id:
        where.append("c.key_id = ?")
        args.append(key_id)
    if staff_id:
        where.append("l.staff_id = ?")
        args.append(staff_id)
    order = " ORDER BY l.due_at, l.id" if status in ("active", "overdue") else " ORDER BY l.issued_at DESC, l.id DESC"
    sql = LOAN_SQL + (" WHERE " + " AND ".join(where) if where else "") + order + f" LIMIT {MAX_PAGE}"
    return [_loan_json(r, at) for r in conn.execute(sql, args)]


# ---------- история ----------

def _events_where(key_id: int | None, kind: str | None, date_from: str | None, date_to: str | None) -> tuple[str, list[object]]:
    where, args = [], []
    if key_id:
        where.append("e.key_id = ?")
        args.append(key_id)
    if kind:
        if kind not in KINDS:
            raise BadRequest("bad_kind", "Неизвестный тип операции", field="kind")
        where.append("e.kind = ?")
        args.append(kind)
    if date_from:
        where.append("e.at >= ?")
        args.append(iso(parse_dt(date_from)))
    if date_to:
        where.append("e.at < ?")
        args.append(iso(parse_dt(date_to)))
    return (" WHERE " + " AND ".join(where) if where else ""), args


EVENTS_SQL = """SELECT e.id, e.at, e.kind, e.details, e.loan_id, k.label, k.room, c.copy_no, s.name AS staff, u.display_name AS actor
FROM events e LEFT JOIN keys k ON k.id = e.key_id LEFT JOIN key_copies c ON c.id = e.copy_id
LEFT JOIN staff s ON s.id = e.staff_id LEFT JOIN users u ON u.id = e.actor_id"""


def list_events(conn: sqlite3.Connection, key_id=None, kind=None, date_from=None, date_to=None, limit: int = 100, offset: int = 0) -> dict[str, object]:
    w, args = _events_where(key_id, kind, date_from, date_to)
    total = conn.execute(f"SELECT COUNT(*) FROM events e{w}", args).fetchone()[0]
    rows = [dict(r) for r in conn.execute(EVENTS_SQL + w + " ORDER BY e.at DESC, e.id DESC LIMIT ? OFFSET ?", (*args, min(limit, MAX_PAGE), offset))]
    for r in rows:
        r["kind_text"] = KINDS[r["kind"]]
    return {"total": total, "events": rows}


def events_csv(conn: sqlite3.Connection, key_id=None, kind=None, date_from=None, date_to=None) -> str:
    """CSV журнала для Excel: разделитель «;», BOM, время UTC в ISO 8601."""
    w, args = _events_where(key_id, kind, date_from, date_to)
    buf = io.StringIO()
    out = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    out.writerow(["Время (UTC)", "Операция", "Ключ", "Помещение", "Экземпляр", "Сотрудник", "Дежурный", "Подробности"])
    for r in conn.execute(EVENTS_SQL + w + " ORDER BY e.at, e.id", args):
        cells = [r["at"], KINDS[r["kind"]], r["label"] or "", r["room"] or "", r["copy_no"] or "", r["staff"] or "", r["actor"] or "", r["details"]]
        # Защита от формул в Excel: ячейка, начинающаяся с = + - @, экранируется апострофом.
        out.writerow([("'" + c) if isinstance(c, str) and c[:1] in ("=", "+", "-", "@") else c for c in cells])
    return "﻿" + buf.getvalue()
