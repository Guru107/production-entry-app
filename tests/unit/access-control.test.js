const test = require("node:test");
const assert = require("node:assert/strict");

function cleanupGlobals() {
	delete global.window;
	delete global.frappe;
	delete global.__;
}

test("access-control fetch errors are shown to the user", async () => {
	const modulePath = "../../production_entry_app/public/js/access_control.js";
	delete require.cache[require.resolve(modulePath)];

	const msgprintCalls = [];
	const originalWarn = console.warn;
	const originalError = console.error;

	global.__ = (message) => message;
	global.window = { production_entry_app: {} };
	global.frappe = {
		call(options) {
			options.error(new Error("Access API failed"));
		},
		msgprint(message) {
			msgprintCalls.push(message);
		},
	};
	console.warn = () => {};
	console.error = () => {};

	try {
		const api = require(modulePath);
		await api.when_ready();

		assert.equal(typeof frappe.msgprint, "function");
		assert.equal(msgprintCalls.length, 1);
		assert.match(msgprintCalls[0].message || msgprintCalls[0], /access/i);
	} finally {
		console.warn = originalWarn;
		console.error = originalError;
		cleanupGlobals();
	}
});
