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
				.waitForFunction(() => Boolean(window.cur_frm?.doc), undefined, { timeout: 5000 })
				.catch(() => {});
		}
	}
}

async function getCsrfToken(page, retries = 3) {
	for (let attempt = 0; attempt < retries; attempt += 1) {
		try {
			const token = await page.evaluate(() => window.frappe?.csrf_token || "");
			if (token) {
				return token;
			}
			if (attempt === retries - 1) {
				throw new Error("Unable to read CSRF token after retries.");
			}
		} catch (error) {
			const message = String(error?.message || "");
			if (!message.includes("Execution context was destroyed") || attempt === retries - 1) {
				throw error;
			}
		}
		await page.waitForLoadState("domcontentloaded", { timeout: 5000 }).catch(() => {});
	}
	throw new Error("Unable to read CSRF token after retries.");
}

async function callFrappeMethod(page, method, args = {}) {
	const csrfToken = await getCsrfToken(page);
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
		throw new Error(details || `Frappe call failed (${response.status()}): ${method}`);
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
	for (let attempt = 0; attempt < 3; attempt += 1) {
		let contextDestroyed = false;
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
			contextDestroyed = true;
		}
		if (contextDestroyed) {
			await page.waitForLoadState("domcontentloaded", { timeout: 5000 }).catch(() => {});
		}

		try {
			await page.waitForFunction(
				({ requestedAction }) => {
					const frm = window.cur_frm;
					if (!frm?.doc) {
						return false;
					}
					if (requestedAction !== "Save") {
						return true;
					}
					const name = String(frm.doc.name || "");
					return !frm.is_new?.() && !name.startsWith("new-") && !frm.doc.__unsaved;
				},
				{ requestedAction: action },
				{ timeout: 10000 }
			);
			return;
		} catch (error) {
			const message = String(error?.message || "");
			if (
				attempt === 2 ||
				(!contextDestroyed && !message.includes("Execution context was destroyed"))
			) {
				const state = await page
					.evaluate(() => ({
						doctype: window.cur_frm?.doctype || null,
						href: window.location.href,
						isNew:
							typeof window.cur_frm?.is_new === "function"
								? window.cur_frm.is_new()
								: window.cur_frm?.is_new,
						message: window.frappe?.msg_dialog?.msg_area?.text?.() || "",
						name: window.cur_frm?.doc?.name || null,
						route: window.frappe?.get_route_str?.() || null,
						unsaved: window.cur_frm?.doc?.__unsaved,
					}))
					.catch(() => ({ href: page.url() }));
				if (attempt < 2 && action === "Save" && state.isNew && !state.message) {
					await page.waitForTimeout(500);
					continue;
				}
				error.message = `${message} Last form state: ${JSON.stringify(state)}`;
				throw error;
			}
			await page.waitForLoadState("domcontentloaded", { timeout: 5000 }).catch(() => {});
			await page
				.waitForFunction(() => Boolean(window.cur_frm?.doc), { timeout: 5000 })
				.catch(() => {});
		}
	}
}

module.exports = {
	callFrappeMethod,
	getDoc,
	retryOnContextDestroyed,
	setFieldValue,
	saveForm,
};
