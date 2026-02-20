async function retryOnContextDestroyed(page, action, retries = 3) {
	for (let attempt = 0; attempt < retries; attempt += 1) {
		try {
			return await action();
		} catch (error) {
			const message = String(error?.message || "");
			if (!message.includes("Execution context was destroyed") || attempt === retries - 1) {
				throw error;
			}
			await page
				.waitForFunction(() => Boolean(window.cur_frm?.doc), { timeout: 5000 })
				.catch(() => {});
		}
	}
}

async function callFrappeMethod(page, method, args = {}) {
	const csrfToken = await page.evaluate(() => window.frappe?.csrf_token || "");
	const response = await page.request.post(`/api/method/${method}`, {
		form: args,
		headers: {
			"X-Frappe-CSRF-Token": csrfToken,
		},
	});
	let payload = {};
	try {
		payload = await response.json();
	} catch (error) {
		payload = {};
	}

	if (!response.ok() || payload.exc || payload.exception) {
		const details = [
			payload?.exception,
			payload?.exc,
			payload?._error_message,
			payload?._server_messages,
		]
			.filter(Boolean)
			.join(" | ");
		throw new Error(details || `Frappe call failed: ${method}`);
	}

	return payload.message;
}

async function getDoc(page, doctype, name) {
	return await callFrappeMethod(page, "frappe.client.get", { doctype, name });
}

async function setFieldValue(page, fieldname, value) {
	await retryOnContextDestroyed(page, async () => {
		await page.waitForFunction(() => Boolean(window.cur_frm?.doc));
		await page.evaluate(
			async ({ key, val }) => {
				await cur_frm.set_value(key, val);
			},
			{ key: fieldname, val: value }
		);
	});
}

async function saveForm(page, action = "Save") {
	try {
		await page.evaluate(
			async ({ requestedAction }) => {
				await cur_frm.save(requestedAction);
			},
			{ requestedAction: action }
		);
	} catch (error) {
		const message = String(error?.message || "");
		if (!message.includes("Execution context was destroyed")) {
			throw error;
		}
	}
	await page.waitForFunction(() => Boolean(window.cur_frm?.doc), { timeout: 10000 });
}

module.exports = {
	callFrappeMethod,
	getDoc,
	retryOnContextDestroyed,
	setFieldValue,
	saveForm,
};
