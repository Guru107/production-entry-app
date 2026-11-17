const test = require("node:test");
const assert = require("node:assert/strict");

global.window = global.window || {};
const {
	render_shift_timeline,
	_start_timeline_animation_if_running,
} = require("../../production_entry_app/public/js/timeline_renderer.js");

function installFrappe(t) {
	const calls = [];
	const originals = { frappe: global.frappe, __: global.__, raf: global.requestAnimationFrame };
	global.__ = (text) => text;
	global.frappe = { call: (options) => calls.push(options), utils: { escape_html: String } };
	t.after(() => {
		global.frappe = originals.frappe;
		global.__ = originals.__;
		global.requestAnimationFrame = originals.raf;
	});
	return calls;
}

function makeFrm(name, isNew = false) {
	return { doc: { name }, is_new: () => isNew, fields_dict: {} };
}

function installFrames() {
	const frames = [];
	global.requestAnimationFrame = (callback) => frames.push(callback);
	return frames;
}

test("render_shift_timeline skips the server call for an unsaved doc", (t) => {
	const calls = installFrappe(t);

	render_shift_timeline(makeFrm("new-workstation-abc", true), "Workstation", "timeline");

	assert.equal(calls.length, 0);
});

test("render_shift_timeline ignores a response for a previously open doc", (t) => {
	const calls = installFrappe(t);
	const frm = makeFrm("WS-A");
	render_shift_timeline(frm, "Workstation", "timeline");
	assert.equal(calls[0].args.docname, "WS-A");

	frm.doc.name = "WS-B";
	// Rendering would throw (frappe.utils.get_form_link etc. are absent); a dropped response does not.
	calls[0].callback({ message: { shift_name: "SHIFT-1" } });
	calls[0].error();
});

test("timeline animation stops for good once the canvas is detached", (t) => {
	installFrappe(t);
	const frames = installFrames();
	const canvas = { isConnected: true, offsetParent: {} };
	const state = { stopped: false };
	let renders = 0;
	const now = Date.now();

	_start_timeline_animation_if_running(
		state,
		() => renders++,
		new Date(now - 1000),
		new Date(now + 60000),
		canvas
	);
	frames.shift()();
	assert.equal(renders, 1);

	canvas.isConnected = false;
	frames.shift()();

	assert.equal(renders, 1);
	assert.equal(state.stopped, true);
	assert.equal(frames.length, 0);
});

test("timeline animation stops once the shift window has ended", (t) => {
	installFrappe(t);
	const frames = installFrames();
	const state = { stopped: false };
	const now = Date.now();

	_start_timeline_animation_if_running(
		state,
		() => assert.fail("must not render"),
		new Date(now - 1000),
		new Date(now + 20),
		{ isConnected: true, offsetParent: {} }
	);
	const realNow = Date.now;
	t.after(() => {
		Date.now = realNow;
	});
	Date.now = () => now + 1000;
	frames.shift()();

	assert.equal(state.stopped, true);
});
