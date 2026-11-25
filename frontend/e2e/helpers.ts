import { expect, type Browser, type Page } from '@playwright/test';

export const PASS: Record<string, string> = { admin: 'admin-demo', duty: 'duty-demo', duty2: 'duty-demo' };

export async function resetDemo(page: Page): Promise<void> {
  expect((await page.request.post('/api/auth/login', { data: { username: 'admin', password: PASS.admin } })).ok()).toBeTruthy();
  expect((await page.request.post('/api/demo/reset')).ok()).toBeTruthy();
  await page.request.post('/api/auth/logout');
}

export async function loginAs(page: Page, username: string, hash = '#keys'): Promise<void> {
  await page.goto(`/${hash}`);
  // Сначала дождаться, что приложение решило, вошли мы или нет: isVisible() не ждёт, и при медленной
  // проверке сессии helper искал поле «Логин» на уже открытом рабочем экране.
  const out = page.getByRole('button', { name: 'Выйти' });
  await expect(out.or(page.getByLabel('Логин'))).toBeVisible();
  if (await out.isVisible()) await out.click();
  await page.getByLabel('Логин').fill(username);
  await page.getByLabel('Пароль').fill(PASS[username]!);
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page.getByTestId('whoami')).toBeVisible();
}

export async function newUser(browser: Browser, username: string, hash = '#keys'): Promise<Page> {
  const p = await (await browser.newContext()).newPage();
  await loginAs(p, username, hash);
  return p;
}

export const keyCard = (page: Page, label: string) => page.locator(`[data-testid="key"][data-label="${label}"]`);
export const copyRow = (page: Page, name: string) => page.locator(`[data-testid="copy"][data-copy="${name}"]`);

/** Локальное время для datetime-local: смещение от «сейчас» в минутах. */
export function localInput(offsetMin: number): string {
  const d = new Date(Date.now() + offsetMin * 60000);
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}
