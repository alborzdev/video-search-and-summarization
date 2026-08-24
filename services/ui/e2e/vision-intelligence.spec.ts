import { expect, test, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const workspaces = ['Home', 'Live', 'Monitoring', 'Explore', 'Events', 'Capabilities', 'System'] as const;
const faultsByPage = new WeakMap<Page, string[]>();

function pageFaults(page: Page): string[] {
  const faults: string[] = [];
  faultsByPage.set(page, faults);
  return faults;
}

function recordRuntimeFaults(page: Page): void {
  const faults = pageFaults(page);

  page.on('pageerror', (error) => faults.push(`pageerror: ${error.message}`));
  page.on('console', (message) => {
    if (message.type() === 'error') faults.push(`console: ${message.text()}`);
  });
  page.on('response', (response) => {
    if (response.status() >= 400) {
      faults.push(`response ${response.status()}: ${response.url()}`);
    }
  });
  page.on('requestfailed', (request) => {
    const failure = request.failure()?.errorText;
    if (failure && failure !== 'net::ERR_ABORTED') {
      faults.push(`request failed: ${request.url()} (${failure})`);
    }
  });
}

async function openApp(page: Page, path = '/'): Promise<void> {
  await page.goto(path, { waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('navigation', { name: 'Primary navigation' })).toBeVisible();
  await expect(page.locator('.vi-app')).toBeVisible();
}

async function expectWorkspace(page: Page, workspace: (typeof workspaces)[number]): Promise<void> {
  const navigation = page.getByRole('navigation', { name: 'Primary navigation' });
  const item = navigation.getByRole('button', { name: workspace, exact: true });
  await item.click();
  await expect(item).toHaveAttribute('aria-current', 'page');
  await expect(page).toHaveURL(new RegExp(`[?&]workspace=${workspace.toLowerCase()}(?:&|$)`));
}

async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  const dimensions = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));

  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);
}

test.beforeEach(({ page }) => recordRuntimeFaults(page));

test.afterEach(({ page }) => {
  expect(faultsByPage.get(page) ?? [], 'browser runtime faults').toEqual([]);
});

test('renders a meaningful VSS UI without a framework error overlay', async ({ page }) => {
  await openApp(page);

  await expect(page).toHaveTitle(/\S/);
  await expect(page.locator('body')).not.toHaveText(/^\s*$/);
  await expect(page.getByRole('navigation', { name: 'Primary navigation' }).getByRole('button')).toHaveCount(7);
  await expect(page.locator('nextjs-portal, [data-nextjs-dialog-overlay], [data-nextjs-dialog]')).toHaveCount(0);
});

test('desktop navigation opens every primary workspace', async ({ page }) => {
  await openApp(page);

  for (const workspace of workspaces) {
    await expectWorkspace(page, workspace);
  }
});

test('workspace deep links remain stable through browser history', async ({ page }) => {
  await openApp(page, '/?workspace=events&source=playwright');
  const navigation = page.getByRole('navigation', { name: 'Primary navigation' });

  await expect(navigation.getByRole('button', { name: 'Events', exact: true })).toHaveAttribute('aria-current', 'page');
  await expectWorkspace(page, 'Explore');
  await expect(page).toHaveURL(/source=playwright/);

  await page.goBack();
  await expect(navigation.getByRole('button', { name: 'Events', exact: true })).toHaveAttribute('aria-current', 'page');
  await expect(page).toHaveURL(/workspace=events/);

  await page.goForward();
  await expect(navigation.getByRole('button', { name: 'Explore', exact: true })).toHaveAttribute('aria-current', 'page');
  await expect(page).toHaveURL(/workspace=explore/);
});

test('mobile bottom navigation exposes every workspace without horizontal body overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openApp(page);

  const navigation = page.getByRole('navigation', { name: 'Primary navigation' });
  const navBox = await navigation.boundingBox();
  expect(navBox, 'mobile bottom navigation bounding box').not.toBeNull();
  expect((navBox?.y ?? 0) + (navBox?.height ?? 0)).toBeGreaterThan(760);

  for (const workspace of workspaces) {
    const item = navigation.getByRole('button', { name: workspace, exact: true });
    await item.scrollIntoViewIfNeeded();
    await expect(item).toBeVisible();
    await expectWorkspace(page, workspace);
    await expectNoHorizontalOverflow(page);
  }
});

test('readiness popover and appearance menu open without changing app data', async ({ page }) => {
  await openApp(page);

  const readiness = page.getByRole('button', { name: 'System readiness', exact: true });
  await readiness.click();
  await expect(readiness).toHaveAttribute('aria-expanded', 'true');
  await expect(page.getByLabel('System readiness details')).toBeVisible();
  await page.getByRole('button', { name: 'Close system readiness' }).click();
  await expect(page.getByLabel('System readiness details')).toBeHidden();

  const appearance = page.getByRole('button', { name: /^Appearance:/ });
  await appearance.click();
  await expect(appearance).toHaveAttribute('aria-expanded', 'true');
  const menu = page.getByRole('menu', { name: 'Appearance options' });
  await expect(menu).toBeVisible();
  await expect(menu.getByRole('menuitemradio')).toHaveCount(3);
  await appearance.click();
  await expect(menu).toBeHidden();
});

test('primary workspaces have no serious or critical WCAG violations', async ({ page }) => {
  test.setTimeout(60_000);
  await openApp(page);

  for (const workspace of workspaces) {
    await expectWorkspace(page, workspace);
    const result = await new AxeBuilder({ page })
      .include('.vi-app')
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
      .analyze();
    const blockingViolations = result.violations.filter(
      (violation) => violation.impact === 'serious' || violation.impact === 'critical',
    );
    expect(blockingViolations, `${workspace} accessibility violations`).toEqual([]);
  }
});

test('dark theme primary workspaces have no serious or critical WCAG violations', async ({ page }) => {
  test.setTimeout(60_000);
  await openApp(page);

  const appearance = page.getByRole('button', { name: /^Appearance:/ });
  await appearance.click();
  await page
    .getByRole('menu', { name: 'Appearance options' })
    .getByRole('menuitemradio', { name: 'Dark' })
    .click();
  await expect(page.locator('.vi-app')).toHaveAttribute('data-theme', 'dark');

  for (const workspace of workspaces) {
    await expectWorkspace(page, workspace);
    const result = await new AxeBuilder({ page })
      .include('.vi-app')
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
      .analyze();
    const blockingViolations = result.violations.filter(
      (violation) => violation.impact === 'serious' || violation.impact === 'critical',
    );
    expect(blockingViolations, `${workspace} dark-theme accessibility violations`).toEqual([]);
  }
});

test('monitoring dialog closes with Escape when the dialog is available', async ({ page }) => {
  await openApp(page, '/?workspace=monitoring');
  const trigger = page.getByRole('button', { name: 'New monitoring rule' });

  test.skip(!(await trigger.isVisible()), 'Monitoring dialog is not available in this deployment.');
  await trigger.click();

  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
});
