#!/usr/bin/env python3
"""Сквозная проверка запущенного контейнера без сторонних библиотек.

    python3 scripts/container_check.py                 # http://127.0.0.1:8219
    python3 scripts/container_check.py --restart       # + docker compose restart и проверка сохранности
    python3 scripts/container_check.py --base http://127.0.0.1:9000

Шаги: готовность → входы → сброс демо → выдача К-202 №1 с истекшим сроком попадает в просроченные →
8 одновременных выдач другого экземпляра: одна → повторная выдача занятого 409 → возврат и повторный
возврат (время закрытия то же, событие одно) → история и CSV → дежурный не регистрирует ключи →
[перезапуск → выдачи и история сохранены].
Демо-режим (DEMO_MODE=1) обязателен: используется /api/demo/reset.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import quote


class Session:
    def __init__(self, base: str) -> None:
        self.base = base
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))

    def call(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={"Content-Type": "application/json"} if data else {})
        try:
            with self.opener.open(req, timeout=15) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")


def wait_ready(base: str, timeout: float = 90) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(base + "/api/health", timeout=2) as r:
                h = json.loads(r.read())
                if h.get("status") == "ok":
                    return h
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            pass
        time.sleep(1)
    raise SystemExit("FAIL: сервер не стал готов")


def step(ok: bool, text: str) -> None:
    print(("ok   " if ok else "FAIL ") + text)
    if not ok:
        sys.exit(1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8219")
    ap.add_argument("--restart", action="store_true")
    args = ap.parse_args()
    base = args.base.rstrip("/")
    h = wait_ready(base)
    step(True, f"готовность: схема v{h.get('schema_version')}")
    s = {u: Session(base) for u in ("admin", "duty", "duty2")}
    for u, sess in s.items():
        st, _ = sess.call("POST", "/api/auth/login", {"username": u, "password": "admin-demo" if u == "admin" else "duty-demo"})
        step(st == 200, f"вход {u}")
    st, _ = s["admin"].call("POST", "/api/demo/reset")
    step(st == 200, "сброс демо")
    d = s["duty"]
    keys = {k["label"]: k for k in d.call("GET", "/api/keys")[1]["keys"]}
    staff = d.call("GET", "/api/staff")[1]["staff"]
    past = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    st, r = d.call("POST", "/api/key-loans", {"copy_id": keys["К-202"]["copies"][0]["id"], "staff_id": staff[0]["id"], "due_at": past})
    step(st == 201 and r["loan"]["overdue"], "выдача с истекшим сроком сразу просрочена")
    lid = r["loan"]["id"]
    over = [x["label"] for x in d.call("GET", "/api/key-loans?status=overdue")[1]["loans"]]
    step("К-202" in over, f"в просроченных: {over}")
    cid = keys["К-101"]["copies"][0]["id"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        out = list(pool.map(lambda i: (d, s["duty2"])[i % 2].call("POST", "/api/key-loans", {"copy_id": cid, "staff_id": staff[i % 6]["id"], "due_at": "2030-01-01T10:00:00Z"}), range(8)))
    codes = sorted(x[0] for x in out)
    step(codes.count(201) == 1, f"8 одновременных выдач одного экземпляра: коды {codes}")
    st, r = d.call("POST", "/api/key-loans", {"copy_id": keys["К-202"]["copies"][0]["id"], "staff_id": staff[1]["id"], "due_at": "2030-01-01T10:00:00Z"})
    step(st == 409 and r["code"] == "copy_taken", "повторная выдача занятого экземпляра — 409")
    st, r1 = d.call("POST", f"/api/key-loans/{lid}/return")
    st2, r2 = s["duty2"].call("POST", f"/api/key-loans/{lid}/return")
    step(r1["changed"] and not r2["changed"] and r1["loan"]["returned_at"] == r2["loan"]["returned_at"], "повторный возврат не меняет время закрытия")
    ev = d.call("GET", f"/api/events?kind=return&key_id={keys['К-202']['id']}")[1]
    step(ev["total"] == 1, "в истории один возврат")
    with d.opener.open(base + "/api/events.csv?kind=issue", timeout=10) as resp:
        text = resp.read().decode("utf-8")
    step(text.startswith("﻿Время (UTC);Операция") and "К-202" in text, "экспорт CSV")
    st, _ = d.call("POST", "/api/keys", {"label": "К-999", "room": "Тест"})
    step(st == 403, "дежурный не регистрирует ключи (403)")
    if args.restart:
        root = Path(__file__).resolve().parent.parent
        subprocess.run(["docker", "compose", "restart", "app"], cwd=root, check=True)
        wait_ready(base)
        a = Session(base)
        a.call("POST", "/api/auth/login", {"username": "duty", "password": "duty-demo"})
        act = [x["label"] for x in a.call("GET", "/api/key-loans?status=active")[1]["loans"]]
        ev = a.call("GET", f"/api/events?kind=return&key_id={keys['К-202']['id']}")[1]
        step("К-101" in act and ev["total"] == 1, "после перезапуска выдачи и история сохранены")
    print("Все проверки пройдены")
    return 0


if __name__ == "__main__":
    sys.exit(main())
