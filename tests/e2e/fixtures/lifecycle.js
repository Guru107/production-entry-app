const { cleanupE2E } = require("./test-data");
const { e2ePrefix } = require("./prefix");
const { getRoute } = require("../utils/routing");

const ADMIN_USERNAME = process.env.PLAYWRIGHT_ADMIN_USERNAME || "Administrator";
const ADMIN_PASSWORD = process.env.PLAYWRIGHT_ADMIN_PASSWORD || "123";

async function loginAsAdmin(page) {
	const response = await page.request.post("/api/method/login", {
		form: {
			usr: ADMIN_USERNAME,
			pwd: ADMIN_PASSWORD,
		},
	});
	if (!response.ok()) {
		throw new Error("Unable to login as administrator for E2E cleanup.");
	}
}

function registerE2ELifecycle(test, options = {}) {
	const { navigateHomeBeforeCleanup = true } = options;
	let prefix = "E2E";

	test.beforeEach(async ({ page: _page }, testInfo) => {
		prefix = e2ePrefix(testInfo);
	});

	test.afterEach(async ({ page }) => {
		await loginAsAdmin(page);
		if (navigateHomeBeforeCleanup) {
			await page.goto(getRoute("/home"));
		}
		await cleanupE2E(page, prefix);
	});

	return {
		getPrefix() {
			return prefix;
		},
	};
}

module.exports = { registerE2ELifecycle };
