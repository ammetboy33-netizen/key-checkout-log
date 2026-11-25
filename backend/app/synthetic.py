"""Синтетика для замеров: python -m app.synthetic KEYS [LOANS_PER_COPY]

KEYS ключей «С-NNNNN» по 2 экземпляра, у каждого экземпляра LOANS_PER_COPY закрытых выдач в прошлом
(история) и каждый пятый ключ выдан сейчас, часть с просрочкой. 200 синтетических сотрудников.
Повторный запуск продолжает нумерацию. Демо-сброс удаляет и синтетику.
"""
from __future__ import annotations

import sys
from datetime import timedelta

from .db import connect, migrate, write_tx
from .service import iso, now, skey


def main(argv: list[str]) -> int:
    n = int(argv[0]) if argv else 2000
    per = int(argv[1]) if len(argv) > 1 else 10
    conn = connect()
    try:
        migrate(conn)
        actor = conn.execute("SELECT id FROM users WHERE role IN ('duty', 'admin') ORDER BY id LIMIT 1").fetchone()
        if actor is None:
            print("нет пользователей: python -m app.seed", file=sys.stderr)
            return 1
        aid = actor["id"]
        t = now()
        with write_tx(conn):
            staff = [r[0] for r in conn.execute("SELECT id FROM staff WHERE name LIKE 'Синтетический сотрудник %'")]
            for i in range(len(staff), 200):
                staff.append(conn.execute("INSERT INTO staff (name, department, search_key) VALUES (?, 'Синтетика', ?) RETURNING id", (f"Синтетический сотрудник {i + 1:03d}", skey(f"Синтетический сотрудник {i + 1:03d}"))).fetchone()[0])
            start = conn.execute("SELECT COUNT(*) FROM keys WHERE label LIKE 'С-%'").fetchone()[0]
            ev, ln = [], []
            for i in range(start + 1, start + n + 1):
                label = f"С-{i:05d}"
                room = f"Синтетическое помещение {i}"
                kid = conn.execute("INSERT INTO keys (label, room, search_key, created_at) VALUES (?, ?, ?, ?) RETURNING id", (label, room, skey(label, room), iso(t - timedelta(days=400)))).fetchone()[0]
                for c in (1, 2):
                    cid = conn.execute("INSERT INTO key_copies (key_id, copy_no) VALUES (?, ?) RETURNING id", (kid, c)).fetchone()[0]
                    for k in range(per):
                        st = staff[(i * 7 + c * 3 + k) % len(staff)]
                        issued = t - timedelta(days=360 - (k * 360 // max(per, 1)), hours=(i % 9))
                        ret = issued + timedelta(hours=3)
                        lid = conn.execute(
                            "INSERT INTO loans (copy_id, staff_id, issued_at, issued_by, due_at, returned_at, returned_by) VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id",
                            (cid, st, iso(issued), aid, iso(issued + timedelta(hours=4)), iso(ret), aid),
                        ).fetchone()[0]
                        ev.append((iso(issued), aid, "issue", kid, cid, lid, st, f"{label} №{c}"))
                        ev.append((iso(ret), aid, "return", kid, cid, lid, st, f"{label} №{c}"))
                    if c == 1 and i % 5 == 0:
                        st = staff[i % len(staff)]
                        due = t - timedelta(hours=2) if i % 10 == 0 else t + timedelta(hours=6)
                        ln.append((cid, st, iso(t - timedelta(hours=5)), aid, iso(due)))
            conn.executemany("INSERT INTO loans (copy_id, staff_id, issued_at, issued_by, due_at) VALUES (?, ?, ?, ?, ?)", ln)
            conn.executemany("INSERT INTO events (at, actor_id, kind, key_id, copy_id, loan_id, staff_id, details) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", ev)
        print(f"keys+={n}, history_loans+={n * 2 * per}, active+={len(ln)}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
