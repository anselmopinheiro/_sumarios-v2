const { test, expect } = require('playwright/test');

const targetPath = process.env.AULA_AVALIACAO_PATH || '/aula/48/avaliacao';

test('abre /aula/48/avaliacao e regista screenshot da grelha', async ({ page }, testInfo) => {
  await page.goto(targetPath, { waitUntil: 'domcontentloaded' });

  await expect(page.getByRole('heading', { name: /Avalia/i })).toBeVisible();
  await expect(page.locator('#avaliacao-tabs')).toBeVisible();
  await expect(page.locator('#save-indicator')).toBeVisible();
  await expect(page.locator('#avaliacao-frame')).toBeVisible();

  const frame = page.frameLocator('#avaliacao-frame');
  const grid = frame.locator('#avaliacao-objeto-table, #avaliacao-table').first();

  await expect(grid).toBeVisible({ timeout: 30_000 });
  await expect(frame.locator('#avaliacao-save-button')).toBeVisible();
  await expect(frame.locator('thead').first()).toBeVisible();
  await expect(frame.locator('tbody tr').first()).toBeVisible();

  const screenshotPath = testInfo.outputPath('aula-48-avaliacao.png');
  await page.screenshot({
    path: screenshotPath,
    fullPage: true,
  });

  testInfo.annotations.push({
    type: 'screenshot',
    description: screenshotPath,
  });
});
