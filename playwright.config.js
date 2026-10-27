const { defineConfig, devices } = require("@playwright/test");
try {
	require("dotenv").config();
} catch (error) {
	// Optional for local runs; CI injects env vars directly.
}

const baseURL = process.env.PLAYWRIGHT_BASE_URL || "http://localhost:8002";

module.exports = defineConfig({
	testDir: "./tests/e2e/specs",
	globalTeardown: "./tests/e2e/global-teardown.js",
	fullyParallel: true, // test-level shard balancing (file-level put reports+joint on one shard); workers: 1 keeps in-job execution serial
	workers: 1,
	timeout: 90_000,
	expect: {
		timeout: 10_000,
	},
	reporter: [["list"], ["html", { outputFolder: "playwright-report", open: "never" }]],
	use: {
		baseURL,
		trace: "on-first-retry",
		video: "retain-on-failure",
		screenshot: "only-on-failure",
	},
	retries: process.env.CI ? 1 : 0,
	projects: [
		{
			name: "setup",
			testMatch: /auth\.setup\.spec\.js/,
		},
		{
			name: "chromium",
			use: {
				...devices["Desktop Chrome"],
				storageState: "tests/e2e/.auth/admin.json",
			},
			dependencies: ["setup"],
			testIgnore: /auth\.setup\.spec\.js/,
		},
	],
});
