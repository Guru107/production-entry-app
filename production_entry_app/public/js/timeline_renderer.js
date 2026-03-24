(() => {
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
		if (value == null || typeof value !== "number" || !Number.isFinite(value)) {
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

		const barX = 12;
		const barY = 24;
		const barW = Math.max(120, width - 24);
		const barH = 60;
		const axisY = barY + barH + 24;

		ctx.save();
		ctx.fillStyle = "#f0f0f0";
		_rounded_rect(ctx, barX, barY, barW, barH, 8);
		ctx.fill();
		ctx.restore();

		ctx.save();
		ctx.strokeStyle = "rgba(0,0,0,0.15)";
		ctx.lineWidth = 1;
		ctx.setLineDash([4, 4]);
		const gridStart = new Date(shiftStart.getTime());
		gridStart.setMinutes(0, 0, 0);
		if (gridStart.getTime() < shiftStart.getTime()) {
			gridStart.setHours(gridStart.getHours() + 1);
		}
		for (let t = gridStart.getTime(); t < shiftEnd.getTime(); t += 60 * 60 * 1000) {
			const pct = (t - shiftStart.getTime()) / totalMs;
			const x = barX + pct * barW;
			ctx.beginPath();
			ctx.moveTo(x, barY);
			ctx.lineTo(x, barY + barH);
			ctx.stroke();
			const label = _format_label_time(new Date(t));
			ctx.fillStyle = "#666";
			ctx.font = `${FONT_SIZE_LABEL}px sans-serif`;
			ctx.textAlign = "center";
			ctx.fillText(label, x, axisY);
		}
		ctx.restore();

		ctx.fillStyle = "#666";
		ctx.font = `${FONT_SIZE_LABEL}px sans-serif`;
		ctx.textAlign = "left";
		ctx.fillText(_format_label_time(shiftStart), barX, axisY);
		ctx.textAlign = "right";
		ctx.fillText(_format_label_time(shiftEnd), barX + barW, axisY);

		const hitBoxes = [];
		entries.forEach((entry, index) => {
			const entryStart = entry.__start;
			const entryEnd = entry.__end;
			const leftPct = _clamp_pct(
				((entryStart.getTime() - shiftStart.getTime()) / totalMs) * 100
			);
			const rightPct = _clamp_pct(
				((entryEnd.getTime() - shiftStart.getTime()) / totalMs) * 100
			);
			const x = barX + (leftPct / 100) * barW + 1;
			const right = barX + (rightPct / 100) * barW - 1;
			const w = Math.max(3, right - x);
			const y = barY + 6;
			const h = barH - 12;
			const isDowntime = entry.entry_type === "downtime";
			const color = isDowntime ? "#6b7280" : PALETTE[index % PALETTE.length];

			ctx.save();
			ctx.shadowColor = "rgba(0,0,0,0.14)";
			ctx.shadowBlur = 4;
			ctx.shadowOffsetY = 2;
			const grad = ctx.createLinearGradient(x, y, x, y + h);
			grad.addColorStop(0, _lighten(color, 0.2));
			grad.addColorStop(1, color);
			ctx.fillStyle = grad;
			_rounded_rect(ctx, x, y, w, h, 5);
			ctx.fill();
			ctx.restore();

			if (w > 60) {
				ctx.save();
				ctx.beginPath();
				_rounded_rect(ctx, x, y, w, h, 5);
				ctx.clip();
				ctx.fillStyle = "#fff";
				ctx.font = `bold ${FONT_SIZE_BAR}px sans-serif`;
				ctx.textAlign = "left";
				ctx.shadowColor = "rgba(0,0,0,0.2)";
				ctx.shadowBlur = 2;
				const label = isDowntime
					? `DT ${entry.stop_reason || __("Downtime")}`
					: `${entry.fg_item || "-"} ${formatMetricDisplay(
							entry.ok_qty || 0,
							"Float",
							payload.float_precision
					  )}`;
				const maxChars = Math.max(4, Math.floor((w - 12) / 7));
				ctx.fillText(_truncate_label(label, maxChars), x + 6, y + h / 2 + 4);
				ctx.restore();
			}

			hitBoxes.push({ x, y, w, h, entry });
		});

		if (!entries.length) {
			ctx.fillStyle = "#666";
			ctx.font = "12px sans-serif";
			ctx.textAlign = "center";
			ctx.fillText(
				__("No production entries for current running shift."),
				barX + barW / 2,
				barY + barH / 2 + 4
			);
		}

		const now = new Date();
		if (now.getTime() >= shiftStart.getTime() && now.getTime() <= shiftEnd.getTime()) {
			const nowPct = (now.getTime() - shiftStart.getTime()) / totalMs;
			const nowX = barX + nowPct * barW;
			const alpha = _clamp(pulseAlpha ?? 1, 0.35, 1);
			ctx.save();
			ctx.strokeStyle = `rgba(220, 38, 38, ${alpha})`;
			ctx.fillStyle = `rgba(220, 38, 38, ${alpha})`;
			ctx.lineWidth = 2;
			ctx.setLineDash([5, 3]);
			ctx.beginPath();
			ctx.moveTo(nowX, barY - 1);
			ctx.lineTo(nowX, barY + barH + 1);
			ctx.stroke();
			ctx.setLineDash([]);
			ctx.beginPath();
			ctx.moveTo(nowX, barY - 1);
			ctx.lineTo(nowX - 6, barY - 11);
			ctx.lineTo(nowX + 6, barY - 11);
			ctx.closePath();
			ctx.fill();
			ctx.restore();
		}

		canvas.__peaHitBoxes = hitBoxes;
		canvas.__peaBarFrame = { x: barX, y: barY, w: barW, h: barH };
	}

	function _bind_timeline_interactions(canvas, tooltip) {
		const cardRect = () => canvas.closest(".pea-shift-timeline-card")?.getBoundingClientRect();
		const hideTooltip = () => {
			tooltip.style.display = "none";
		};
		canvas.addEventListener("mouseleave", hideTooltip);

		canvas.addEventListener("mousemove", (event) => {
			const rect = canvas.getBoundingClientRect();
			const x = event.clientX - rect.left;
			const y = event.clientY - rect.top;
			const hit = (canvas.__peaHitBoxes || []).find(
				(box) => x >= box.x && x <= box.x + box.w && y >= box.y && y <= box.y + box.h
			);
			if (!hit) {
				canvas.style.cursor = "default";
				hideTooltip();
				return;
			}

			canvas.style.cursor = "pointer";
			const entry = hit.entry;
			const safe = (value) => frappe.utils.escape_html(String(value ?? "-"));
			if (entry.entry_type === "downtime") {
				tooltip.innerHTML = [
					`<div><strong>${safe(entry.name)}</strong></div>`,
					`<div>${safe(__("Type"))}: ${safe(__("Downtime"))}</div>`,
					`<div>${safe(__("Reason"))}: ${safe(entry.stop_reason || __("Other"))}</div>`,
					`<div>${safe(__("Duration"))}: ${safe(
						_format_duration(entry.__start, entry.__end)
					)}</div>`,
				].join("");
			} else {
				tooltip.innerHTML = [
					`<div><strong>${safe(entry.name)}</strong></div>`,
					`<div>${safe(__("Type"))}: ${safe(__("Production"))}</div>`,
					`<div>${safe(__("FG"))}: ${safe(entry.fg_item || "-")}</div>`,
					`<div>${safe(__("FG Qty"))}: ${safe(
						formatMetricDisplay(entry.fg_qty || 0, "Float", canvas.__peaFloatPrecision)
					)}</div>`,
					`<div>${safe(__("Rejection Qty"))}: ${safe(
						formatMetricDisplay(
							entry.rejection_qty || 0,
							"Float",
							canvas.__peaFloatPrecision
						)
					)}</div>`,
					`<div>${safe(__("OK Qty"))}: ${safe(
						formatMetricDisplay(entry.ok_qty || 0, "Float", canvas.__peaFloatPrecision)
					)}</div>`,
					`<div>${safe(__("Duration"))}: ${safe(
						_format_duration(entry.__start, entry.__end)
					)}</div>`,
				].join("");
			}
			const card = cardRect();
			const left = event.clientX - (card?.left || 0) + 12;
			const top = event.clientY - (card?.top || 0) + 12;
			tooltip.style.left = `${left}px`;
			tooltip.style.top = `${top}px`;
			tooltip.style.display = "block";
		});

		canvas.addEventListener("click", (event) => {
			const rect = canvas.getBoundingClientRect();
			const x = event.clientX - rect.left;
			const y = event.clientY - rect.top;
			const hit = (canvas.__peaHitBoxes || []).find(
				(box) => x >= box.x && x <= box.x + box.w && y >= box.y && y <= box.y + box.h
			);
			if (!hit?.entry?.name) {
				return;
			}
			if (hit.entry.entry_type === "downtime") {
				frappe.set_route("Form", "Downtime Entry", hit.entry.name);
				return;
			}
			frappe.set_route("stock-entry", hit.entry.name);
		});
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
		const shiftName = frappe.utils.escape_html(String(data.shift_name || ""));
		const html = [
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
		set_html_field(frm, htmlFieldname, html);

		const field = frm.fields_dict[htmlFieldname];
		const card = field?.$wrapper?.[0]?.querySelector(`[data-pea-id="${domId}"]`);
		if (!card) {
			return;
		}
		const canvas = card.querySelector(".pea-shift-timeline-canvas");
		const tooltip = card.querySelector(".pea-shift-timeline-tooltip");
		if (!canvas || !tooltip) {
			return;
		}

		const preparedEntries = (data.entries || [])
			.map((entry) => {
				const start = _as_date(entry.actual_start);
				const end = _as_date(entry.actual_end);
				return {
					...entry,
					__start: start,
					__end: end,
				};
			})
			.filter(
				(entry) =>
					entry.__start &&
					entry.__end &&
					entry.__end.getTime() > entry.__start.getTime() &&
					entry.__end.getTime() > shiftStart.getTime() &&
					entry.__start.getTime() < shiftEnd.getTime()
			)
			.sort((a, b) => a.__start.getTime() - b.__start.getTime());

		const render = (pulseAlpha) => {
			const width = Math.max(
				320,
				Math.round(card.clientWidth || field.$wrapper.width() || 320)
			);
			const dpr = window.devicePixelRatio || 1;
			canvas.width = Math.round(width * dpr);
			canvas.height = Math.round(CANVAS_HEIGHT * dpr);
			canvas.style.width = `${width}px`;
			canvas.style.height = `${CANVAS_HEIGHT}px`;
			const ctx = canvas.getContext("2d");
			ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
			canvas.__peaWidth = width;
			canvas.__peaHeight = CANVAS_HEIGHT;
			canvas.__peaFloatPrecision = getSystemFloatPrecision(data.float_precision);
			_draw_timeline(
				canvas,
				{
					shiftStart,
					shiftEnd,
					entries: preparedEntries,
					float_precision: data.float_precision,
				},
				pulseAlpha
			);
		};

		_bind_timeline_interactions(canvas, tooltip);
		render(1);

		const state = {
			animationFrame: null,
			resizeObserver: null,
			resizeHandler: null,
			stopped: false,
		};
		frm.__peaTimelineState = frm.__peaTimelineState || {};
		frm.__peaTimelineState[htmlFieldname] = state;

		const animate = () => {
			if (state.stopped) {
				return;
			}
			const alpha = 0.7 + (Math.sin(Date.now() / ANIMATION_PERIOD_MS) + 1) * 0.15;
			render(alpha);
			state.animationFrame = requestAnimationFrame(animate);
		};
		const now = Date.now();
		if (now >= shiftStart.getTime() && now <= shiftEnd.getTime()) {
			state.animationFrame = requestAnimationFrame(animate);
		}

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
})();
