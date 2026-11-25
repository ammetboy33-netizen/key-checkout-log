import { expect, test } from '@playwright/test';
import { copyRow, loginAs, resetDemo } from './helpers';

test.beforeEach(async ({ page }) => resetDemo(page));

test('сессия потеряна: вход с объяснением, затем работа продолжается', async ({ page, context }) => {
  await loginAs(page, 'duty');
  await context.clearCookies();
  await copyRow(page, 'К-202 №1').getByRole('button', { name: 'Выдать К-202 №1' }).click();
  await page.getByLabel('Кому').selectOption({ label: 'Анна Белова · Бухгалтерия' });
  await page.getByRole('button', { name: 'Выдать К-202 №1', exact: true }).click();
  await expect(page.getByText('Сессия закончилась, войдите снова')).toBeVisible();
  await page.getByLabel('Логин').fill('duty');
  await page.getByLabel('Пароль').fill('duty-demo');
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(copyRow(page, 'К-202 №1')).toContainText('свободен');
});

test('сервер недоступен: сообщение вместо пустого экрана', async ({ page }) => {
  await loginAs(page, 'duty');
  await page.route('**/api/key-loans?*', (r) => r.abort());
  await page.getByRole('link', { name: 'Выдано' }).click();
  await expect(page.getByRole('alert')).toHaveText('Сервер недоступен. Проверьте, что контейнер запущен, и повторите.');
});

test('ответ на возврат потерян: повторное нажатие не создаёт второй возврат', async ({ page }) => {
  await loginAs(page, 'duty', '#active');
  await page.route('**/api/key-loans/*/return', async (route) => {
    await route.fetch();
    await route.abort();
  });
  await page.getByRole('button', { name: 'Принять возврат: К-102 №1' }).click();
  await expect(page.getByRole('alert')).toContainText('Сервер недоступен');
  await page.unroute('**/api/key-loans/*/return');
  await page.getByRole('button', { name: 'Принять возврат: К-102 №1' }).click();
  await expect(page.getByTestId('notice')).toHaveText('К-102 №1 уже был возвращён');
  await page.getByRole('link', { name: 'История' }).click();
  await page.getByLabel('Ключ', { exact: true }).selectOption({ label: 'К-102 · Склад «Б-2»' });
  await page.getByLabel('Операция', { exact: true }).selectOption({ label: 'возврат' });
  await expect(page.getByTestId('event')).toHaveCount(1);
});
