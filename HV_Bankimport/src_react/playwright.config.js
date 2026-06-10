import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
	testDir: "./tests/e2e",
	timeout: 30_000,
	expect: { timeout: 8_000 },
	fullyParallel: true,
	retries: process.env.CI ? 1 : 0,
	reporter: [["list"]],
	use: {
		baseURL: "http://127.0.0.1:4177",
		trace: "on-first-retry",
		screenshot: "only-on-failure",
	},
	projects: [
		{ name: "chromium", use: { ...devices["Desktop Chrome"] } },
		{ name: "mobile", use: { ...devices["Pixel 7"] } },
	],
	webServer: {
		command: "npm run dev -- --host 127.0.0.1 --port 4177",
		url: "http://127.0.0.1:4177",
		reuseExistingServer: !process.env.CI,
		timeout: 60_000,
	},
});
