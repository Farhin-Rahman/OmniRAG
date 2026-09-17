// @ts-check
import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright configuration for OmniRAG frontend tests.
 * @see https://playwright.dev/docs/test-configuration
 */
export default defineConfig({
    testDir: "./tests",
    fullyParallel: true,
    forbidOnly: !!process.env.CI,
    retries: process.env.CI ? 2 : 0,
    workers: process.env.CI ? 1 : undefined,
    reporter: "html",
    use: {
        // Matches the actual Vite dev server port (vite.config.ts), not the
        // create-react-app default this was apparently copied from — the
        // mismatch meant this config could never have reached a running
        // app; confirmed while auditing test coverage.
        baseURL: "http://localhost:8000",
        trace: "on-first-retry",
        screenshot: "only-on-failure",
    },

    projects: [
        {
            name: "chromium",
            use: { ...devices["Desktop Chrome"] },
        },
    ],

    /* Run local dev server before starting tests */
    webServer: {
        command: "npm run dev",
        url: "http://localhost:8000",
        reuseExistingServer: !process.env.CI,
        timeout: 120 * 1000,
    },
});
