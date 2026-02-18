frappe.ui.form.on("Workstation", {
	refresh(frm) {
		(window.production_entry_app?.timeline_renderer?.render_shift_timeline || (() => {}))(
			frm,
			"Workstation",
			"custom_shift_timeline_html"
		);
	},
});
