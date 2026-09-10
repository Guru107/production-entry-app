const { callFrappeMethod } = require("./frappe");

async function retryTransientRequest(action, retries = 3) {
	for (let attempt = 0; attempt < retries; attempt += 1) {
		try {
			return await action();
		} catch (error) {
			const message = String(error?.message || "");
			const isTransient =
				message.includes("socket hang up") || message.includes("ECONNRESET");
			if (!isTransient || attempt === retries - 1) {
				throw error;
			}
			await new Promise((resolve) => setTimeout(resolve, 250));
		}
	}
}

async function bootstrapE2E(page, prefix = "E2E") {
	return await retryTransientRequest(() =>
		callFrappeMethod(
			page,
			"production_entry_app.production_entry_app.e2e_api.bootstrap_e2e_context",
			{ prefix }
		)
	);
}

async function cleanupE2E(page, prefix = "E2E") {
	return await retryTransientRequest(() =>
		callFrappeMethod(
			page,
			"production_entry_app.production_entry_app.e2e_api.cleanup_e2e_context",
			{ prefix }
		)
	);
}

module.exports = {
	bootstrapE2E,
	cleanupE2E,
	retryTransientRequest,
};
