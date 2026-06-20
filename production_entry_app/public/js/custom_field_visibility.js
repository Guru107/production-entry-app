(function () {
	const FIELD_MAP =
		(typeof window !== "undefined" &&
			window.production_entry_app &&
			window.production_entry_app.generated_access_control_field_map) ||
		(typeof module !== "undefined" && module.exports ? module.exports : {});

	function _getAccessControlApi() {
		return (
			(typeof window !== "undefined" && window.production_entry_app?.access_control) || null
		);
	}

	function _getParentTableFieldname(frm, childDoctype) {
		for (const [fieldname, field] of Object.entries(frm?.fields_dict || {})) {
			if (field?.df?.fieldtype === "Table" && field?.df?.options === childDoctype) {
				return fieldname;
			}
		}
		return null;
	}

	function _setParentFieldVisibility(frm, fieldname, visible) {
		if (!frm?.toggle_display) return;
		frm.toggle_display(fieldname, visible);
	}

	function _setGridRowsFieldVisibility(grid, fieldname, visible) {
		for (const row of grid?.grid_rows || []) {
			if (!row) continue;
			if (typeof row.toggle_display === "function") {
				row.toggle_display(fieldname, visible);
			}
		}
	}

	function _setChildFieldVisibility(frm, childDoctype, fieldname, visible) {
		const parentTableFieldname = _getParentTableFieldname(frm, childDoctype);
		const grid = parentTableFieldname ? frm?.fields_dict?.[parentTableFieldname]?.grid : null;
		if (!grid) {
			return;
		}
		if (typeof grid.toggle_display === "function") {
			grid.toggle_display(fieldname, visible);
		} else if (typeof grid.update_docfield_property === "function") {
			grid.update_docfield_property(fieldname, "hidden", visible ? 0 : 1);
			grid.debounced_refresh?.();
		} else {
			_setGridRowsFieldVisibility(grid, fieldname, visible);
		}
		frm.refresh_field?.(parentTableFieldname);
	}

	function _applyFieldVisibilityForDoctype(frm, doctype, enabled) {
		const fieldnames = FIELD_MAP[doctype] || [];
		for (const fieldname of fieldnames) {
			if (doctype === "Stock Entry Detail") {
				_setChildFieldVisibility(frm, doctype, fieldname, enabled);
				continue;
			}
			if (doctype === "Stock Entry" && enabled) {
				continue;
			}
			_setParentFieldVisibility(frm, fieldname, enabled);
		}
	}

	async function apply_field_visibility(frm, doctype) {
		if (!frm || !doctype) return;
		const accessControl = _getAccessControlApi();
		if (!accessControl?.when_ready) {
			return;
		}
		const state = await accessControl.when_ready();
		_applyFieldVisibilityForDoctype(frm, doctype, Boolean(state?.enabled));
	}

	function register_field_visibility_handlers() {
		if (typeof frappe === "undefined" || !frappe.ui?.form?.on) {
			return;
		}

		for (const doctype of Object.keys(FIELD_MAP)) {
			frappe.ui.form.on(doctype, {
				onload(frm) {
					void apply_field_visibility(frm, doctype);
				},
				refresh(frm) {
					void apply_field_visibility(frm, doctype);
				},
			});
		}
	}

	const api = {
		FIELD_MAP,
		apply_field_visibility,
		register_field_visibility_handlers,
	};

	if (typeof window !== "undefined") {
		const PEA = (window.production_entry_app = window.production_entry_app || {});
		PEA.custom_field_visibility = api;
	}

	if (typeof module !== "undefined" && module.exports) {
		module.exports = api;
	}

	register_field_visibility_handlers();
})();
