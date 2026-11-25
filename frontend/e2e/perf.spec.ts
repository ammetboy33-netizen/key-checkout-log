import { expect, test } from '@playwright/test';
import { loginAs } from './helpers';

// Замер раунда 4. Перед запуском: docker compose exec -T app python -m app.synthetic 2000 10
// (2 000 ключей по 2 экземпляра, 40 000 закрытых выдач в истории, 400 активных, 200 просроченных).
test('2 000 ключей и 80 000 записей истории: ответы API и отклик интерфейса', async ({ page }) => {
  test.setTimeout(120_000);
  await loginAs(page, 'duty');
  const n = (await (await page.request.get('/api/keys?limit=1')).json()).total as number;
  test.skip(n < 1000, 'нет синтетических данных: python -m app.synthetic 2000 10');
  const time = async (url: string) => {
    const out: number[] = [];
    for (let i = 0; i < 15; i++) {
      const t0 = Date.now();
      const r = await page.request.get(url);
      expect(r.ok()).toBeTruthy();
      out.push(Date.now() - t0);
    }
    out.sort((a, b) => a - b);
    return { median: out[7], p90: out[13] };
  };
  const keys = await time('/api/keys?limit=50');
  const allKeysBrief = await time('/api/keys?brief=true&limit=5000');
  const freeKeys = await time('/api/keys?available=true&limit=50');
  const search = await time(`/api/keys?q=${encodeURIComponent('С-0123')}`);
  const active = await time('/api/key-loans?status=active');
  const overdue = await time('/api/key-loans?status=overdue');
  const history = await time('/api/events?limit=100');
  const byKind = await time('/api/events?kind=return&limit=100');
  const csv = await time('/api/events.csv?kind=issue');
  await expect(page.getByTestId('found')).toHaveText(`Ключей: ${n}, показаны 50`);
  const tm = Date.now();
  await page.getByRole('button', { name: 'Показать ещё 50' }).click();
  await expect(page.getByTestId('found')).toHaveText(`Ключей: ${n}, показаны 100`);
  const more = Date.now() - tm;
  const t0 = Date.now();
  await page.getByLabel('Метка, помещение или заметка').fill('С-01234');
  await expect(page.getByTestId('key')).toHaveCount(1);
  const ui = Date.now() - t0;
  console.log('PERF219', JSON.stringify({ keys: n, keysApi: keys, allKeysBrief, freeKeys, more, search, active, overdue, history, byKind, csv, ui }));
});
