frappe.ui.form.on("Operator", {
	refresh(frm) {
		const renderer = window.production_entry_app?.timeline_renderer;
		if (!renderer?.render_shift_timeline) {
			console.warn("Production Entry App timeline renderer is not loaded.");
			return;
		}
		renderer.render_shift_timeline(frm, "Operator", "shift_timeline_html");
	},
});
