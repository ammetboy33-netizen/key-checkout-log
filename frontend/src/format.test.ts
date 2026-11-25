import { describe, expect, it } from 'vitest';
import { dayToIso, defaultDue, dueText, localToIso, span } from './format';

describe('format', () => {
  it('span и dueText: строго позже срока — просрочка', () => {
    expect(span(40 * 60000)).toBe('40 мин');
    expect(span(125 * 60000)).toBe('2 ч 5 мин');
    expect(span(52 * 3600000)).toBe('2 дн 4 ч');
    expect(dueText('2030-01-01T12:00:00Z', '2030-01-01T12:00:00Z').overdue).toBe(false);
    expect(dueText('2030-01-01T12:00:00Z', '2030-01-01T12:00:01Z').overdue).toBe(true);
    expect(dueText('2030-01-01T12:00:00Z', '2030-01-01T14:05:00Z').text).toBe('просрочен на 2 ч 5 мин');
  });
  it('defaultDue: через 4 часа, вверх до 15 минут; переход через полночь', () => {
    expect(defaultDue(new Date(2030, 0, 1, 9, 2))).toBe('2030-01-01T13:15');
    expect(defaultDue(new Date(2030, 0, 1, 21, 50))).toBe('2030-01-02T02:00');
  });
  it('localToIso и dayToIso', () => {
    expect(localToIso('2030-01-01T13:15')).toBe(new Date(2030, 0, 1, 13, 15).toISOString());
    expect(localToIso('')).toBeNull();
    expect(dayToIso('2030-01-31', true)).toBe(new Date(2030, 1, 1).toISOString());
    expect(dayToIso('31.01.2030')).toBeUndefined();
  });
});
