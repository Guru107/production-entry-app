const { cleanupE2E } = require("./test-data");
const { e2ePrefix } = require("./prefix");

function registerE2ELifecycle(test, options = {}) {
	const { navigateHomeBeforeCleanup = true } = options;
	let prefix = "E2E";

	test.beforeEach(async (_args, testInfo) => {
		prefix = e2ePrefix(testInfo);
	});

	test.afterEach(async ({ page }) => {
		if (navigateHomeBeforeCleanup) {
			await page.goto("/app/home");
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
