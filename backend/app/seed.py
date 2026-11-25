"""Демоданные: администратор, два дежурных, 6 сотрудников, 6 ключей на 10 экземпляров, выдачи и история.

python -m app.seed           — создать, если нет (повторный запуск не дублирует данные)
python -m app.seed --reset   — вернуть демо к исходному виду (удаляет ключи, сотрудников, выдачи и журнал)

Все помещения и люди вымышлены.
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import timedelta

from .auth import hash_password
from .db import connect, migrate, write_tx
from .service import iso, now, skey

RESET_ROLE = "admin"
DEMO_USERS: list[tuple[str, str, str, str]] = [
    ("admin", "Ольга Ветрова", "admin", "admin-demo"),
    ("duty", "Сергей Ким", "duty", "duty-demo"),
    ("duty2", "Нина Ли", "duty", "duty-demo"),
]
STAFF = [
    ("Анна Белова", "Бухгалтерия"),
    ("Борис Орлов", "ИТ-отдел"),
    ("Вера Седова", "Отдел кадров"),
    ("Глеб Наумов", "Хозяйственная служба"),
    ("Дарья Котова", "Отдел продаж"),
    ("Егор Рябов", "ИТ-отдел"),
]
# метка, помещение, заметка, экземпляров
KEYS = [
    ("К-101", "Переговорная «Сосна»", "", 2),
    ("К-102", "Склад «Б-2»", "Брелок синий", 1),
    ("К-201", "Серверная «Север»", "Только ИТ-отдел", 2),
    ("К-202", "Кабинет 7", "", 1),
    ("К-301", "Архив «Липа»", "", 2),
    ("К-302", "Мастерская «Клён»", "Брелок красный", 2),
]


def seed(conn: sqlite3.Connection, reset: bool = False) -> dict[str, int]:
    migrate(conn)
    with write_tx(conn):
        if reset:
            for t in ("events", "loans", "key_copies", "keys", "staff"):
                conn.execute(f"DELETE FROM {t}")
            demo = [u[0] for u in DEMO_USERS]
            conn.execute(f"DELETE FROM sessions WHERE user_id NOT IN (SELECT id FROM users WHERE username IN ({','.join('?' * len(demo))}))", demo)
        ids: dict[str, int] = {}
        for username, name, role, pwd in DEMO_USERS:
            row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
            if row is None:
                h, salt = hash_password(pwd)
                row = conn.execute(
                    "INSERT INTO users (username, display_name, role, password_hash, salt) VALUES (?, ?, ?, ?, ?) RETURNING id",
                    (username, name, role, h, salt),
                ).fetchone()
            ids[username] = int(row["id"])
        if conn.execute("SELECT COUNT(*) FROM keys").fetchone()[0] == 0:
            t = now()
            ago = lambda **kw: iso(t - timedelta(**kw))  # noqa: E731
            staff = {}
            for name, dep in STAFF:
                staff[name] = conn.execute("INSERT INTO staff (name, department, search_key) VALUES (?, ?, ?) RETURNING id", (name, dep, skey(name, dep))).fetchone()["id"]
            copies: dict[str, int] = {}
            for label, room, note, n in KEYS:
                kid = conn.execute("INSERT INTO keys (label, room, note, search_key, created_at) VALUES (?, ?, ?, ?, ?) RETURNING id", (label, room, note, skey(label, room, note), ago(days=30))).fetchone()["id"]
                conn.execute("INSERT INTO events (at, actor_id, kind, key_id, details) VALUES (?, ?, 'key_create', ?, ?)", (ago(days=30), ids["admin"], kid, f"{label} · {room}"))
                for k in range(1, n + 1):
                    cid = conn.execute("INSERT INTO key_copies (key_id, copy_no) VALUES (?, ?) RETURNING id", (kid, k)).fetchone()["id"]
                    copies[f"{label}/{k}"] = cid
                    conn.execute("INSERT INTO events (at, actor_id, kind, key_id, copy_id, details) VALUES (?, ?, 'copy_add', ?, ?, ?)", (ago(days=30), ids["admin"], kid, cid, f"{label} №{k}"))

            def loan(copy: str, who: str, by: str, issued: str, due: str, returned: str | None = None, rby: str | None = None) -> None:
                cid = copies[copy]
                kid = conn.execute("SELECT key_id FROM key_copies WHERE id = ?", (cid,)).fetchone()[0]
                lid = conn.execute(
                    "INSERT INTO loans (copy_id, staff_id, issued_at, issued_by, due_at, returned_at, returned_by) VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id",
                    (cid, staff[who], issued, ids[by], due, returned, ids[rby] if rby else None),
                ).fetchone()["id"]
                label, no = copy.split("/")
                conn.execute("INSERT INTO events (at, actor_id, kind, key_id, copy_id, loan_id, staff_id, details) VALUES (?, ?, 'issue', ?, ?, ?, ?, ?)", (issued, ids[by], kid, cid, lid, staff[who], f"{label} №{no} → {who}, срок {due}"))
                if returned:
                    conn.execute("INSERT INTO events (at, actor_id, kind, key_id, copy_id, loan_id, staff_id, details) VALUES (?, ?, 'return', ?, ?, ?, ?, ?)", (returned, ids[rby or by], kid, cid, lid, staff[who], f"{label} №{no} ← {who}"))

            # История: закрытые выдачи прошлых дней.
            loan("К-101/1", "Анна Белова", "duty", ago(days=3, hours=6), ago(days=3, hours=2), ago(days=3, hours=3), "duty")
            loan("К-201/1", "Борис Орлов", "duty2", ago(days=2, hours=8), ago(days=2), ago(days=2, hours=1), "duty2")
            loan("К-302/1", "Глеб Наумов", "duty", ago(days=1, hours=7), ago(days=1, hours=1), ago(days=1, minutes=30), "duty")
            # Активные: одна просрочена со вчерашнего дня, две в срок.
            loan("К-102/1", "Глеб Наумов", "duty2", ago(days=1, hours=5), ago(hours=20))
            loan("К-201/2", "Егор Рябов", "duty", ago(hours=2), iso(t + timedelta(hours=4)))
            loan("К-301/1", "Вера Седова", "duty", ago(hours=1), iso(t + timedelta(days=1)))
    return {k: conn.execute(f"SELECT COUNT(*) FROM {k}").fetchone()[0] for k in ("users", "staff", "keys", "key_copies", "loans")}


def main(argv: list[str]) -> int:
    conn = connect()
    try:
        c = seed(conn, reset="--reset" in argv)
        print(", ".join(f"{k}={v}" for k, v in c.items()))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
