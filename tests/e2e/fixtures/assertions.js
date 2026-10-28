const { expect } = require("@playwright/test");

const MESSAGE_SELECTORS = [
	".msgprint",
	".modal.show .msgprint",
	".modal.show .modal-body",
	'.frappe-control[data-fieldname="_error_message"]',
	".frappe-alert-message",
];

function patternPayload(pattern) {
	if (pattern instanceof RegExp) {
		return { patternSource: pattern.source, patternFlags: pattern.flags, patternLiteral: null };
	}
	return { patternSource: null, patternFlags: null, patternLiteral: String(pattern) };
}

async function dismissVisibleFrappeDialog(page) {
	await page.keyboard.press("Escape");
	await page.keyboard.press("Escape");
	const dialog = page.locator(".modal.show").first();
	if (await dialog.count()) {
		await dialog.locator(".btn-modal-close").click();
		await dialog.waitFor({ state: "hidden" });
	}
	await page.evaluate(() => {
		if (window.frappe?.msg_dialog?.hide) {
			frappe.msg_dialog.hide();
		}
	});
}

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

				function collectVisibleMessages() {
					const messages = [];
					if (document.querySelector(".modal.show")) {
						const dialogText = window.frappe?.msg_dialog?.msg_area?.text?.()?.trim();
						if (dialogText) {
							messages.push(dialogText);
						}
					}
					for (const selector of selectors) {
						for (const element of document.querySelectorAll(selector)) {
							const text = (element.innerText || element.textContent || "").trim();
							if (text && isVisible(element)) {
								messages.push(text);
							}
						}
					}
					return messages;
				}

				const messages = collectVisibleMessages();
				return messages[0] || false;
			},
			MESSAGE_SELECTORS,
			{ timeout }
		);
		return await handle.jsonValue();
	} catch (error) {
		throw new Error("No visible Frappe message found.");
	}
}

async function waitForMatchingVisibleMessage(page, pattern, timeout = 10_000) {
	const payload = patternPayload(pattern);
	try {
		const handle = await page.waitForFunction(
			({ selectors, patternSource, patternFlags, patternLiteral }) => {
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

				function messageMatches(text) {
					if (patternSource !== null) {
						return new RegExp(patternSource, patternFlags).test(text);
					}
					return text.includes(patternLiteral);
				}

				function collectVisibleMessages() {
					const messages = [];
					if (document.querySelector(".modal.show")) {
						const dialogText = window.frappe?.msg_dialog?.msg_area?.text?.()?.trim();
						if (dialogText) {
							messages.push(dialogText);
						}
					}
					for (const selector of selectors) {
						for (const element of document.querySelectorAll(selector)) {
							const text = (element.innerText || element.textContent || "").trim();
							if (text && isVisible(element)) {
								messages.push(text);
							}
						}
					}
					return messages;
				}

				for (const text of collectVisibleMessages()) {
					if (messageMatches(text)) {
						return text;
					}
				}
				return false;
			},
			{ ...payload, selectors: MESSAGE_SELECTORS },
			{ timeout }
		);
		return await handle.jsonValue();
	} catch (error) {
		throw new Error("No visible Frappe message found.");
	}
}

async function expectValidationError(page, pattern, timeout = 10_000) {
	const message = await waitForMatchingVisibleMessage(page, pattern, timeout);
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
	dismissVisibleFrappeDialog,
	expectValidationError,
	expectToast,
	waitForFormSaved,
	waitForVisibleMessage,
	waitForMatchingVisibleMessage,
};
