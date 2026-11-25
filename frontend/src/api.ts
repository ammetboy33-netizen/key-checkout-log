import { request } from './api-core';

export interface Loan {
  id: number;
  copy_id: number;
  staff_id: number;
  issued_at: string;
  due_at: string;
  returned_at: string | null;
  staff: string;
  department: string;
  key_id: number;
  label: string;
  room: string;
  copy_no: number;
  issued_by: string;
  returned_by: string | null;
  overdue: boolean;
}
export interface Copy {
  id: number;
  copy_no: number;
  retired: boolean;
  loan: Loan | null;
}
export interface Key {
  id: number;
  label: string;
  room: string;
  note: string;
  copies: Copy[];
  available: number;
  overdue: number;
}
export interface Staff {
  id: number;
  name: string;
  department: string;
}
export type EventKind = 'issue' | 'return' | 'key_create' | 'copy_add' | 'copy_retire' | 'copy_restore' | 'staff_create';
export const EVENT_KINDS: [EventKind, string][] = [
  ['issue', 'выдача'],
  ['return', 'возврат'],
  ['key_create', 'новый ключ'],
  ['copy_add', 'новый экземпляр'],
  ['copy_retire', 'экземпляр списан'],
  ['copy_restore', 'экземпляр возвращён в работу'],
  ['staff_create', 'новый сотрудник'],
];
export interface EventRow {
  id: number;
  at: string;
  kind: EventKind;
  kind_text: string;
  details: string;
  loan_id: number | null;
  label: string | null;
  room: string | null;
  copy_no: number | null;
  staff: string | null;
  actor: string | null;
}
export interface EventFilter {
  key_id?: number;
  kind?: EventKind;
  from?: string;
  to?: string;
}

const qs = (f: EventFilter & { limit?: number; offset?: number }) => {
  const s = new URLSearchParams();
  for (const [k, v] of Object.entries(f)) if (v !== undefined && v !== '') s.set(k, String(v));
  return s.toString();
};

export const api = {
  keys: (q = '', available = false, offset = 0) => request<{ total: number; keys: Key[] }>('GET', `/api/keys?q=${encodeURIComponent(q)}&available=${available}&limit=50&offset=${offset}`),
  keyNames: () => request<{ total: number; keys: Pick<Key, 'id' | 'label' | 'room'>[] }>('GET', '/api/keys?brief=true&limit=5000'),
  createKey: (b: { label: string; room: string; note: string; copies: number }) => request<{ key: Key }>('POST', '/api/keys', b),
  addCopy: (keyId: number) => request<{ key: Key }>('POST', `/api/keys/${keyId}/copies`),
  retire: (copyId: number, retired: boolean) => request<{ changed: boolean }>('PATCH', `/api/copies/${copyId}`, { retired }),
  staff: () => request<{ staff: Staff[] }>('GET', '/api/staff'),
  createStaff: (b: { name: string; department: string }) => request<{ staff: Staff }>('POST', '/api/staff', b),
  issue: (copy_id: number, staff_id: number, due_at: string) => request<{ loan: Loan; created: boolean }>('POST', '/api/key-loans', { copy_id, staff_id, due_at }),
  giveBack: (id: number) => request<{ loan: Loan; changed: boolean }>('POST', `/api/key-loans/${id}/return`),
  loans: (status: 'active' | 'overdue' | 'returned' | 'all') => request<{ loans: Loan[]; now: string }>('GET', `/api/key-loans?status=${status}`),
  events: (f: EventFilter, offset = 0) => request<{ total: number; events: EventRow[] }>('GET', `/api/events?${qs({ ...f, limit: 100, offset })}`),
  csvUrl: (f: EventFilter) => `./api/events.csv?${qs(f)}`,
};
