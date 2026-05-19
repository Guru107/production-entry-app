const test = require("node:test");
const assert = require("node:assert/strict");

function loadVisibilityModule(fieldMap, enabled) {
	const modulePath = "../../production_entry_app/public/js/custom_field_visibility.js";
	delete require.cache[require.resolve(modulePath)];

	global.window = {
		production_entry_app: {
			generated_access_control_field_map: fieldMap,
			access_control: {
				async when_ready() {
					return { enabled };
				},
			},
		},
	};
	global.frappe = { ui: { form: { on() {} } } };

	return require(modulePath);
}

function cleanupGlobals() {
	delete global.window;
	delete global.frappe;
}

test("enabled access does not force parent Stock Entry fields visible", async () => {
	const calls = [];
	const api = loadVisibilityModule({ "Stock Entry": ["custom_pea_shift"] }, true);

	try {
		await api.apply_field_visibility(
			{
				toggle_display(fieldname, visible) {
					calls.push([fieldname, visible]);
				},
			},
			"Stock Entry"
		);

		assert.deepEqual(calls, []);
	} finally {
		cleanupGlobals();
	}
});

test("disabled access still hides parent Stock Entry fields", async () => {
	const calls = [];
	const api = loadVisibilityModule({ "Stock Entry": ["custom_pea_shift"] }, false);

	try {
		await api.apply_field_visibility(
			{
				toggle_display(fieldname, visible) {
					calls.push([fieldname, visible]);
				},
			},
			"Stock Entry"
		);

		assert.deepEqual(calls, [["custom_pea_shift", false]]);
	} finally {
		cleanupGlobals();
	}
});

test("enabled access continues to show non-Stock Entry parent fields", async () => {
	const calls = [];
	const api = loadVisibilityModule({ Workstation: ["custom_pea_standard_spm"] }, true);

	try {
		await api.apply_field_visibility(
			{
				toggle_display(fieldname, visible) {
					calls.push([fieldname, visible]);
				},
			},
			"Workstation"
		);

		assert.deepEqual(calls, [["custom_pea_standard_spm", true]]);
	} finally {
		cleanupGlobals();
	}
});
