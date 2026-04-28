const { defineConfig } = require("cypress");
const fs = require("fs");

module.exports = defineConfig({
	env: {
		hv_user: "hv@example.com",
		hv_password: "hv",
	},
	defaultCommandTimeout: 20000,
	pageLoadTimeout: 30000,
	video: true,
	viewportHeight: 960,
	viewportWidth: 1400,
	retries: {
		runMode: 1,
		openMode: 0,
	},
	e2e: {
		setupNodeEvents(on, config) {
			on("after:spec", (spec, results) => {
				if (results && results.video) {
					const failures = results.tests.some((test) =>
						test.attempts.some((attempt) => attempt.state === "failed")
					);
					if (!failures) {
						fs.unlinkSync(results.video);
					}
				}
			});
		},
		testIsolation: false,
		baseUrl: process.env.CYPRESS_BASE_URL || "http://frontend:8080",
		specPattern: "cypress/integration/**/*.js",
		supportFile: "cypress/support/e2e.js",
	},
});
