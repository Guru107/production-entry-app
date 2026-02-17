const { expect } = require("@playwright/test");

const MESSAGE_SELECTORS = [
	".modal.show .msgprint",
	".modal.show .modal-body",
	'.frappe-control[data-fieldname="_error_message"]',
	".frappe-alert-message",
];

async function waitForVisibleMessage(page, timeout = 10_000) {
	for (const selector of MESSAGE_SELECTORS) {
		const locator = page.locator(selector).first();
		try {
			await locator.waitFor({ state: "visible", timeout });
			const text = (await locator.textContent()) || "";
			if (text.trim()) {
				return text.trim();
			}
		} catch (error) {
			// Try the next selector.
		}
	}
	throw new Error("No visible Frappe message found.");
}

async function expectValidationError(page, pattern, timeout = 10_000) {
	const message = await waitForVisibleMessage(page, timeout);
	if (pattern instanceof RegExp) {
		expect(message).toMatch(pattern);
	} else {
		expect(message).toContain(pattern);
	}
	return message;
}

async function expectToast(page, pattern, timeout = 10_000) {
	const toast = page.locator(".frappe-alert-message").first();
	await toast.waitFor({ state: "visible", timeout });
	const message = ((await toast.textContent()) || "").trim();
	if (pattern instanceof RegExp) {
		expect(message).toMatch(pattern);
	} else {
		expect(message).toContain(pattern);
	}
	return message;
}

async function waitForFormSaved(page, timeout = 10_000) {
	await page.waitForFunction(() => Boolean(window.cur_frm?.doc), undefined, { timeout });
	await page.waitForFunction(() => !window.cur_frm?.is_dirty?.(), undefined, { timeout });
}

module.exports = {
	expectValidationError,
	expectToast,
	waitForFormSaved,
	waitForVisibleMessage,
};
