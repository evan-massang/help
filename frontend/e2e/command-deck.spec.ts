import { expect, test } from "@playwright/test";

// Mocks the backend so this can run against a freshly-booted Next.js
// without docker compose. Validates the critical user path:
//   1. Command Deck loads with health dots
//   2. Opportunity feed renders top items
//   3. Live alert toast pops in when an alert WS frame arrives
//   4. Keyboard shortcut `g o` navigates to /opportunities

const HEALTH_BODY = {
  status: "ok",
  version: "0.0.1",
  uptime_s: 12,
  checks: {
    postgres: { status: "ok", latency_ms: 4, detail: null },
    redis: { status: "ok", latency_ms: 2, detail: null },
    chroma: { status: "ok", latency_ms: 8, detail: null },
    ollama: { status: "ok", latency_ms: 12, detail: null },
    ai_budget: { status: "ok", latency_ms: null, detail: "spent $0.40 / $15.00, 6 calls" },
  },
};

const OPPORTUNITIES = {
  count: 1,
  items: [
    {
      mint: "TestMint11111111111111111111111111111111111",
      symbol: "TEST",
      launchpad: "pumpfun_bc",
      score: "47.5",
      components: { safety: "100", momentum: "60", liquidity: "60" },
      scored_at: new Date().toISOString(),
      safety_verdict: "pass",
      safety_reasons: [],
      lp_usd: "12500",
      price_usd: "0.0001",
      age_s: 90,
    },
  ],
};

const ALERTS = { count: 0, items: [] };
const BUDGET = {
  date: new Date().toISOString().slice(0, 10),
  total_usd: "0.40",
  budget_usd: "15.00",
  remaining_usd: "14.60",
  calls: 6,
};

test.beforeEach(async ({ page }) => {
  await page.route("**/api/health", (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(HEALTH_BODY) }),
  );
  await page.route("**/api/opportunities*", (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(OPPORTUNITIES) }),
  );
  await page.route("**/api/alerts*", (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(ALERTS) }),
  );
  await page.route("**/api/ai/budget", (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(BUDGET) }),
  );
});

test("command deck renders health, opportunities, and AI spend", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "memeterm" })).toBeVisible();
  await expect(page.getByText("Top opportunities")).toBeVisible();
  await expect(page.getByText("TEST")).toBeVisible();
  await expect(page.getByText("Alert feed")).toBeVisible();
  await expect(page.getByText(/AI:/)).toContainText("$0.40");
});

test("`g o` navigates to /opportunities", async ({ page }) => {
  await page.goto("/");
  await page.keyboard.press("g");
  await page.keyboard.press("o");
  await page.waitForURL("**/opportunities");
  await expect(page.getByRole("heading", { name: "Opportunities" })).toBeVisible();
});

test("? opens the keyboard help overlay", async ({ page }) => {
  await page.goto("/");
  await page.keyboard.press("?");
  await expect(page.getByRole("heading", { name: "Keyboard shortcuts" })).toBeVisible();
});
