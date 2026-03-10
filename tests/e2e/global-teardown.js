const { request } = require("@playwright/test");

const ADMIN_USERNAME = process.env.PLAYWRIGHT_USERNAME || "Administrator";
const ADMIN_PASSWORD = process.env.PLAYWRIGHT_PASSWORD || "123";

module.exports = async () => {
	const baseURL = process.env.PLAYWRIGHT_BASE_URL || "http://localhost:8002";
	const requestContext = await request.newContext({ baseURL });

	try {
		const loginResponse = await requestContext.post("/api/method/login", {
			form: {
				usr: ADMIN_USERNAME,
				pwd: ADMIN_PASSWORD,
			},
		});
		if (!loginResponse.ok()) {
			console.warn("Playwright global teardown login failed; reserved E2E cleanup skipped.");
			return;
		}

		const cleanupResponse = await requestContext.post(
			"/api/method/production_entry_app.production_entry_app.api.cleanup_reserved_e2e_artifacts"
		);
		if (!cleanupResponse.ok()) {
			console.warn("Playwright global teardown reserved E2E cleanup failed.");
		}
	} finally {
		await requestContext.dispose();
	}
};
