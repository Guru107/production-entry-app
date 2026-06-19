const { expect } = require("@playwright/test");

const MESSAGE_SELECTORS = [
	".modal.show .msgprint",
	".modal.show .modal-body",
	'.frappe-control[data-fieldname="_error_message"]',
	".frappe-alert-message",
];

async function waitForVisibleMessage(page, timeout = 10_000) {
	try {
		const handle = await page.waitForFunction(
			(selectors) => {
				function isVisible(element) {
					const rect = element.getBoundingClientRect();
					const style = window.getComputedStyle(element);
					return (
						rect.width > 0 &&
						rect.height > 0 &&
						style.display !== "none" &&
						style.visibility !== "hidden"
					);
				}

				for (const selector of selectors) {
					for (const element of document.querySelectorAll(selector)) {
						const text = (element.innerText || element.textContent || "").trim();
						if (text && isVisible(element)) {
							return text;
						}
					}
				}
				return false;
			},
			MESSAGE_SELECTORS,
			{ timeout }
		);
		return await handle.jsonValue();
	} catch (error) {
		throw new Error("No visible Frappe message found.");
	}
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
