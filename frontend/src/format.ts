export const dateTime = (iso: string) => new Date(iso).toLocaleString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });

/** «2 ч 5 мин», «3 дн 4 ч», «40 мин». */
export function span(ms: number): string {
  const min = Math.max(0, Math.floor(ms / 60000));
  if (min < 60) return `${min} мин`;
  const h = Math.floor(min / 60);
  if (h < 24) return min % 60 ? `${h} ч ${min % 60} мин` : `${h} ч`;
  const d = Math.floor(h / 24);
  return h % 24 ? `${d} дн ${h % 24} ч` : `${d} дн`;
}

/** Срок возврата словами относительно «сейчас» сервера: строго позже срока — просрочка. */
export function dueText(dueIso: string, nowIso: string): { text: string; overdue: boolean } {
  const due = new Date(dueIso).getTime();
  const now = new Date(nowIso).getTime();
  if (now > due) return { text: `просрочен на ${span(now - due)}`, overdue: true };
  return { text: `вернуть до ${dateTime(dueIso)} (через ${span(due - now)})`, overdue: false };
}

/** Значение для <input type="datetime-local"> по локальному времени. */
export function toLocalInput(d: Date): string {
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

/** Срок по умолчанию: через 4 часа, округлено вверх до 15 минут. */
export function defaultDue(now = new Date()): string {
  const d = new Date(now.getTime() + 4 * 3600_000);
  d.setSeconds(0, 0);
  d.setMinutes(Math.ceil(d.getMinutes() / 15) * 15);
  return toLocalInput(d);
}

/** Локальное «YYYY-MM-DDTHH:MM» → ISO с часовым поясом (UTC). Пусто или неверно — null. */
export function localToIso(v: string): string | null {
  if (!/^\d{4}-\d\d-\d\dT\d\d:\d\d$/.test(v)) return null;
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

/** Начало локального дня «YYYY-MM-DD» в ISO; для «по» — начало следующего дня (граница не включается). */
export function dayToIso(v: string, next = false): string | undefined {
  if (!/^\d{4}-\d\d-\d\d$/.test(v)) return undefined;
  const [y, m, d] = v.split('-').map(Number);
  return new Date(y!, m! - 1, d! + (next ? 1 : 0)).toISOString();
}
