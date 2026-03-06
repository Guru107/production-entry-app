const test = require("node:test");
const assert = require("node:assert/strict");

const {
	parse_time,
	format_time_display,
	format_datetime_display,
} = require("../../production_entry_app/public/js/time_entry_fields.js");

test("parse_time accepts shorthand hour and minute inputs", () => {
	assert.deepEqual(parse_time("6"), {
		hh: "06",
		mm: "00",
		frappe_time: "06:00:00",
	});
	assert.deepEqual(parse_time("06"), {
		hh: "06",
		mm: "00",
		frappe_time: "06:00:00",
	});
	assert.deepEqual(parse_time("630"), {
		hh: "06",
		mm: "30",
		frappe_time: "06:30:00",
	});
	assert.deepEqual(parse_time("0630"), {
		hh: "06",
		mm: "30",
		frappe_time: "06:30:00",
	});
	assert.deepEqual(parse_time("6:3"), {
		hh: "06",
		mm: "03",
		frappe_time: "06:03:00",
	});
	assert.deepEqual(parse_time("6:30"), {
		hh: "06",
		mm: "30",
		frappe_time: "06:30:00",
	});
	assert.deepEqual(parse_time("06:30"), {
		hh: "06",
		mm: "30",
		frappe_time: "06:30:00",
	});
	assert.deepEqual(parse_time("06:30:00"), {
		hh: "06",
		mm: "30",
		frappe_time: "06:30:00",
	});
});

test("parse_time rejects invalid values", () => {
	assert.deepEqual(parse_time("2500"), { error: "Enter a valid time in HH:MM format." });
	assert.deepEqual(parse_time("06:70"), { error: "Enter a valid time in HH:MM format." });
	assert.deepEqual(parse_time("abc"), { error: "Enter a valid time in HH:MM format." });
});

test("display formatters return shorthand-friendly values", () => {
	assert.equal(format_time_display("06:30:00"), "06:30");
	assert.equal(format_time_display("6:3"), "06:03");
	assert.equal(format_time_display(""), "");
	assert.deepEqual(format_datetime_display("2026-03-06 08:30:00"), {
		date: "2026-03-06",
		time: "08:30",
	});
	assert.deepEqual(format_datetime_display(""), { date: "", time: "" });
});
