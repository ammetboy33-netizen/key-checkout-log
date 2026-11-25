import { expect, test } from '@playwright/test';
import { copyRow, loginAs, resetDemo } from './helpers';

test.beforeEach(async ({ page }) => resetDemo(page));

test('выдача и возврат только с клавиатуры', async ({ page }) => {
  await loginAs(page, 'duty');
  await copyRow(page, 'К-202 №1').getByRole('button', { name: 'Выдать К-202 №1' }).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByLabel('Кому')).toBeFocused();
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('Tab');
  await expect(page.getByLabel('Вернуть до')).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('notice')).toContainText('К-202 №1 выдан: Анна Белова');
  await copyRow(page, 'К-202 №1').getByRole('button', { name: 'Принять возврат: К-202 №1' }).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('notice')).toHaveText('К-202 №1 принят от: Анна Белова');
});

for (const width of [360, 320]) {
  for (const hash of ['#keys', '#active', '#history']) {
    test(`узкий экран ${width} px, ${hash}: без горизонтальной прокрутки страницы`, async ({ page }) => {
      await page.setViewportSize({ width, height: 740 });
      await loginAs(page, 'admin', hash);
      await page.waitForTimeout(150);
      expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
    });
  }
}

test('поля подписаны, кнопки не меньше 40 px', async ({ page }) => {
  await loginAs(page, 'admin');
  for (const b of await page.locator('main button, main a.btn').all()) {
    if (!(await b.isVisible())) continue;
    expect((await b.boundingBox())!.height).toBeGreaterThanOrEqual(40);
  }
  for (const l of ['Метка, помещение или заметка', 'Метка на бирке', 'Помещение', 'Экземпляров']) await expect(page.getByLabel(l, { exact: true })).toBeVisible();
});
