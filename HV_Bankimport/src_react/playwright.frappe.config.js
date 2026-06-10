import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
	testDir: "./tests/frappe-e2e",
	timeout: 90_000,
	expect: { timeout: 12_000 },
	fullyParallel: false,
	workers: 1,
	retries: process.env.CI ? 1 : 0,
	reporter: [["list"]],
	use: {
		baseURL: process.env.FRAPPE_BASE_URL || "http://127.0.0.1:8080",
		trace: "on-first-retry",
		screenshot: "only-on-failure",
	},
	projects: [
		{ name: "frappe-chromium", use: { ...devices["Desktop Chrome"] } },
	],
});
