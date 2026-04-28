const PEA = (window.production_entry_app = window.production_entry_app || {});
const PALETTE = [
	"#4C6EF5",
	"#37B24D",
	"#F59F00",
	"#E64980",
	"#7950F2",
	"#20C997",
	"#FD7E14",
	"#1098AD",
	"#AE3EC9",
	"#74B816",
	"#4DABF7",
	"#FF6B6B",
];
const CANVAS_HEIGHT = 130;
const FONT_SIZE_LABEL = 11;
const FONT_SIZE_BAR = 11;
const ANIMATION_PERIOD_MS = 450;

function _clamp_pct(value) {
	return Math.max(0, Math.min(100, value));
}

function _clamp(value, min, max) {
	return Math.max(min, Math.min(max, value));
}

function _as_date(value) {
	if (!value) {
		return null;
	}
	const date = new Date(String(value).replace(" ", "T"));
	if (Number.isNaN(date.getTime())) {
		return null;
	}
	return date;
}

function _format_label_time(date) {
	return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(
		2,
		"0"
	)}`;
}

function _hex_to_rgb(hex) {
	const value = (hex || "").replace("#", "");
	if (value.length !== 6) {
		return { r: 0, g: 0, b: 0 };
	}
	return {
		r: parseInt(value.slice(0, 2), 16),
		g: parseInt(value.slice(2, 4), 16),
		b: parseInt(value.slice(4, 6), 16),
	};
}

function _lighten(hex, ratio) {
	const rgb = _hex_to_rgb(hex);
	const mix = (channel) => Math.round(channel + (255 - channel) * _clamp(ratio, 0, 1));
	return `rgb(${mix(rgb.r)}, ${mix(rgb.g)}, ${mix(rgb.b)})`;
}

function _rounded_rect(ctx, x, y, w, h, r) {
	const radius = Math.min(r, w / 2, h / 2);
	ctx.beginPath();
	ctx.moveTo(x + radius, y);
	ctx.arcTo(x + w, y, x + w, y + h, radius);
	ctx.arcTo(x + w, y + h, x, y + h, radius);
	ctx.arcTo(x, y + h, x, y, radius);
	ctx.arcTo(x, y, x + w, y, radius);
	ctx.closePath();
}

function _truncate_label(text, maxChars) {
	if (text.length <= maxChars) {
		return text;
	}
	return `${text.slice(0, Math.max(0, maxChars - 1))}…`;
}

function _format_duration(start, end) {
	const mins = Math.max(0, Math.round((end.getTime() - start.getTime()) / 60000));
	const hours = Math.floor(mins / 60);
	const remainder = mins % 60;
	if (!hours) {
		return `${remainder}m`;
	}
	if (!remainder) {
		return `${hours}h`;
	}
	return `${hours}h ${remainder}m`;
}

function getSystemFloatPrecision(rawPrecision) {
	const resolvedRawPrecision =
		rawPrecision ??
		frappe?.boot?.sysdefaults?.float_precision ??
		frappe?.defaults?.get_default?.("float_precision") ??
		3;
	const numericPrecision = Number(resolvedRawPrecision);
	return Number.isFinite(numericPrecision) ? numericPrecision : 3;
}

function formatMetricDisplay(value, fieldtype = "Float", rawPrecision) {
	if (
		value === null ||
		value === undefined ||
		typeof value !== "number" ||
		!Number.isFinite(value)
	) {
		return String(value ?? "");
	}
	if (typeof frappe !== "undefined" && typeof frappe.format === "function") {
		const df = { fieldtype };
		if (fieldtype === "Float") {
			df.precision = getSystemFloatPrecision(rawPrecision);
		}
		return frappe.format(value, df, { only_value: true, always_show_decimals: true });
	}
	return String(value);
}

function _clear_timeline_state(frm, htmlFieldname) {
	if (!frm.__peaTimelineState) {
		return;
	}
	const state = frm.__peaTimelineState[htmlFieldname];
	if (!state) {
		return;
	}
	state.stopped = true;
	if (state.animationFrame) {
		cancelAnimationFrame(state.animationFrame);
	}
	if (state.resizeObserver) {
		state.resizeObserver.disconnect();
	}
	if (state.resizeHandler) {
		window.removeEventListener("resize", state.resizeHandler);
	}
	delete frm.__peaTimelineState[htmlFieldname];
}

function _draw_timeline(canvas, payload, pulseAlpha) {
	const ctx = canvas.getContext("2d");
	const width = canvas.__peaWidth || 0;
	const height = canvas.__peaHeight || 0;
	ctx.clearRect(0, 0, width, height);

	const shiftStart = payload.shiftStart;
	const shiftEnd = payload.shiftEnd;
	const entries = payload.entries || [];
	const totalMs = Math.max(1, shiftEnd.getTime() - shiftStart.getTime());
	const frame = _get_timeline_frame(width);

	_draw_timeline_background(ctx, frame, shiftStart, shiftEnd, totalMs);
	canvas.__peaHitBoxes = _draw_entry_segments(
		ctx,
		frame,
		entries,
		shiftStart,
		totalMs,
		payload.float_precision
	);
	if (!entries.length) {
		_draw_empty_timeline_message(ctx, frame);
	}
	_draw_now_marker(ctx, frame, shiftStart, shiftEnd, totalMs, pulseAlpha);
	canvas.__peaBarFrame = frame;
}

function _get_timeline_frame(width) {
	const x = 12;
	const y = 24;
	const w = Math.max(120, width - 24);
	const h = 60;
	return { x, y, w, h, axisY: y + h + 24 };
}

function _draw_timeline_background(ctx, frame, shiftStart, shiftEnd, totalMs) {
	ctx.save();
	ctx.fillStyle = "#f0f0f0";
	_rounded_rect(ctx, frame.x, frame.y, frame.w, frame.h, 8);
	ctx.fill();
	ctx.restore();
	_draw_timeline_grid(ctx, frame, shiftStart, shiftEnd, totalMs);
	_draw_timeline_axis_labels(ctx, frame, shiftStart, shiftEnd);
}

function _draw_timeline_grid(ctx, frame, shiftStart, shiftEnd, totalMs) {
	ctx.save();
	ctx.strokeStyle = "rgba(0,0,0,0.15)";
	ctx.lineWidth = 1;
	ctx.setLineDash([4, 4]);
	for (let t = _get_first_grid_time(shiftStart); t < shiftEnd.getTime(); t += 60 * 60 * 1000) {
		_draw_grid_line(ctx, frame, t, shiftStart, totalMs);
	}
	ctx.restore();
}

function _get_first_grid_time(shiftStart) {
	const gridStart = new Date(shiftStart.getTime());
	gridStart.setMinutes(0, 0, 0);
	if (gridStart.getTime() < shiftStart.getTime()) {
		gridStart.setHours(gridStart.getHours() + 1);
	}
	return gridStart.getTime();
}

function _draw_grid_line(ctx, frame, timestamp, shiftStart, totalMs) {
	const pct = (timestamp - shiftStart.getTime()) / totalMs;
	const x = frame.x + pct * frame.w;
	ctx.beginPath();
	ctx.moveTo(x, frame.y);
	ctx.lineTo(x, frame.y + frame.h);
	ctx.stroke();
	ctx.fillStyle = "#666";
	ctx.font = `${FONT_SIZE_LABEL}px sans-serif`;
	ctx.textAlign = "center";
	ctx.fillText(_format_label_time(new Date(timestamp)), x, frame.axisY);
}

function _draw_timeline_axis_labels(ctx, frame, shiftStart, shiftEnd) {
	ctx.fillStyle = "#666";
	ctx.font = `${FONT_SIZE_LABEL}px sans-serif`;
	ctx.textAlign = "left";
	ctx.fillText(_format_label_time(shiftStart), frame.x, frame.axisY);
	ctx.textAlign = "right";
	ctx.fillText(_format_label_time(shiftEnd), frame.x + frame.w, frame.axisY);
}

function _draw_entry_segments(ctx, frame, entries, shiftStart, totalMs, floatPrecision) {
	return entries.map((entry, index) => {
		const box = _get_entry_hit_box(frame, entry, shiftStart, totalMs);
		_draw_entry_bar(ctx, box, entry, index, floatPrecision);
		return { ...box, entry };
	});
}

function _get_entry_hit_box(frame, entry, shiftStart, totalMs) {
	const leftPct = _clamp_pct(((entry.__start.getTime() - shiftStart.getTime()) / totalMs) * 100);
	const rightPct = _clamp_pct(((entry.__end.getTime() - shiftStart.getTime()) / totalMs) * 100);
	const x = frame.x + (leftPct / 100) * frame.w + 1;
	const right = frame.x + (rightPct / 100) * frame.w - 1;
	return { x, y: frame.y + 6, w: Math.max(3, right - x), h: frame.h - 12 };
}

function _draw_entry_bar(ctx, box, entry, index, floatPrecision) {
	const color = entry.entry_type === "downtime" ? "#6b7280" : PALETTE[index % PALETTE.length];
	_draw_entry_bar_shape(ctx, box, color);
	if (box.w > 60) {
		_draw_entry_bar_label(ctx, box, entry, floatPrecision);
	}
}

function _draw_entry_bar_shape(ctx, box, color) {
	ctx.save();
	ctx.shadowColor = "rgba(0,0,0,0.14)";
	ctx.shadowBlur = 4;
	ctx.shadowOffsetY = 2;
	const grad = ctx.createLinearGradient(box.x, box.y, box.x, box.y + box.h);
	grad.addColorStop(0, _lighten(color, 0.2));
	grad.addColorStop(1, color);
	ctx.fillStyle = grad;
	_rounded_rect(ctx, box.x, box.y, box.w, box.h, 5);
	ctx.fill();
	ctx.restore();
}

function _draw_entry_bar_label(ctx, box, entry, floatPrecision) {
	ctx.save();
	ctx.beginPath();
	_rounded_rect(ctx, box.x, box.y, box.w, box.h, 5);
	ctx.clip();
	ctx.fillStyle = "#fff";
	ctx.font = `bold ${FONT_SIZE_BAR}px sans-serif`;
	ctx.textAlign = "left";
	ctx.shadowColor = "rgba(0,0,0,0.2)";
	ctx.shadowBlur = 2;
	const label = _get_entry_bar_label(entry, floatPrecision);
	const maxChars = Math.max(4, Math.floor((box.w - 12) / 7));
	ctx.fillText(_truncate_label(label, maxChars), box.x + 6, box.y + box.h / 2 + 4);
	ctx.restore();
}

function _get_entry_bar_label(entry, floatPrecision) {
	if (entry.entry_type === "downtime") {
		return `DT ${entry.stop_reason || __("Downtime")}`;
	}
	return `${entry.fg_item || "-"} ${formatMetricDisplay(
		entry.ok_qty || 0,
		"Float",
		floatPrecision
	)}`;
}

function _draw_empty_timeline_message(ctx, frame) {
	ctx.fillStyle = "#666";
	ctx.font = "12px sans-serif";
	ctx.textAlign = "center";
	ctx.fillText(
		__("No production entries for current running shift."),
		frame.x + frame.w / 2,
		frame.y + frame.h / 2 + 4
	);
}

function _draw_now_marker(ctx, frame, shiftStart, shiftEnd, totalMs, pulseAlpha) {
	const now = new Date();
	if (now.getTime() < shiftStart.getTime() || now.getTime() > shiftEnd.getTime()) {
		return;
	}
	const nowPct = (now.getTime() - shiftStart.getTime()) / totalMs;
	const nowX = frame.x + nowPct * frame.w;
	const alpha = _clamp(pulseAlpha ?? 1, 0.35, 1);
	ctx.save();
	ctx.strokeStyle = `rgba(220, 38, 38, ${alpha})`;
	ctx.fillStyle = `rgba(220, 38, 38, ${alpha})`;
	ctx.lineWidth = 2;
	ctx.setLineDash([5, 3]);
	ctx.beginPath();
	ctx.moveTo(nowX, frame.y - 1);
	ctx.lineTo(nowX, frame.y + frame.h + 1);
	ctx.stroke();
	ctx.setLineDash([]);
	ctx.beginPath();
	ctx.moveTo(nowX, frame.y - 1);
	ctx.lineTo(nowX - 6, frame.y - 11);
	ctx.lineTo(nowX + 6, frame.y - 11);
	ctx.closePath();
	ctx.fill();
	ctx.restore();
}

function _bind_timeline_interactions(canvas, tooltip) {
	const cardRect = () => canvas.closest(".pea-shift-timeline-card")?.getBoundingClientRect();
	const hideTooltip = () => {
		tooltip.style.display = "none";
	};
	canvas.addEventListener("mouseleave", hideTooltip);

	canvas.addEventListener("mousemove", (event) => {
		const hit = _get_hit_box_for_event(canvas, event);
		if (!hit) {
			canvas.style.cursor = "default";
			hideTooltip();
			return;
		}

		canvas.style.cursor = "pointer";
		_show_timeline_tooltip(tooltip, hit.entry, canvas.__peaFloatPrecision, cardRect(), event);
	});

	canvas.addEventListener("click", (event) => {
		const hit = _get_hit_box_for_event(canvas, event);
		if (!hit?.entry?.name) {
			return;
		}
		_open_timeline_entry(hit.entry);
	});
}

function _get_hit_box_for_event(canvas, event) {
	const rect = canvas.getBoundingClientRect();
	const x = event.clientX - rect.left;
	const y = event.clientY - rect.top;
	return (canvas.__peaHitBoxes || []).find(
		(box) => x >= box.x && x <= box.x + box.w && y >= box.y && y <= box.y + box.h
	);
}

function _show_timeline_tooltip(tooltip, entry, floatPrecision, card, event) {
	tooltip.innerHTML =
		entry.entry_type === "downtime"
			? _get_downtime_tooltip_html(entry)
			: _get_production_tooltip_html(entry, floatPrecision);
	tooltip.style.left = `${event.clientX - (card?.left || 0) + 12}px`;
	tooltip.style.top = `${event.clientY - (card?.top || 0) + 12}px`;
	tooltip.style.display = "block";
}

function _get_downtime_tooltip_html(entry) {
	return [
		`<div><strong>${_safe_tooltip_value(entry.name)}</strong></div>`,
		`<div>${_safe_tooltip_value(__("Type"))}: ${_safe_tooltip_value(__("Downtime"))}</div>`,
		`<div>${_safe_tooltip_value(__("Reason"))}: ${_safe_tooltip_value(
			entry.stop_reason || __("Other")
		)}</div>`,
		`<div>${_safe_tooltip_value(__("Duration"))}: ${_safe_tooltip_value(
			_format_duration(entry.__start, entry.__end)
		)}</div>`,
	].join("");
}

function _get_production_tooltip_html(entry, floatPrecision) {
	return [
		`<div><strong>${_safe_tooltip_value(entry.name)}</strong></div>`,
		`<div>${_safe_tooltip_value(__("Type"))}: ${_safe_tooltip_value(__("Production"))}</div>`,
		`<div>${_safe_tooltip_value(__("FG"))}: ${_safe_tooltip_value(
			entry.fg_item || "-"
		)}</div>`,
		_get_metric_tooltip_line(__("FG Qty"), entry.fg_qty, floatPrecision),
		_get_metric_tooltip_line(__("Rejection Qty"), entry.rejection_qty, floatPrecision),
		_get_metric_tooltip_line(__("OK Qty"), entry.ok_qty, floatPrecision),
		`<div>${_safe_tooltip_value(__("Duration"))}: ${_safe_tooltip_value(
			_format_duration(entry.__start, entry.__end)
		)}</div>`,
	].join("");
}

function _get_metric_tooltip_line(label, value, floatPrecision) {
	return `<div>${_safe_tooltip_value(label)}: ${_safe_tooltip_value(
		formatMetricDisplay(value || 0, "Float", floatPrecision)
	)}</div>`;
}

function _safe_tooltip_value(value) {
	return frappe.utils.escape_html(String(value ?? "-"));
}

function _open_timeline_entry(entry) {
	if (entry.entry_type === "downtime") {
		frappe.set_route("Form", "Downtime Entry", entry.name);
		return;
	}
	frappe.set_route("stock-entry", entry.name);
}

function _render_canvas_timeline(frm, htmlFieldname, data) {
	const shiftStart = _as_date(data.shift_start);
	const shiftEnd = _as_date(data.shift_end);
	if (!shiftStart || !shiftEnd || shiftEnd.getTime() <= shiftStart.getTime()) {
		_render_timeline_message(frm, htmlFieldname, __("Invalid shift window for timeline."));
		return;
	}

	_clear_timeline_state(frm, htmlFieldname);
	const domId = `pea-timeline-${Math.random().toString(36).slice(2)}`;
	set_html_field(frm, htmlFieldname, _get_timeline_html(domId, data));

	const field = frm.fields_dict[htmlFieldname];
	const elements = _get_timeline_elements(field, domId);
	if (!elements) {
		return;
	}

	const preparedEntries = _prepare_timeline_entries(data.entries || [], shiftStart, shiftEnd);
	const render = _get_timeline_render_fn(
		elements,
		field,
		data,
		shiftStart,
		shiftEnd,
		preparedEntries
	);
	_bind_timeline_interactions(elements.canvas, elements.tooltip);
	render(1);

	const state = _init_timeline_state(frm, htmlFieldname);
	_start_timeline_animation_if_running(state, render, shiftStart, shiftEnd);
	_bind_timeline_resize(state, elements.card, render);
}

function _get_timeline_html(domId, data) {
	const shiftName = frappe.utils.escape_html(String(data.shift_name || ""));
	return [
		`<div class="pea-shift-timeline-card form-section" data-pea-id="${domId}" style="position:relative;">`,
		`<div style="margin-bottom:8px;"><strong>${frappe.utils.escape_html(
			__("Running Shift Timeline")
		)}</strong>: ${shiftName}</div>`,
		`<div style="display:flex;justify-content:space-between;font-size:12px;color:#666;margin-bottom:6px;">`,
		`<span>${frappe.utils.escape_html(
			frappe.datetime.str_to_user(String(data.shift_start || ""))
		)}</span>`,
		`<span>${frappe.utils.escape_html(
			frappe.datetime.str_to_user(String(data.shift_end || ""))
		)}</span>`,
		`</div>`,
		`<canvas class="pea-shift-timeline-canvas" height="${CANVAS_HEIGHT}" style="width:100%;height:${CANVAS_HEIGHT}px;display:block;"></canvas>`,
		'<div class="pea-shift-timeline-tooltip" style="display:none;position:absolute;z-index:100;background:#fff;border:1px solid #d1d5db;border-radius:8px;padding:10px 14px;box-shadow:0 4px 12px rgba(0,0,0,0.12);font-size:12px;line-height:1.6;pointer-events:none;max-width:260px;"></div>',
		"</div>",
	].join("");
}

function _get_timeline_elements(field, domId) {
	const card = field?.$wrapper?.[0]?.querySelector(`[data-pea-id="${domId}"]`);
	const canvas = card?.querySelector(".pea-shift-timeline-canvas");
	const tooltip = card?.querySelector(".pea-shift-timeline-tooltip");
	return card && canvas && tooltip ? { card, canvas, tooltip } : null;
}

function _prepare_timeline_entries(entries, shiftStart, shiftEnd) {
	return entries
		.map((entry) => ({
			...entry,
			__start: _as_date(entry.actual_start),
			__end: _as_date(entry.actual_end),
		}))
		.filter((entry) => _is_visible_timeline_entry(entry, shiftStart, shiftEnd))
		.sort((a, b) => a.__start.getTime() - b.__start.getTime());
}

function _is_visible_timeline_entry(entry, shiftStart, shiftEnd) {
	return Boolean(
		entry.__start &&
			entry.__end &&
			entry.__end.getTime() > entry.__start.getTime() &&
			entry.__end.getTime() > shiftStart.getTime() &&
			entry.__start.getTime() < shiftEnd.getTime()
	);
}

function _get_timeline_render_fn(elements, field, data, shiftStart, shiftEnd, preparedEntries) {
	return (pulseAlpha) => {
		const width = Math.max(
			320,
			Math.round(elements.card.clientWidth || field.$wrapper.width() || 320)
		);
		const dpr = window.devicePixelRatio || 1;
		_setup_canvas_for_dpr(elements.canvas, width, dpr, data.float_precision);
		_draw_timeline(
			elements.canvas,
			{
				shiftStart,
				shiftEnd,
				entries: preparedEntries,
				float_precision: data.float_precision,
			},
			pulseAlpha
		);
	};
}

function _setup_canvas_for_dpr(canvas, width, dpr, floatPrecision) {
	canvas.width = Math.round(width * dpr);
	canvas.height = Math.round(CANVAS_HEIGHT * dpr);
	canvas.style.width = `${width}px`;
	canvas.style.height = `${CANVAS_HEIGHT}px`;
	canvas.getContext("2d").setTransform(dpr, 0, 0, dpr, 0, 0);
	canvas.__peaWidth = width;
	canvas.__peaHeight = CANVAS_HEIGHT;
	canvas.__peaFloatPrecision = getSystemFloatPrecision(floatPrecision);
}

function _init_timeline_state(frm, htmlFieldname) {
	const state = {
		animationFrame: null,
		resizeObserver: null,
		resizeHandler: null,
		stopped: false,
	};
	frm.__peaTimelineState = frm.__peaTimelineState || {};
	frm.__peaTimelineState[htmlFieldname] = state;
	return state;
}

function _start_timeline_animation_if_running(state, render, shiftStart, shiftEnd) {
	if (!_is_now_within_shift(shiftStart, shiftEnd)) {
		return;
	}
	const animate = () => {
		if (state.stopped) {
			return;
		}
		const alpha = 0.7 + (Math.sin(Date.now() / ANIMATION_PERIOD_MS) + 1) * 0.15;
		render(alpha);
		state.animationFrame = requestAnimationFrame(animate);
	};
	state.animationFrame = requestAnimationFrame(animate);
}

function _is_now_within_shift(shiftStart, shiftEnd) {
	const now = Date.now();
	return now >= shiftStart.getTime() && now <= shiftEnd.getTime();
}

function _bind_timeline_resize(state, card, render) {
	if (typeof ResizeObserver !== "undefined") {
		state.resizeObserver = new ResizeObserver(() => {
			render(1);
		});
		state.resizeObserver.observe(card);
	} else {
		state.resizeHandler = () => {
			render(1);
		};
		window.addEventListener("resize", state.resizeHandler);
	}
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
	_clear_timeline_state(frm, htmlFieldname);
	const container = $('<div class="form-section">');
	container.append(
		`<div><strong>${frappe.utils.escape_html(
			__("Running Shift Timeline")
		)}</strong></div><div class="text-muted" style="margin-top:6px;">${frappe.utils.escape_html(
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
				_render_timeline_message(frm, htmlFieldname, __("No running shift found."));
				return;
			}
			_render_canvas_timeline(frm, htmlFieldname, data);
		},
		error() {
			_render_timeline_message(frm, htmlFieldname, __("Unable to load timeline data."));
		},
	});
}

PEA.timeline_renderer = {
	render_shift_timeline,
	set_html_field,
};
