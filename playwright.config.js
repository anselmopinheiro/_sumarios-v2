const { defineConfig } = require('playwright/test');

const port = process.env.PLAYWRIGHT_PORT || '5000';
const baseURL = process.env.PLAYWRIGHT_BASE_URL || `http://127.0.0.1:${port}`;
const shouldStartServer = process.env.PLAYWRIGHT_SKIP_WEBSERVER !== '1';

module.exports = defineConfig({
  testDir: './tests/playwright',
  timeout: 60_000,
  expect: {
    timeout: 15_000,
  },
  fullyParallel: false,
  reporter: [['list']],
  outputDir: 'test-results/playwright',
  use: {
    baseURL,
    headless: true,
    viewport: { width: 1440, height: 980 },
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  webServer: shouldStartServer
    ? {
        command: 'python app.py',
        url: `${baseURL}/health`,
        reuseExistingServer: true,
        timeout: 120_000,
        env: {
          ...process.env,
          FLASK_DEBUG: '0',
          FLASK_USE_RELOADER: '0',
          SKIP_DB_BOOTSTRAP: process.env.SKIP_DB_BOOTSTRAP || '1',
        },
      }
    : undefined,
});
