frappe.ui.form.on("Operator", {
	refresh(frm) {
		(window.production_entry_app?.timeline_renderer?.render_shift_timeline || (() => {}))(
			frm,
			"Operator",
			"shift_timeline_html"
		);
	},
});
