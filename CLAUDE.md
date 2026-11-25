# Правила работы с проектом 219 Журнал выдачи ключей

Сервер FastAPI + SQLite (stdlib `sqlite3`, без ORM), интерфейс React + TypeScript + Vite. Один Docker-контейнер, порт `127.0.0.1:8219`.

## Где что находится

- Интерфейс и публичные маршруты — `frontend/src/App.tsx` (вкладки `#keys`, `#active`, `#overdue`, `#history`, `#staff`), `frontend/src/ui/Login.tsx`, `frontend/src/api.ts`, `frontend/src/format.ts`. API: `/api/keys[/{id}/copies]`, `/api/copies/{id}`, `/api/staff`, `/api/key-loans[/{id}/return]`, `/api/events`, `/api/events.csv`, `/api/auth/*`, `/api/me`, `/api/health`, `/api/demo/*` (только `DEMO_MODE=1`). OpenAPI — `/api/docs`.
- Предметная логика и хранение — `backend/app/service.py` (правила), `backend/app/main.py` (маршруты, роли), `backend/app/web.py` и `auth.py`, `backend/app/db.py`, `backend/app/migrations/*.sql`.
- Данные, ассеты и демоматериалы — `backend/app/seed.py` (администратор, два дежурных, 6 сотрудников, 6 ключей на 10 экземпляров, выдачи), `backend/app/synthetic.py KEYS [LOANS_PER_COPY]`, `frontend/public/favicon.svg` (собственная), том Docker `keys-data`.
- Тесты и документация — `backend/tests/` (pytest), `frontend/src/*.test.ts` (Vitest), `frontend/e2e/` (Playwright), `scripts/container_check.py`, `docs/`.

## Команды и сценарий

- Установка — `docker compose up -d --build`. Для разработки: `backend/.venv` + `pip install -r requirements-dev.txt`, `frontend: npm ci`.
- Запуск и адрес — http://127.0.0.1:8219 (контейнер). В разработке: uvicorn на :8000 и `npm run dev` на :5219.
- Проверки и сборка — `cd backend && python -m pytest`, `cd frontend && npm test && npm run build && npm run e2e` (против контейнера), `python3 scripts/container_check.py --restart`.
- Данные и результат показательного сценария — `duty / duty-demo` выдаёт `К-202 №1` Анне Беловой со сроком в прошлом: выдача сразу в «Просрочках». Повторная выдача экземпляра — 409. «Принять возврат» убирает выдачу из активных, повторный возврат не меняет время закрытия, история хранит выдачу и один возврат.

## Инварианты проекта

- Одна активная выдача на экземпляр — частичный уникальный индекс `loans_one_active_per_copy ON loans(copy_id) WHERE returned_at IS NULL`. Проверка в `service.issue` нужна для понятного ответа с текущей выдачей, защита — индекс. Не убирайте его.
- Просрочка не хранится, а вычисляется при чтении: `now() > due_at` строго. В момент срока выдача ещё не просрочена. Время — UTC в ISO 8601, `due_at` приходит с часовым поясом, без пояса — 400.
- Возврат идемпотентен: повторный вызов отвечает `changed=false`, `returned_at` и `returned_by` не меняются, события `return` второй раз нет.
- Повторная выдача того же экземпляра тому же сотруднику, пока ключ у него, отвечает 200 той же выдачей.
- Каждое изменение — одна транзакция `BEGIN IMMEDIATE`, событие журнала пишется в ней же. Автор — пользователь сессии.
- Роли: `duty` — выдача, возврат, просмотр; `admin` — плюс ключи, экземпляры, сотрудники. Проверка роли на сервере (`require_role`).
- Ключи поиска считаются в Python (`skey`): `lower()` SQLite не меняет регистр кириллицы.
- CSV: «;», BOM, ячейки, начинающиеся с `= + - @`, экранируются апострофом (защита от формул в Excel).
- Список ключей постраничный (по 50), «только доступные» считается в SQL.
- Миграции — только новыми файлами `NNN_*.sql`. `/api/demo/reset` удаляет всё, кроме учётных записей: только для демо-базы.

Изменения проверяй через основной сценарий и применимые граничные случаи. Для ночного выпуска веди в `docs/ACCEPTANCE.md` пять секций: корректность, восстановление, удобство, узкие места и воспроизводимость. Записывай измерения и результаты повторных проверок. Фактическое устройство продукта описано в `docs/ARCHITECTURE.md`, рецепты проверок — в `docs/ACCEPTANCE.md`. Публикуй этот репозиторий и развёртывай его по `PUBLISH_TO_GITHUB.md` только по запросу владельца.
