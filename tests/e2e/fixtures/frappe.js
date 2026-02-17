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
	for (let attempt = 0; attempt < 3; attempt += 1) {
		try {
			await page.waitForFunction(() => Boolean(window.cur_frm?.doc));
			await page.evaluate(
				async ({ key, val }) => {
					await cur_frm.set_value(key, val);
				},
				{ key: fieldname, val: value }
			);
			return;
		} catch (error) {
			const message = String(error?.message || "");
			if (!message.includes("Execution context was destroyed") || attempt === 2) {
				throw error;
			}
			await page.waitForLoadState("domcontentloaded");
		}
	}
}

async function saveForm(page, action = "Save") {
	await page.evaluate(
		async ({ requestedAction }) => {
			await cur_frm.save(requestedAction);
		},
		{ requestedAction: action }
	);
}

module.exports = {
	callFrappeMethod,
	getDoc,
	setFieldValue,
	saveForm,
};
