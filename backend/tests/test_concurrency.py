"""Параллельные выдачи и возвраты на настоящем uvicorn (отдельный процесс, пул потоков, SQLite WAL)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import httpx

from .conftest import http_login


def test_parallel_issue_one_copy_one_loan(live_server: str) -> None:
    a, b = http_login(live_server, "duty"), http_login(live_server, "duty2")
    keys = httpx.get(f"{live_server}/api/keys", headers=a).json()["keys"]
    cid = next(k for k in keys if k["label"] == "К-202")["copies"][0]["id"]
    staff = [s["id"] for s in httpx.get(f"{live_server}/api/staff", headers=a).json()["staff"]]
    with ThreadPoolExecutor(max_workers=8) as pool:
        res = list(pool.map(lambda i: httpx.post(f"{live_server}/api/key-loans", json={"copy_id": cid, "staff_id": staff[i % 6], "due_at": "2030-01-01T10:00:00Z"}, headers=(a, b)[i % 2], timeout=30), range(8)))
    codes = sorted(r.status_code for r in res)
    assert codes.count(201) == 1 and set(codes) <= {200, 201, 409}
    active = [x for x in httpx.get(f"{live_server}/api/key-loans", headers=a).json()["loans"] if x["copy_id"] == cid]
    assert len(active) == 1
    ev = httpx.get(f"{live_server}/api/events", params={"kind": "issue", "key_id": next(k for k in keys if k["label"] == "К-202")["id"]}, headers=a).json()
    assert ev["total"] == 1


def test_parallel_returns_one_event(live_server: str) -> None:
    a = http_login(live_server, "duty")
    lid = next(x for x in httpx.get(f"{live_server}/api/key-loans", headers=a).json()["loans"] if x["label"] == "К-102")["id"]
    with ThreadPoolExecutor(max_workers=6) as pool:
        res = list(pool.map(lambda _: httpx.post(f"{live_server}/api/key-loans/{lid}/return", headers=a, timeout=30).json(), range(6)))
    assert sum(1 for r in res if r["changed"]) == 1
    assert len({r["loan"]["returned_at"] for r in res}) == 1
    ret = httpx.get(f"{live_server}/api/events", params={"kind": "return"}, headers=a).json()["events"]
    assert sum(1 for e in ret if e["loan_id"] == lid) == 1
