import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, authApi, type User } from './api-core';
import { api, EVENT_KINDS, type Copy, type EventFilter, type EventKind, type EventRow, type Key, type Loan, type Staff } from './api';
import { dateTime, dayToIso, defaultDue, dueText, localToIso, toLocalInput } from './format';
import { Login } from './ui/Login';

type View = 'keys' | 'active' | 'overdue' | 'history' | 'staff';
const VIEWS: [View, string][] = [
  ['keys', 'Ключи'],
  ['active', 'Выдано'],
  ['overdue', 'Просрочки'],
  ['history', 'История'],
  ['staff', 'Сотрудники'],
];
const parse = (): View => {
  const h = location.hash.slice(1);
  return (VIEWS.map((v) => v[0]) as string[]).includes(h) ? (h as View) : 'keys';
};
const roleLabel = (r: string) => (r === 'admin' ? 'администратор' : 'дежурный');
const errText = (e: unknown) => (e instanceof ApiError ? e.message : 'Не удалось выполнить действие');

function useLoad<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [n, setN] = useState(0);
  useEffect(() => {
    let alive = true;
    fn()
      .then((d) => alive && (setData(d), setError(null)))
      .catch((e: unknown) => alive && setError(errText(e)));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, n]);
  return { data, error, reload: useCallback(() => setN((x) => x + 1), []) };
}

export function App() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<string | null>(null);
  const [loginNotice, setLoginNotice] = useState<string | null>(null);
  const [view, setView] = useState<View>(parse);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    authApi
      .me()
      .then((r) => setUser(r.user))
      .catch(() => undefined)
      .finally(() => setLoading(false));
    const lost = () => (setUser(null), setLoginNotice('Сессия закончилась, войдите снова'));
    const hash = () => setView(parse());
    window.addEventListener('auth-lost', lost);
    window.addEventListener('hashchange', hash);
    return () => {
      window.removeEventListener('auth-lost', lost);
      window.removeEventListener('hashchange', hash);
    };
  }, []);
  useEffect(() => {
    if (!notice) return;
    const t = window.setTimeout(() => setNotice(null), 6000);
    return () => window.clearTimeout(t);
  }, [notice]);
  if (loading) return <p className="muted">Загрузка…</p>;
  if (!user) return <Login onLogin={(u) => (setUser(u), setLoginNotice(null))} notice={loginNotice} roleLabel={roleLabel} />;
  const admin = user.role === 'admin';
  const done = (text: string) => (setNotice(text), setTick((x) => x + 1));
  return (
    <div className="app">
      <header className="topbar">
        <div>
          <p className="kicker">Журнал выдачи ключей</p>
          <h1>{VIEWS.find((v) => v[0] === view)?.[1]}</h1>
        </div>
        <div className="whoami">
          <span data-testid="whoami">
            {user.display_name} · {roleLabel(user.role)}
          </span>
          <button type="button" className="btn btn--ghost" onClick={() => void authApi.logout().finally(() => setUser(null))}>
            Выйти
          </button>
        </div>
      </header>
      <nav className="tabs" aria-label="Разделы">
        {VIEWS.map(([v, label]) => (
          <a key={v} href={`#${v}`} className={`tab ${view === v ? 'tab--on' : ''}`} aria-current={view === v ? 'page' : undefined}>
            {label}
          </a>
        ))}
      </nav>
      <p className="notice-line" role="status" aria-live="polite" data-testid="notice">
        {notice ?? ''}
      </p>
      {view === 'keys' ? (
        <KeysView admin={admin} tick={tick} done={done} />
      ) : view === 'active' || view === 'overdue' ? (
        <LoansView key={view} status={view} tick={tick} done={done} />
      ) : view === 'history' ? (
        <HistoryView tick={tick} />
      ) : (
        <StaffView admin={admin} done={done} />
      )}
    </div>
  );
}

/* ---------------- Ключи ---------------- */

function KeysView({ admin, tick, done }: { admin: boolean; tick: number; done: (t: string) => void }) {
  const [q, setQ] = useState('');
  const [dq, setDq] = useState('');
  const [free, setFree] = useState(false);
  useEffect(() => {
    const t = window.setTimeout(() => setDq(q.trim()), 250);
    return () => window.clearTimeout(t);
  }, [q]);
  const { data, error, reload } = useLoad(() => api.keys(dq, free), [dq, free, tick]);
  const staff = useLoad(() => api.staff(), [tick]);
  const now = new Date().toISOString();
  // «Показать ещё»: следующие 50 ключей дописываются, новый поиск сбрасывает их.
  const [more, setMore] = useState<Key[]>([]);
  const [moreErr, setMoreErr] = useState<string | null>(null);
  const focusFrom = useRef<number | null>(null);
  useEffect(() => setMore([]), [data]);
  const shown = data ? [...data.keys, ...more] : [];
  useEffect(() => {
    const i = focusFrom.current;
    if (i === null) return;
    focusFrom.current = null;
    document.querySelectorAll<HTMLElement>('[data-testid="key"] h2')[i]?.focus();
  }, [more]);
  return (
    <main>
      <div className="filters" role="search">
        <div className="field field--grow">
          <label htmlFor="q">Метка, помещение или заметка</label>
          <input id="q" type="search" value={q} onChange={(e) => setQ(e.target.value)} autoComplete="off" />
        </div>
        <label className="check">
          <input type="checkbox" checked={free} onChange={(e) => setFree(e.target.checked)} /> Только доступные
        </label>
      </div>
      {error ? (
        <p className="errors" role="alert">
          {error}
        </p>
      ) : null}
      {data ? (
        <>
          <p className="muted" data-testid="found" aria-live="polite">
            Ключей: {data.total}
            {data.total > shown.length ? `, показаны ${shown.length}` : ''}
          </p>
          {shown.length ? (
            <ul className="keys">
              {shown.map((k) => (
                <KeyCard key={k.id} k={k} admin={admin} staff={staff.data?.staff ?? []} now={now} done={(t) => (reload(), done(t))} />
              ))}
            </ul>
          ) : (
            <p className="empty">Ключей не найдено.</p>
          )}
          {data.total > shown.length ? (
            <p>
              <button
                type="button"
                className="btn"
                onClick={() =>
                  void api.keys(dq, free, shown.length).then(
                    (r) => ((focusFrom.current = shown.length), setMore((m) => [...m, ...r.keys])),
                    (e) => setMoreErr(errText(e)),
                  )
                }
              >
                Показать ещё {Math.min(50, data.total - shown.length)}
              </button>
              {moreErr ? <span className="errors"> {moreErr}</span> : null}
            </p>
          ) : null}
        </>
      ) : null}
      {admin ? <NewKey done={done} /> : null}
    </main>
  );
}

function KeyCard({ k, admin, staff, now, done }: { k: Key; admin: boolean; staff: Staff[]; now: string; done: (t: string) => void }) {
  const [err, setErr] = useState<string | null>(null);
  const errRef = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    if (err) errRef.current?.focus();
  }, [err]);
  return (
    <li className="panel key" data-testid="key" data-label={k.label}>
      <div className="key__head">
        <h2 tabIndex={-1}>
          {k.label} <span className="key__room">{k.room}</span>
        </h2>
        <span className={`pill ${k.available ? '' : 'pill--warn'}`} data-testid="avail">
          {k.available ? `доступно ${k.available} из ${k.copies.filter((c) => !c.retired).length}` : 'нет доступных'}
        </span>
      </div>
      {k.note ? <p className="muted small">{k.note}</p> : null}
      {err ? (
        <p ref={errRef} tabIndex={-1} className="banner" role="alert" data-testid="key-error">
          {err}
        </p>
      ) : null}
      <ul className="copies">
        {k.copies.map((c) => (
          <CopyRow key={c.id} k={k} c={c} admin={admin} staff={staff} now={now} setErr={setErr} done={done} />
        ))}
      </ul>
      {admin ? (
        <button type="button" className="btn btn--ghost" onClick={() => void api.addCopy(k.id).then(() => done(`${k.label}: добавлен экземпляр`), (e) => setErr(errText(e)))}>
          Добавить экземпляр
        </button>
      ) : null}
    </li>
  );
}

function CopyRow({
  k,
  c,
  admin,
  staff,
  now,
  setErr,
  done,
}: {
  k: Key;
  c: Copy;
  admin: boolean;
  staff: Staff[];
  now: string;
  setErr: (e: string | null) => void;
  done: (t: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [who, setWho] = useState('');
  const [due, setDue] = useState(defaultDue);
  const [busy, setBusy] = useState(false);
  const sel = useRef<HTMLSelectElement>(null);
  useEffect(() => {
    if (open) sel.current?.focus();
  }, [open]);
  const name = `${k.label} №${c.copy_no}`;
  const dueIso = localToIso(due);
  const past = dueIso !== null && new Date(dueIso).getTime() <= Date.now();
  const l = c.loan;
  return (
    <li className={`copy ${l?.overdue ? 'copy--overdue' : ''}`} data-testid="copy" data-copy={name}>
      <div className="copy__line">
        <strong>№{c.copy_no}</strong>{' '}
        {c.retired ? (
          <span className="muted">списан</span>
        ) : l ? (
          <span data-testid="holder">
            у {l.staff}
            {l.department ? ` (${l.department})` : ''} · <span className={l.overdue ? 'bad' : ''}>{dueText(l.due_at, now).text}</span>
          </span>
        ) : (
          <span className="ok">свободен</span>
        )}
        <span className="copy__actions">
          {l ? (
            <button
              type="button"
              className="btn"
              aria-label={`Принять возврат: ${name}`}
              aria-disabled={busy}
              onClick={async () => {
                if (busy) return;
                setBusy(true);
                setErr(null);
                try {
                  const r = await api.giveBack(l.id);
                  done(r.changed ? `${name} принят от: ${l.staff}` : `${name} уже был возвращён`);
                } catch (e) {
                  setErr(errText(e));
                } finally {
                  setBusy(false);
                }
              }}
            >
              Принять возврат
            </button>
          ) : !c.retired && !open ? (
            <button type="button" className="btn btn--primary" aria-label={`Выдать ${name}`} onClick={() => setOpen(true)}>
              Выдать
            </button>
          ) : null}
          {admin && !l ? (
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() => void api.retire(c.id, !c.retired).then(() => done(c.retired ? `${name} возвращён в работу` : `${name} списан`), (e) => setErr(errText(e)))}
            >
              {c.retired ? 'Вернуть в работу' : 'Списать'}
            </button>
          ) : null}
        </span>
      </div>
      {open && !l ? (
        <form
          className="row issue"
          onSubmit={async (e) => {
            e.preventDefault();
            if (busy) return;
            if (!who) return setErr('Выберите сотрудника');
            if (!dueIso) return setErr('Укажите срок возврата');
            setBusy(true);
            setErr(null);
            try {
              const r = await api.issue(c.id, Number(who), dueIso);
              setOpen(false);
              done(`${name} выдан: ${r.loan.staff}${r.loan.overdue ? ' (срок уже прошёл — выдача просрочена)' : ''}`);
            } catch (err) {
              const holder = err instanceof ApiError ? (err.data as { loan?: Loan } | undefined)?.loan : undefined;
              setErr(holder ? `${errText(err)}. Список обновлён.` : errText(err));
              if (holder) done('');
            } finally {
              setBusy(false);
            }
          }}
        >
          <div className="field field--grow">
            <label htmlFor={`who-${c.id}`}>Кому</label>
            <select id={`who-${c.id}`} ref={sel} value={who} onChange={(e) => setWho(e.target.value)} required>
              <option value="">— выберите сотрудника —</option>
              {staff.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                  {s.department ? ` · ${s.department}` : ''}
                </option>
              ))}
            </select>
          </div>
          <div className="field field--due">
            <label htmlFor={`due-${c.id}`}>Вернуть до</label>
            <input id={`due-${c.id}`} type="datetime-local" value={due} onChange={(e) => setDue(e.target.value)} required aria-describedby={past ? `past-${c.id}` : undefined} />
          </div>
          <div className="presets" role="group" aria-label="Быстрый срок">
            {(
              [
                ['через 1 ч', () => toLocalInput(new Date(Date.now() + 3600_000))],
                ['до 18:00', () => {
                  const d = new Date();
                  if (d.getHours() >= 17) d.setDate(d.getDate() + 1);
                  d.setHours(18, 0, 0, 0);
                  return toLocalInput(d);
                }],
                ['до завтра 10:00', () => {
                  const d = new Date();
                  d.setDate(d.getDate() + 1);
                  d.setHours(10, 0, 0, 0);
                  return toLocalInput(d);
                }],
              ] as [string, () => string][]
            ).map(([t, fn]) => (
              <button key={t} type="button" className="btn btn--ghost" onClick={() => setDue(fn())}>
                {t}
              </button>
            ))}
          </div>
          <button type="submit" className="btn btn--primary" aria-disabled={busy}>
            Выдать {name}
          </button>
          <button type="button" className="btn btn--ghost" onClick={() => setOpen(false)}>
            Отмена
          </button>
          {past ? (
            <p id={`past-${c.id}`} className="warn small" data-testid="past-warning">
              Срок уже прошёл: выдача сразу попадёт в просроченные.
            </p>
          ) : null}
        </form>
      ) : null}
    </li>
  );
}

function NewKey({ done }: { done: (t: string) => void }) {
  const empty = { label: '', room: '', note: '', copies: 1 };
  const [f, setF] = useState(empty);
  const [errs, setErrs] = useState<Record<string, string>>({});
  return (
    <section className="panel" aria-labelledby="nk-h">
      <h2 id="nk-h">Новый ключ</h2>
      <form
        className="row"
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            const r = await api.createKey(f);
            setF(empty);
            setErrs({});
            done(`Ключ ${r.key.label} зарегистрирован, экземпляров: ${r.key.copies.length}`);
          } catch (err) {
            setErrs(err instanceof ApiError ? (Object.keys(err.fields).length ? err.fields : { [(err.data as { field?: string } | undefined)?.field ?? '_']: err.message }) : { _: errText(err) });
          }
        }}
      >
        {(
          [
            ['label', 'Метка на бирке'],
            ['room', 'Помещение'],
            ['note', 'Заметка (необязательно)'],
          ] as const
        ).map(([k, label]) => (
          <div key={k} className={`field ${k === 'room' ? 'field--grow' : ''}`}>
            <label htmlFor={`nk-${k}`}>{label}</label>
            <input id={`nk-${k}`} value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} aria-invalid={!!errs[k]} aria-describedby={errs[k] ? `nk-${k}-err` : undefined} />
            {errs[k] ? (
              <span id={`nk-${k}-err`} className="error">
                {errs[k]}
              </span>
            ) : null}
          </div>
        ))}
        <div className="field field--num">
          <label htmlFor="nk-copies">Экземпляров</label>
          <input id="nk-copies" type="number" min={1} max={20} value={f.copies} onChange={(e) => setF({ ...f, copies: Math.max(1, Math.min(20, Number(e.target.value) || 1)) })} />
        </div>
        <button type="submit" className="btn btn--primary">
          Зарегистрировать
        </button>
        {errs._ ? (
          <p className="errors" role="alert">
            {errs._}
          </p>
        ) : null}
      </form>
    </section>
  );
}

/* ---------------- Выдано и просрочки ---------------- */

function LoansView({ status, tick, done }: { status: 'active' | 'overdue'; tick: number; done: (t: string) => void }) {
  const [n, setN] = useState(0);
  const { data, error } = useLoad(() => api.loans(status), [status, tick, n]);
  const [err, setErr] = useState<string | null>(null);
  return (
    <main>
      {error || err ? (
        <p className="errors" role="alert">
          {error ?? err}
        </p>
      ) : null}
      {data ? (
        data.loans.length ? (
          <div className="table-wrap">
            <table className="data cards-sm" data-testid="loans">
              <caption className="visually-hidden">{status === 'overdue' ? 'Просроченные выдачи' : 'Выданные ключи'}</caption>
              <thead>
                <tr>
                  <th scope="col">Ключ</th>
                  <th scope="col">Кому</th>
                  <th scope="col">Выдан</th>
                  <th scope="col">Срок</th>
                  <th scope="col">
                    <span className="visually-hidden">Действие</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.loans.map((l) => {
                  const d = dueText(l.due_at, data.now);
                  return (
                    <tr key={l.id} data-testid="loan" data-key={`${l.label} №${l.copy_no}`} className={d.overdue ? 'row--overdue' : ''}>
                      <td>
                        <strong>
                          {l.label} №{l.copy_no}
                        </strong>
                        <div className="muted small">{l.room}</div>
                      </td>
                      <td>
                        {l.staff}
                        {l.department ? <div className="muted small">{l.department}</div> : null}
                      </td>
                      <td>
                        {dateTime(l.issued_at)}
                        <div className="muted small">выдал(а): {l.issued_by}</div>
                      </td>
                      <td className={d.overdue ? 'bad' : ''}>{d.text}</td>
                      <td>
                        <button
                          type="button"
                          className="btn"
                          aria-label={`Принять возврат: ${l.label} №${l.copy_no}`}
                          onClick={() =>
                            void api.giveBack(l.id).then(
                              (r) => (setN((x) => x + 1), done(r.changed ? `${l.label} №${l.copy_no} принят от: ${l.staff}` : `${l.label} №${l.copy_no} уже был возвращён`)),
                              (e) => setErr(errText(e)),
                            )
                          }
                        >
                          Принять возврат
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="empty">{status === 'overdue' ? 'Просрочек нет.' : 'Сейчас ничего не выдано.'}</p>
        )
      ) : null}
    </main>
  );
}

/* ---------------- История ---------------- */

function HistoryView({ tick }: { tick: number }) {
  const keys = useLoad(() => api.keyNames(), [tick]);
  const [keyId, setKeyId] = useState('');
  const [kind, setKind] = useState('');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const filter: EventFilter = { key_id: keyId ? Number(keyId) : undefined, kind: (kind || undefined) as EventKind | undefined, from: dayToIso(from), to: dayToIso(to, true) };
  const fkey = JSON.stringify(filter);
  const { data, error } = useLoad(() => api.events(filter), [fkey, tick]);
  const [more, setMore] = useState<EventRow[]>([]);
  useEffect(() => setMore([]), [data]);
  const rows = data ? [...data.events, ...more] : [];
  return (
    <main>
      <div className="filters" role="search">
        <div className="field">
          <label htmlFor="h-key">Ключ</label>
          <select id="h-key" value={keyId} onChange={(e) => setKeyId(e.target.value)}>
            <option value="">все ключи</option>
            {keys.data?.keys.map((k) => (
              <option key={k.id} value={k.id}>
                {k.label} · {k.room}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="h-kind">Операция</label>
          <select id="h-kind" value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">все операции</option>
            {EVENT_KINDS.map(([k, t]) => (
              <option key={k} value={k}>
                {t}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="h-from">С даты</label>
          <input id="h-from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="h-to">По дату включительно</label>
          <input id="h-to" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        </div>
        <a className="btn" href={api.csvUrl(filter)} download>
          Скачать CSV
        </a>
      </div>
      {error ? (
        <p className="errors" role="alert">
          {error}
        </p>
      ) : null}
      {data ? (
        <>
          <p className="muted" data-testid="found" aria-live="polite">
            Записей: {data.total}
            {data.total > rows.length ? `, показаны ${rows.length}` : ''}
          </p>
          <div className="table-wrap">
            <table className="data cards-sm">
              <caption className="visually-hidden">История операций</caption>
              <thead>
                <tr>
                  <th scope="col">Когда</th>
                  <th scope="col">Операция</th>
                  <th scope="col">Ключ</th>
                  <th scope="col">Сотрудник</th>
                  <th scope="col">Дежурный</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((e) => (
                  <tr key={e.id} data-testid="event" data-kind={e.kind}>
                    <td>{dateTime(e.at)}</td>
                    <td>{e.kind_text}</td>
                    <td>
                      {e.label ? `${e.label}${e.copy_no ? ` №${e.copy_no}` : ''}` : '—'}
                      {e.room ? <div className="muted small">{e.room}</div> : null}
                    </td>
                    <td>{e.staff ?? '—'}</td>
                    <td>{e.actor ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.total > rows.length ? (
            <button type="button" className="btn" onClick={() => void api.events(filter, rows.length).then((r) => setMore((m) => [...m, ...r.events]))}>
              Показать ещё
            </button>
          ) : null}
        </>
      ) : null}
    </main>
  );
}

/* ---------------- Сотрудники ---------------- */

function StaffView({ admin, done }: { admin: boolean; done: (t: string) => void }) {
  const { data, error, reload } = useLoad(() => api.staff(), []);
  const [name, setName] = useState('');
  const [dep, setDep] = useState('');
  const [err, setErr] = useState<string | null>(null);
  return (
    <main>
      {error ? <p className="errors">{error}</p> : null}
      {data ? (
        <ul className="staff" data-testid="staff">
          {data.staff.map((s) => (
            <li key={s.id}>
              {s.name}
              {s.department ? <span className="muted"> · {s.department}</span> : null}
            </li>
          ))}
        </ul>
      ) : null}
      {admin ? (
        <section className="panel" aria-labelledby="ns-h">
          <h2 id="ns-h">Новый сотрудник</h2>
          <form
            className="row"
            onSubmit={async (e) => {
              e.preventDefault();
              try {
                const r = await api.createStaff({ name, department: dep });
                setName('');
                setDep('');
                setErr(null);
                reload();
                done(`Сотрудник добавлен: ${r.staff.name}`);
              } catch (er) {
                setErr(errText(er));
              }
            }}
          >
            <div className="field field--grow">
              <label htmlFor="ns-name">Имя и фамилия</label>
              <input id="ns-name" value={name} onChange={(e) => setName(e.target.value)} required />
            </div>
            <div className="field field--grow">
              <label htmlFor="ns-dep">Отдел</label>
              <input id="ns-dep" value={dep} onChange={(e) => setDep(e.target.value)} />
            </div>
            <button type="submit" className="btn btn--primary">
              Добавить
            </button>
            {err ? (
              <p className="errors" role="alert">
                {err}
              </p>
            ) : null}
          </form>
        </section>
      ) : (
        <p className="hint">Добавлять сотрудников может администратор.</p>
      )}
    </main>
  );
}
