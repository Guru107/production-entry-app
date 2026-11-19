---
name: frappe-js-patterns
description: House rules for this app's client-side JavaScript (form scripts, public/js). Use when writing or editing any .js file in production_entry_app.
---

# JavaScript — Frappe Best Practices

### Every `frappe.call()` Must Have an `error:` Callback

Silent failures are unacceptable. Every API call must inform the user when something goes wrong:

```javascript
frappe.call({
	method: "...",
	args: { ... },
	callback(r) { /* success */ },
	error(err) {
		frappe.msgprint(__("Operation failed. Please retry or contact support."));
		console.error(err);
	},
});
```

### Debounce Repeated Triggers

When multiple field changes trigger the same server call, debounce to 300 ms to avoid
sending duplicate requests:

```javascript
let _timer = null;
function _my_handler(frm) {
	clearTimeout(_timer);
	_timer = setTimeout(() => _do_call(frm), 300);
}
```

### Last-Call-Wins for Rapid API Calls

When a user action can trigger multiple in-flight requests, use a request counter so stale
responses are discarded:

```javascript
let _reqId = 0;
function _fetch_metrics(frm) {
	const id = ++_reqId;
	frappe.call({
		...,
		callback(r) {
			if (id !== _reqId) return;   // stale — discard
			/* apply result */
		},
	});
}
```

### Animation Frame Cleanup

Always guard `requestAnimationFrame` loops with a `stopped` flag so orphaned frames cannot
re-queue themselves after a form unloads:

```javascript
const state = { stopped: false, animationFrame: null };

const animate = () => {
	if (state.stopped) return;   // checked first, every frame
	/* draw */
	state.animationFrame = requestAnimationFrame(animate);
};

// On cleanup:
state.stopped = true;
cancelAnimationFrame(state.animationFrame);
```

### i18n — All User-Visible Strings in `__()`

Every string a user can see must be wrapped in the translation function:

```javascript
// CORRECT
frappe.msgprint(__("Shift started successfully."));
ctx.fillText(__("No entries for this shift."), x, y);
`<th>${__("Workstation")}</th>`

// WRONG — hard-coded strings are not translatable
frappe.msgprint("Shift started successfully.");
```

Exceptions: CSS class names, HTML attribute names, API method paths, DocType names used as
identifiers (not displayed text), JS variable names.

### Monkey-Patching ERPNext Prototypes

When overriding a method on an ERPNext prototype (e.g., `erpnext.stock.StockEntry.prototype`),
always check that the original method exists and preserve a fallback:

```javascript
const _proto = erpnext.stock.StockEntry.prototype;
const _original = typeof _proto.some_method === "function" ? _proto.some_method : null;

_proto.some_method = function () {
	if (_should_override(this.frm.doc)) { /* custom logic */ return; }
	if (_original) return _original.call(this);
	console.warn("[production_entry_app] some_method original not found; ERPNext may have changed.");
};
```

Document the dependency with a comment referencing the ERPNext source file and version.

### HTML Construction

Prefer template literals over string concatenation. Always escape user-supplied values:

```javascript
const row = `
	<tr>
		<td>${frappe.utils.escape_html(entry.name)}</td>
		<td>${frappe.utils.escape_html(entry.workstation || "—")}</td>
	</tr>`;
```
