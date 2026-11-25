import { expect, test } from '@playwright/test';
import { copyRow, keyCard, localInput, loginAs, newUser, resetDemo } from './helpers';

test.beforeEach(async ({ page }) => resetDemo(page));

test('приёмка ТЗ: выдача с истекшим сроком в просроченных, повторная выдача заблокирована, возврат убирает активную выдачу, история остаётся', async ({ page, browser }) => {
  await loginAs(page, 'duty');
  await copyRow(page, 'К-202 №1').getByRole('button', { name: 'Выдать К-202 №1' }).click();
  await expect(page.getByLabel('Кому')).toBeFocused();
  await page.getByLabel('Кому').selectOption({ label: 'Анна Белова · Бухгалтерия' });
  await page.getByLabel('Вернуть до').fill(localInput(-30));
  await expect(page.getByTestId('past-warning')).toHaveText('Срок уже прошёл: выдача сразу попадёт в просроченные.');
  await page.getByRole('button', { name: 'Выдать К-202 №1', exact: true }).click();
  await expect(page.getByTestId('notice')).toHaveText('К-202 №1 выдан: Анна Белова (срок уже прошёл — выдача просрочена)');
  await expect(copyRow(page, 'К-202 №1').getByTestId('holder')).toContainText('у Анна Белова (Бухгалтерия) · просрочен на');

  await page.getByRole('link', { name: 'Просрочки' }).click();
  await expect(page.locator('[data-testid="loan"][data-key="К-202 №1"]')).toContainText('просрочен на 30 мин');
  await expect(page.getByTestId('loan')).toHaveCount(2); // и демо-просрочка К-102

  // Второй дежурный в устаревшей вкладке пытается выдать тот же экземпляр.
  const other = await newUser(browser, 'duty2');
  await page.goto('/#keys');
  await copyRow(other, 'К-202 №1').waitFor();
  // Страница второго дежурного открыта после выдачи, поэтому кнопки «Выдать» там нет — проверяем запрет на сервере.
  await expect(copyRow(other, 'К-202 №1').getByRole('button', { name: 'Выдать К-202 №1' })).toHaveCount(0);
  const cid = await other.evaluate(async () => (await (await fetch('./api/keys?q=К-202')).json()).keys[0].copies[0].id as number);
  const res = await other.request.post('/api/key-loans', { data: { copy_id: cid, staff_id: 2, due_at: new Date(Date.now() + 3600000).toISOString() } });
  expect(res.status()).toBe(409);
  expect((await res.json()).message).toContain('уже выдан: Анна Белова');
  await other.context().close();

  // Возврат: активная выдача пропадает, история остаётся.
  await copyRow(page, 'К-202 №1').getByRole('button', { name: 'Принять возврат: К-202 №1' }).click();
  await expect(page.getByTestId('notice')).toHaveText('К-202 №1 принят от: Анна Белова');
  await expect(copyRow(page, 'К-202 №1')).toContainText('свободен');
  await page.getByRole('link', { name: 'Выдано' }).click();
  await expect(page.locator('[data-testid="loan"][data-key="К-202 №1"]')).toHaveCount(0);
  await page.getByRole('link', { name: 'История' }).click();
  await page.getByLabel('Ключ', { exact: true }).selectOption({ label: 'К-202 · Кабинет 7' });
  await expect(page.getByTestId('event')).toHaveCount(4); // создан, экземпляр, выдача, возврат
  await page.getByLabel('Операция', { exact: true }).selectOption({ label: 'возврат' });
  await expect(page.getByTestId('event')).toHaveCount(1);
  await expect(page.getByTestId('event')).toContainText('Анна Белова');
});

test('устаревшая страница: «Выдать» на уже выданном экземпляре — понятный отказ и обновление', async ({ page, browser }) => {
  await loginAs(page, 'duty');
  const other = await newUser(browser, 'duty2');
  await copyRow(other, 'К-202 №1').getByRole('button', { name: 'Выдать К-202 №1' }).click();
  // Первый дежурный выдаёт тот же экземпляр раньше.
  await copyRow(page, 'К-202 №1').getByRole('button', { name: 'Выдать К-202 №1' }).click();
  await page.getByLabel('Кому').selectOption({ label: 'Борис Орлов · ИТ-отдел' });
  await page.getByRole('button', { name: 'Выдать К-202 №1', exact: true }).click();
  await expect(page.getByTestId('notice')).toHaveText('К-202 №1 выдан: Борис Орлов');
  await other.getByLabel('Кому').selectOption({ label: 'Вера Седова · Отдел кадров' });
  await other.getByRole('button', { name: 'Выдать К-202 №1', exact: true }).click();
  await expect(keyCard(other, 'К-202').getByTestId('key-error')).toContainText('К-202 №1 уже выдан: Борис Орлов');
  await expect(keyCard(other, 'К-202').getByTestId('key-error')).toBeFocused();
  await expect(copyRow(other, 'К-202 №1').getByTestId('holder')).toContainText('у Борис Орлов');
  await other.context().close();
});

test('два экземпляра одного ключа выдаются разным людям; повторное «Принять возврат» — один возврат в истории', async ({ page, browser }) => {
  await loginAs(page, 'duty');
  for (const [n, who] of [
    [1, 'Анна Белова · Бухгалтерия'],
    [2, 'Дарья Котова · Отдел продаж'],
  ] as const) {
    await copyRow(page, `К-101 №${n}`).getByRole('button', { name: `Выдать К-101 №${n}` }).click();
    await page.getByLabel('Кому').selectOption({ label: who });
    await page.getByRole('button', { name: `Выдать К-101 №${n}`, exact: true }).click();
    await expect(page.getByTestId('notice')).toContainText(`К-101 №${n} выдан`);
  }
  await expect(keyCard(page, 'К-101').getByTestId('avail')).toHaveText('нет доступных');
  // Вторая вкладка с тем же списком: обе нажимают «Принять возврат».
  const other = await newUser(browser, 'duty2', '#active');
  await page.getByRole('link', { name: 'Выдано' }).click();
  await page.getByRole('button', { name: 'Принять возврат: К-101 №1' }).click();
  await expect(page.getByTestId('notice')).toHaveText('К-101 №1 принят от: Анна Белова');
  await other.getByRole('button', { name: 'Принять возврат: К-101 №1' }).click();
  await expect(other.getByTestId('notice')).toHaveText('К-101 №1 уже был возвращён');
  await other.context().close();
  await page.getByRole('link', { name: 'История' }).click();
  await page.getByLabel('Операция', { exact: true }).selectOption({ label: 'возврат' });
  await expect(page.getByTestId('event').filter({ hasText: 'Анна Белова' }).filter({ hasText: 'К-101 №1' })).toHaveCount(2); // один из демо 3 дня назад, один сейчас
});

test('администратор: новый ключ, экземпляр, списание; дежурный — без этих кнопок; экспорт CSV', async ({ page }) => {
  await loginAs(page, 'admin');
  await page.getByLabel('Метка на бирке').fill('К-401');
  await page.getByLabel('Помещение', { exact: true }).fill('Кладовая «Дуб»');
  await page.getByLabel('Экземпляров').fill('2');
  await page.getByRole('button', { name: 'Зарегистрировать' }).click();
  await expect(page.getByTestId('notice')).toHaveText('Ключ К-401 зарегистрирован, экземпляров: 2');
  await keyCard(page, 'К-401').getByRole('button', { name: 'Добавить экземпляр' }).click();
  await expect(keyCard(page, 'К-401').getByTestId('copy')).toHaveCount(3);
  await copyRow(page, 'К-401 №3').getByRole('button', { name: 'Списать' }).click();
  await expect(copyRow(page, 'К-401 №3')).toContainText('списан');
  await page.getByLabel('Метка на бирке').fill('К-401');
  await page.getByLabel('Помещение', { exact: true }).fill('Дубль');
  await page.getByRole('button', { name: 'Зарегистрировать' }).click();
  await expect(page.getByText('Метка «К-401» уже есть')).toBeVisible();
  await page.getByRole('link', { name: 'История' }).click();
  const dl = page.waitForEvent('download');
  await page.getByRole('link', { name: 'Скачать CSV' }).click();
  const d = await dl;
  expect(d.suggestedFilename()).toMatch(/^zhurnal-klyuchey-\d{8}-\d{4}\.csv$/);
  const text = (await d.createReadStream().then(async (s) => { const ch: Buffer[] = []; for await (const c of s) ch.push(c as Buffer); return Buffer.concat(ch).toString('utf8'); }));
  expect(text.startsWith('﻿Время (UTC);Операция;Ключ')).toBe(true);
  expect(text).toContain('новый ключ;К-401;Кладовая «Дуб»');
  await loginAs(page, 'duty');
  await expect(page.getByRole('button', { name: 'Добавить экземпляр' })).toHaveCount(0);
  await expect(page.getByLabel('Метка на бирке')).toHaveCount(0);
});

test('быстрый срок: «до 18:00» ставит сегодня или завтра 18:00', async ({ page }) => {
  await loginAs(page, 'duty');
  await copyRow(page, 'К-202 №1').getByRole('button', { name: 'Выдать К-202 №1' }).click();
  await page.getByRole('button', { name: 'до 18:00' }).click();
  await expect(page.getByLabel('Вернуть до')).toHaveValue(/T18:00$/);
  await page.getByRole('button', { name: 'до завтра 10:00' }).click();
  await expect(page.getByLabel('Вернуть до')).toHaveValue(/T10:00$/);
});

test('поиск и «Только доступные»', async ({ page }) => {
  await loginAs(page, 'duty');
  await page.getByLabel('Метка, помещение или заметка').fill('клен');
  await expect(page.getByTestId('key')).toHaveCount(1);
  await expect(keyCard(page, 'К-302')).toBeVisible();
  await page.getByLabel('Метка, помещение или заметка').fill('');
  await page.getByLabel('Только доступные').check();
  await expect(keyCard(page, 'К-102')).toHaveCount(0);
  await expect(page.getByTestId('key')).toHaveCount(5);
});
