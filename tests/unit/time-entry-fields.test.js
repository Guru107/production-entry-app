const test = require("node:test");
const assert = require("node:assert/strict");

const {
	parse_time,
	format_time_display,
	format_datetime_display,
	resolve_datetime_in_window,
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

// Shift window 22:00 (D) – 06:00 (D+1); fixed-width "YYYY-MM-DD HH:MM:SS" strings compare
// lexicographically, matching the server's str(datetime) wire format.
const NIGHT_START = "2026-10-26 22:00:00";
const NIGHT_END = "2026-10-27 06:00:00";

test("resolve_datetime_in_window keeps in-window datetimes (E1 start)", () => {
	assert.equal(
		resolve_datetime_in_window("2026-10-26 23:00:00", NIGHT_START, NIGHT_END),
		"2026-10-26 23:00:00"
	);
});

test("resolve_datetime_in_window rolls after-midnight time to next day (E1 end)", () => {
	assert.equal(
		resolve_datetime_in_window("2026-10-26 02:00:00", NIGHT_START, NIGHT_END),
		"2026-10-27 02:00:00"
	);
});

test("resolve_datetime_in_window treats window end as inclusive (E2)", () => {
	assert.equal(
		resolve_datetime_in_window("2026-10-26 06:00:00", NIGHT_START, NIGHT_END),
		"2026-10-27 06:00:00"
	);
});

test("resolve_datetime_in_window rolls an after-midnight start too (E3)", () => {
	assert.equal(
		resolve_datetime_in_window("2026-10-26 02:00:00", NIGHT_START, NIGHT_END),
		"2026-10-27 02:00:00"
	);
});

test("resolve_datetime_in_window passes buffer times through unchanged (E4)", () => {
	assert.equal(
		resolve_datetime_in_window("2026-10-26 21:30:00", NIGHT_START, NIGHT_END),
		"2026-10-26 21:30:00"
	);
	assert.equal(
		resolve_datetime_in_window("2026-10-26 06:30:00", NIGHT_START, NIGHT_END),
		"2026-10-26 06:30:00"
	);
});

test("resolve_datetime_in_window leaves swapped day-shift times alone (E5)", () => {
	const start = "2026-10-26 08:00:00";
	const end = "2026-10-26 16:00:00";
	assert.equal(
		resolve_datetime_in_window("2026-10-26 16:00:00", start, end),
		"2026-10-26 16:00:00"
	);
	assert.equal(
		resolve_datetime_in_window("2026-10-26 09:00:00", start, end),
		"2026-10-26 09:00:00"
	);
});

test("resolve_datetime_in_window passes through without a window (E6/E7)", () => {
	assert.equal(resolve_datetime_in_window("2026-10-26 02:00:00", "", ""), "2026-10-26 02:00:00");
	assert.equal(resolve_datetime_in_window("2026-10-26 02:00:00"), "2026-10-26 02:00:00");
});

test("resolve_datetime_in_window normalizes T separator and month rollover", () => {
	assert.equal(
		resolve_datetime_in_window(
			"2026-10-31T23:30:00",
			"2026-10-31 22:00:00",
			"2026-11-01 06:00:00"
		),
		"2026-10-31 23:30:00"
	);
	assert.equal(
		resolve_datetime_in_window(
			"2026-10-31 02:00:00",
			"2026-10-31 22:00:00",
			"2026-11-01 06:00:00"
		),
		"2026-11-01 02:00:00"
	);
});
