"""API журнала ключей: роли, выдача, просрочка и её точная граница, возврат, история, экспорт."""
from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app import service

from .conftest import login


def _key(c: httpx.Client, h: dict[str, str], label: str) -> dict:
    return next(k for k in c.get("/api/keys", headers=h).json()["keys"] if k["label"] == label)


def _staff(c: httpx.Client, h: dict[str, str], name: str) -> int:
    return next(s["id"] for s in c.get("/api/staff", headers=h).json()["staff"] if s["name"] == name)


def _iso(d: datetime) -> str:
    return d.astimezone(UTC).isoformat(timespec="seconds")


def test_login_and_roles(client: httpx.Client) -> None:
    assert client.get("/api/keys").status_code == 401
    d = login(client, "duty")
    assert client.post("/api/keys", json={"label": "К-999", "room": "Тест"}, headers=d).status_code == 403
    assert client.post("/api/staff", json={"name": "Тест"}, headers=d).status_code == 403
    a = login(client, "admin")
    r = client.post("/api/keys", json={"label": " К-401 ", "room": "Кладовая  «Дуб»", "copies": 3}, headers=a)
    assert r.status_code == 201 and [c["copy_no"] for c in r.json()["key"]["copies"]] == [1, 2, 3]
    assert r.json()["key"]["room"] == "Кладовая «Дуб»"
    assert client.post("/api/keys", json={"label": "К-401", "room": "Дубль"}, headers=a).status_code == 409
    assert client.post("/api/keys", json={"label": "  ", "room": "X"}, headers=a).status_code == 422


def test_search_and_availability(client: httpx.Client) -> None:
    h = login(client, "duty")
    keys = client.get("/api/keys", headers=h).json()["keys"]
    assert [k["label"] for k in keys] == ["К-101", "К-102", "К-201", "К-202", "К-301", "К-302"]
    assert [k["label"] for k in client.get("/api/keys", params={"q": "СЕРВЕРНАЯ"}, headers=h).json()["keys"]] == ["К-201"]
    assert [k["label"] for k in client.get("/api/keys", params={"q": "клен"}, headers=h).json()["keys"]] == ["К-302"]  # ё/е
    free = [k["label"] for k in client.get("/api/keys", params={"available": True}, headers=h).json()["keys"]]
    assert "К-102" not in free and "К-201" in free  # у К-201 свободен второй экземпляр


def test_acceptance_expired_due_overdue_block_return(client: httpx.Client) -> None:
    """Приёмка ТЗ: выдача с истекшим сроком попадает в просроченные, повторная выдача экземпляра
    блокируется, после возврата активная выдача пропадает, история остаётся."""
    h = login(client, "duty")
    k = _key(client, h, "К-202")
    cid = k["copies"][0]["id"]
    anna = _staff(client, h, "Анна Белова")
    r = client.post("/api/key-loans", json={"copy_id": cid, "staff_id": anna, "due_at": _iso(datetime.now(UTC) - timedelta(minutes=5))}, headers=h)
    assert r.status_code == 201
    lid = r.json()["loan"]["id"]
    assert r.json()["loan"]["overdue"] is True
    overdue = client.get("/api/key-loans", params={"status": "overdue"}, headers=h).json()["loans"]
    assert {x["label"] for x in overdue} == {"К-102", "К-202"}
    # Другому сотруднику — 409 с текущей выдачей; тому же — та же выдача.
    boris = _staff(client, h, "Борис Орлов")
    r2 = client.post("/api/key-loans", json={"copy_id": cid, "staff_id": boris, "due_at": _iso(datetime.now(UTC) + timedelta(hours=1))}, headers=h)
    assert r2.status_code == 409 and r2.json()["code"] == "copy_taken" and r2.json()["loan"]["staff"] == "Анна Белова"
    r3 = client.post("/api/key-loans", json={"copy_id": cid, "staff_id": anna, "due_at": _iso(datetime.now(UTC))}, headers=h)
    assert r3.status_code == 200 and r3.json()["loan"]["id"] == lid
    # Возврат и повторный возврат: время закрытия не меняется, событие одно.
    first = client.post(f"/api/key-loans/{lid}/return", headers=h).json()
    assert first["changed"] is True
    again = client.post(f"/api/key-loans/{lid}/return", headers=login(client, "duty2")).json()
    assert again["changed"] is False and again["loan"]["returned_at"] == first["loan"]["returned_at"]
    assert again["loan"]["returned_by"] == "Сергей Ким"
    assert lid not in [x["id"] for x in client.get("/api/key-loans", params={"status": "active"}, headers=h).json()["loans"]]
    hist = client.get("/api/events", params={"key_id": k["id"]}, headers=h).json()["events"]
    assert [e["kind"] for e in hist if e["loan_id"] == lid] == ["return", "issue"]


def test_exact_due_boundary(client: httpx.Client, monkeypatch: pytest.MonkeyPatch) -> None:
    """Просрочка — строго позже срока: в момент срока ещё нет, через секунду — есть."""
    h = login(client, "duty")
    due = datetime(2030, 1, 15, 12, 0, 0, tzinfo=UTC)
    k = _key(client, h, "К-101")
    r = client.post("/api/key-loans", json={"copy_id": k["copies"][1]["id"], "staff_id": _staff(client, h, "Дарья Котова"), "due_at": "2030-01-15T15:00:00+03:00"}, headers=h)
    lid = r.json()["loan"]["id"]
    assert r.json()["loan"]["due_at"] == "2030-01-15T12:00:00+00:00"
    monkeypatch.setattr(service, "now", lambda: due)
    st = lambda: next(x for x in client.get("/api/key-loans", params={"status": "active"}, headers=h).json()["loans"] if x["id"] == lid)["overdue"]  # noqa: E731
    ids = lambda: [x["id"] for x in client.get("/api/key-loans", params={"status": "overdue"}, headers=h).json()["loans"]]  # noqa: E731
    assert st() is False and lid not in ids()
    monkeypatch.setattr(service, "now", lambda: due + timedelta(seconds=1))
    assert st() is True and lid in ids()


def test_two_copies_of_one_key(client: httpx.Client) -> None:
    h = login(client, "duty")
    k = _key(client, h, "К-302")
    due = _iso(datetime.now(UTC) + timedelta(hours=2))
    a, b = _staff(client, h, "Анна Белова"), _staff(client, h, "Борис Орлов")
    assert client.post("/api/key-loans", json={"copy_id": k["copies"][0]["id"], "staff_id": a, "due_at": due}, headers=h).status_code == 201
    assert client.post("/api/key-loans", json={"copy_id": k["copies"][1]["id"], "staff_id": b, "due_at": due}, headers=h).status_code == 201
    k2 = _key(client, h, "К-302")
    assert k2["available"] == 0 and [c["loan"]["staff"] for c in k2["copies"]] == ["Анна Белова", "Борис Орлов"]
    assert "К-302" not in [x["label"] for x in client.get("/api/keys", params={"available": True}, headers=h).json()["keys"]]


def test_retire_rules_and_validation(client: httpx.Client) -> None:
    a = login(client, "admin")
    k = _key(client, a, "К-102")  # выдан
    assert client.patch(f"/api/copies/{k['copies'][0]['id']}", json={"retired": True}, headers=a).status_code == 409
    k = _key(client, a, "К-202")
    cid = k["copies"][0]["id"]
    assert client.patch(f"/api/copies/{cid}", json={"retired": True}, headers=a).json()["changed"] is True
    r = client.post("/api/key-loans", json={"copy_id": cid, "staff_id": _staff(client, a, "Анна Белова"), "due_at": "2030-01-01T10:00:00Z"}, headers=a)
    assert r.status_code == 409 and r.json()["code"] == "copy_retired"
    assert client.post("/api/key-loans", json={"copy_id": cid, "staff_id": 9999, "due_at": "2030-01-01T10:00:00Z"}, headers=a).json()["field"] == "staff_id"
    assert client.post("/api/key-loans", json={"copy_id": cid, "staff_id": 1, "due_at": "2030-01-01 10:00"}, headers=a).json()["field"] == "due_at"
    r = client.post(f"/api/keys/{k['id']}/copies", headers=a)
    assert [c["copy_no"] for c in r.json()["key"]["copies"]] == [1, 2]


def test_history_filters_and_csv(client: httpx.Client) -> None:
    h = login(client, "duty")
    all_ev = client.get("/api/events", headers=h).json()
    assert all_ev["total"] == 6 + 10 + 6 + 3  # ключи, экземпляры, выдачи, возвраты
    ret = client.get("/api/events", params={"kind": "return"}, headers=h).json()
    assert ret["total"] == 3 and {e["kind_text"] for e in ret["events"]} == {"возврат"}
    k = _key(client, h, "К-201")
    assert {e["label"] for e in client.get("/api/events", params={"key_id": k["id"], "kind": "issue"}, headers=h).json()["events"]} == {"К-201"}
    since = _iso(datetime.now(UTC) - timedelta(hours=3))
    recent = client.get("/api/events", params={"from": since, "kind": "issue"}, headers=h).json()["events"]
    assert sorted(e["staff"] for e in recent) == ["Вера Седова", "Егор Рябов"]
    assert client.get("/api/events", params={"from": "вчера"}, headers=h).status_code == 400
    r = client.get("/api/events.csv", params={"kind": "issue"}, headers=h)
    assert r.headers["content-type"].startswith("text/csv") and "attachment" in r.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(r.text.lstrip("﻿")), delimiter=";"))
    assert rows[0][:3] == ["Время (UTC)", "Операция", "Ключ"] and len(rows) == 1 + 6
    assert all(x[1] == "выдача" for x in rows[1:])


def test_csv_formula_injection_is_neutralized(client: httpx.Client) -> None:
    a = login(client, "admin")
    client.post("/api/staff", json={"name": "=HYPERLINK(\"x\")", "department": "+1"}, headers=a)
    text = client.get("/api/events.csv", params={"kind": "staff_create"}, headers=a).text
    assert "'=HYPERLINK" in text and ";=HYPERLINK" not in text


def test_seed_idempotent_and_reset_rights(client: httpx.Client) -> None:
    from app.db import connect
    from app.seed import seed

    conn = connect()
    try:
        first = seed(conn)
        assert first == {"users": 3, "staff": 6, "keys": 6, "key_copies": 10, "loans": 6}
        assert seed(conn) == first
    finally:
        conn.close()
    assert client.post("/api/demo/reset", headers=login(client, "duty")).status_code == 403
    assert client.post("/api/demo/reset", headers=login(client, "admin")).status_code == 200
