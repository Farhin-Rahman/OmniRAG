// @ts-check
import { test, expect } from "@playwright/test";

/**
 * Baseline smoke tests that don't require a signed-in Firebase session,
 * unlike dropdown-menu.spec.js (which needs a real session to reach the
 * chat sidebar it tests). These exist so there's at least some coverage
 * that reliably runs in a clean browser context — no auth emulator, no
 * seeded account.
 */

test.describe("Unauthenticated app shell", () => {
    test("root redirects to /auth", async ({ page }) => {
        await page.goto("/");
        await expect(page).toHaveURL(/\/auth$/);
    });

    test("auth page renders the sign-in form", async ({ page }) => {
        await page.goto("/auth");
        await expect(page.getByText("Welcome")).toBeVisible();
        await expect(page.getByRole("tab", { name: "Sign In" })).toBeVisible();
        await expect(page.getByRole("tab", { name: "Sign Up" })).toBeVisible();
    });

    test("chat route redirects unauthenticated users to /auth", async ({ page }) => {
        await page.goto("/chat");
        await expect(page).toHaveURL(/\/auth$/);
    });

    test("unknown route shows the not-found page", async ({ page }) => {
        await page.goto("/this-route-does-not-exist");
        await expect(page.locator("body")).not.toBeEmpty();
        // Not asserting page content beyond "didn't crash" — NotFound.tsx's
        // copy isn't a contract worth pinning a test to.
        await expect(page).toHaveURL(/\/this-route-does-not-exist$/);
    });
});
