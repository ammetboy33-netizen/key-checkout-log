-- 001: исходная схема Журнал выдачи ключей.
CREATE TABLE users (
  id INTEGER PRIMARY KEY,
  username TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('duty', 'admin')),
  password_hash TEXT NOT NULL,
  salt TEXT NOT NULL
);

CREATE TABLE sessions (
  token TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at TEXT NOT NULL
);

-- Ключ: условная метка (на бирке) и помещение. Помещения в демо вымышленные.
CREATE TABLE keys (
  id INTEGER PRIMARY KEY,
  label TEXT NOT NULL UNIQUE,
  room TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  search_key TEXT NOT NULL,
  created_at TEXT NOT NULL
);

-- Физический экземпляр ключа: номер в пределах ключа (К-101 №1, К-101 №2).
CREATE TABLE key_copies (
  id INTEGER PRIMARY KEY,
  key_id INTEGER NOT NULL REFERENCES keys(id),
  copy_no INTEGER NOT NULL CHECK (copy_no >= 1),
  retired_at TEXT,
  UNIQUE (key_id, copy_no)
);

-- Сотрудники, которым выдают ключи (учётные записи им не нужны).
CREATE TABLE staff (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  department TEXT NOT NULL DEFAULT '',
  search_key TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1
);

-- Выдача: кто взял, кто выдал, плановый срок, фактический возврат и кто принял.
CREATE TABLE loans (
  id INTEGER PRIMARY KEY,
  copy_id INTEGER NOT NULL REFERENCES key_copies(id),
  staff_id INTEGER NOT NULL REFERENCES staff(id),
  issued_at TEXT NOT NULL,
  issued_by INTEGER NOT NULL REFERENCES users(id),
  due_at TEXT NOT NULL,
  returned_at TEXT,
  returned_by INTEGER REFERENCES users(id)
);
-- Одна активная выдача на экземпляр: вторая параллельная выдача упирается в индекс.
CREATE UNIQUE INDEX loans_one_active_per_copy ON loans(copy_id) WHERE returned_at IS NULL;
CREATE INDEX loans_active_due ON loans(due_at) WHERE returned_at IS NULL;
CREATE INDEX loans_staff ON loans(staff_id, id DESC);

-- Журнал операций для истории и экспорта.
CREATE TABLE events (
  id INTEGER PRIMARY KEY,
  at TEXT NOT NULL,
  actor_id INTEGER REFERENCES users(id),
  kind TEXT NOT NULL CHECK (kind IN ('issue', 'return', 'key_create', 'copy_add', 'copy_retire', 'copy_restore', 'staff_create')),
  key_id INTEGER REFERENCES keys(id),
  copy_id INTEGER REFERENCES key_copies(id),
  loan_id INTEGER REFERENCES loans(id),
  staff_id INTEGER REFERENCES staff(id),
  details TEXT NOT NULL DEFAULT ''
);
CREATE INDEX events_at ON events(at, id);
CREATE INDEX events_key ON events(key_id, at);
