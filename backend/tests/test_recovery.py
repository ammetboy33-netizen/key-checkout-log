"""Перезапуск на той же базе, миграции, уникальный индекс активной выдачи."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import httpx
import pytest

from app.db import connect, latest_migration, migrate, schema_version
from app.seed import seed

from .conftest import free_port, http_login, start_server


def test_restart_keeps_loans_and_history(tmp_path: Path) -> None:
    db = tmp_path / "keep.sqlite3"
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    proc = start_server(db, port)
    try:
        h = http_login(base, "duty")
        k = next(k for k in httpx.get(f"{base}/api/keys", headers=h).json()["keys"] if k["label"] == "К-101")
        sid = httpx.get(f"{base}/api/staff", headers=h).json()["staff"][0]["id"]
        lid = httpx.post(f"{base}/api/key-loans", json={"copy_id": k["copies"][0]["id"], "staff_id": sid, "due_at": "2030-01-01T10:00:00Z"}, headers=h).json()["loan"]["id"]
    finally:
        proc.terminate()
        proc.wait(timeout=10)
    proc = start_server(db, port)
    try:
        h = http_login(base, "duty")
        assert lid in [x["id"] for x in httpx.get(f"{base}/api/key-loans", headers=h).json()["loans"]]
        assert len(httpx.get(f"{base}/api/keys", headers=h).json()["keys"]) == 6
        assert httpx.get(f"{base}/api/health").json()["schema_version"] == latest_migration()
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_migrate_idempotent(tmp_path: Path) -> None:
    conn = connect(str(tmp_path / "m.sqlite3"))
    try:
        assert migrate(conn) == latest_migration()
        assert migrate(conn) == latest_migration() == schema_version(conn)
    finally:
        conn.close()


def test_unique_active_loan_index(tmp_path: Path) -> None:
    conn = connect(str(tmp_path / "u.sqlite3"))
    try:
        seed(conn)
        cid = conn.execute("SELECT c.id FROM key_copies c JOIN keys k ON k.id = c.key_id WHERE k.label = 'К-202'").fetchone()[0]
        conn.execute("INSERT INTO loans (copy_id, staff_id, issued_at, issued_by, due_at) VALUES (?, 1, 'a', 1, 'b')", (cid,))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO loans (copy_id, staff_id, issued_at, issued_by, due_at) VALUES (?, 2, 'a', 1, 'b')", (cid,))
        conn.execute("UPDATE loans SET returned_at = 'c' WHERE copy_id = ?", (cid,))
        conn.execute("INSERT INTO loans (copy_id, staff_id, issued_at, issued_by, due_at) VALUES (?, 2, 'a', 1, 'b')", (cid,))
    finally:
        conn.close()
