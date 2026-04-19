frappe.ui.form.on("Operator", {
	refresh(frm) {
		void window.production_entry_app?.custom_field_visibility?.apply_field_visibility?.(
			frm,
			"Operator"
		);
		const accessControl = window.production_entry_app?.access_control;
		const ready = accessControl?.when_ready?.();
		if (!ready?.then) return;
		void ready.then((state) => {
			if (!state?.enabled) return;
			const renderer = window.production_entry_app?.timeline_renderer;
			if (!renderer?.render_shift_timeline) {
				console.warn("Production Entry App timeline renderer is not loaded.");
				return;
			}
			renderer.render_shift_timeline(frm, "Operator", "shift_timeline_html");
		});
	},
});
