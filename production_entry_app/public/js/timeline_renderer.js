(() => {
	const PEA = (window.production_entry_app = window.production_entry_app || {});

	function _clamp_pct(value) {
		return Math.max(0, Math.min(100, value));
	}

	function set_html_field(frm, fieldname, html) {
		const update_display = () => {
			const field = frm.fields_dict[fieldname];
			if (field) {
				field.df.options = html;
				field.html(html);
			}
		};
		update_display();
		if (!frm.fields_dict[fieldname]) {
			setTimeout(update_display, 100);
		}
	}

	function _render_timeline_message(frm, htmlFieldname, message) {
		const container = $('<div class="form-section">');
		container.append(
			`<div><strong>Running Shift Timeline</strong></div><div class="text-muted" style="margin-top:6px;">${frappe.utils.escape_html(
				message
			)}</div>`
		);
		set_html_field(frm, htmlFieldname, container.prop("outerHTML"));
	}

	function render_shift_timeline(frm, doctype, htmlFieldname) {
		if (!frm.doc.name) {
			return;
		}

		frappe.call({
			method: "production_entry_app.production_entry_app.api_timeline.get_shift_timeline_data",
			args: { doctype, docname: frm.doc.name },
			callback(r) {
				const data = r.message || {};
				const shiftName = data.shift_name;
				if (!shiftName) {
					_render_timeline_message(frm, htmlFieldname, "No running shift found.");
					return;
				}

				const shiftStart = new Date(String(data.shift_start || "").replace(" ", "T"));
				const shiftEnd = new Date(String(data.shift_end || "").replace(" ", "T"));
				const totalMs = Math.max(1, shiftEnd.getTime() - shiftStart.getTime());
				const entries = data.entries || [];
				const palette = Array.from(
					{ length: 12 },
					(_, i) => `hsl(${(i * 31) % 360}, 75%, 52%)`
				);

				const container = $('<div id="pea-shift-timeline-card" class="form-section">');
				container.append(
					`<div style="margin-bottom:8px;"><strong>Running Shift Timeline</strong>: ${frappe.utils.escape_html(
						shiftName
					)}</div>`
				);
				container.append(
					`<div style="display:flex;justify-content:space-between;font-size:12px;color:#666;margin-bottom:4px;">
						<span>${frappe.datetime.str_to_user(String(data.shift_start))}</span>
						<span>${frappe.datetime.str_to_user(String(data.shift_end))}</span>
					</div>`
				);
				const bar = $(
					'<div style="position:relative;height:36px;background:#e8e8e8;border-radius:8px;overflow:hidden;"></div>'
				);

				entries.forEach((entry, index) => {
					const entryStart = new Date(
						String(entry.actual_start || "").replace(" ", "T")
					);
					const entryEnd = new Date(String(entry.actual_end || "").replace(" ", "T"));
					const leftPct = _clamp_pct(
						((entryStart.getTime() - shiftStart.getTime()) / totalMs) * 100
					);
					const widthPct = Math.max(
						0.8,
						_clamp_pct(((entryEnd.getTime() - entryStart.getTime()) / totalMs) * 100)
					);
					const block = $(
						`<div style="position:absolute;left:${leftPct}%;width:${widthPct}%;top:4px;bottom:4px;border-radius:6px;background:${
							palette[index % palette.length]
						};"></div>`
					);
					const details = [
						`SE: ${entry.name || ""}`,
						`FG: ${entry.fg_item || "-"}`,
						`FG Qty: ${entry.fg_qty || 0}`,
						`Rejection Qty: ${entry.rejection_qty || 0}`,
						`OK Qty: ${entry.ok_qty || 0}`,
					].join(" | ");
					block.attr("title", details);
					bar.append(block);
				});

				if (!entries.length) {
					bar.append(
						'<div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#666;font-size:12px;">No production entries for current running shift.</div>'
					);
				}

				container.append(bar);
				set_html_field(frm, htmlFieldname, container.prop("outerHTML"));
			},
			error() {
				_render_timeline_message(frm, htmlFieldname, "Unable to load timeline data.");
			},
		});
	}

	PEA.timeline_renderer = {
		render_shift_timeline,
		set_html_field,
	};
})();
