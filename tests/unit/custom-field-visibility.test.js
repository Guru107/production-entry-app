const test = require("node:test");
const assert = require("node:assert/strict");

function loadVisibilityModule(fieldMap, enabled, frappeOverrides = {}) {
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
	global.frappe = { ui: { form: { on() {} } }, ...frappeOverrides };

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

test("disabled child field visibility uses grid scope without mutating shared DocField", async () => {
	const sharedDocfield = { fieldname: "custom_pea_rejection_qty", hidden: 0 };
	const calls = [];
	const gridRows = [
		{ docfields: [{ fieldname: "custom_pea_rejection_qty", hidden: 0 }] },
		{ docfields: [{ fieldname: "custom_pea_rejection_qty", hidden: 0 }] },
	];
	const api = loadVisibilityModule(
		{ "Stock Entry Detail": ["custom_pea_rejection_qty"] },
		false,
		{
			meta: {
				get_docfield() {
					return sharedDocfield;
				},
			},
		}
	);

	try {
		await api.apply_field_visibility(
			{
				doc: { name: "STE-0001" },
				fields_dict: {
					items: {
						df: { fieldtype: "Table", options: "Stock Entry Detail" },
						grid: {
							grid_rows: gridRows,
							toggle_display(fieldname, visible) {
								calls.push(["grid.toggle_display", fieldname, visible]);
								for (const row of gridRows) {
									row.docfields.find(
										(field) => field.fieldname === fieldname
									).hidden = visible ? 0 : 1;
								}
							},
						},
					},
				},
				refresh_field(fieldname) {
					calls.push(["refresh_field", fieldname]);
				},
			},
			"Stock Entry Detail"
		);

		assert.equal(sharedDocfield.hidden, 0);
		assert.deepEqual(
			gridRows.map((row) => row.docfields[0].hidden),
			[1, 1]
		);
		assert.deepEqual(calls, [
			["grid.toggle_display", "custom_pea_rejection_qty", false],
			["refresh_field", "items"],
		]);
	} finally {
		cleanupGlobals();
	}
});
