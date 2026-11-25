# RM Batch Trace: body of a non-standard Frappe Script Report (Report.report_script).
#
# Runs inside Frappe's safe_exec (RestrictedPython) on the host site, NOT as part of
# production_entry_app. Sandbox rules that shape this file:
# - no imports and no names starting with "_" (except the translation function `_`);
# - top-level functions cannot see other top-level names, so everything lives inside
#   rm_batch_trace() and its nested helpers;
# - no augmented assignment on items (`d[k] += x`), no str.format();
# - the script receives `filters` and returns by setting `data = [columns, rows, message]`.
#
# Walk: per (item, warehouse), FIFO over non-cancelled Stock Ledger Entries. Units in stock
# just before an outgoing entry are the newest arrivals summing to the balance, so an
# outgoing slice maps onto the incoming entries found by walking the ledger backwards.
# Quantities are deltas of qty_after_transaction (Stock Reconciliation posts actual_qty = 0).


def rm_batch_trace(filters):
	flt = frappe.utils.flt
	max_depth = 60
	max_steps = 10000
	page_size = 500
	eps = 1e-9
	via_limit = 3
	scrap_item_group = "Scrap"
	joint_side_field = "custom_pea_joint_output_side"
	precision = int(frappe.db.get_single_value("System Settings", "float_precision") or 3)

	state = {"steps": 0, "work_limit": False}
	item_cache = {}
	doc_cache = {}
	bom_cache = {}
	window_cache = {}
	out_cache = {}
	bundle_cache = {}
	traced = {}
	untraced = {}

	doctype = filters.get("document_type") or "Sales Invoice"
	document = filters.get("document")
	item_filter = filters.get("item")
	if doctype not in ("Sales Invoice", "Delivery Note"):
		frappe.throw(_("Document Type must be Sales Invoice or Delivery Note."))
	# Filters arrive as JSON: a list here would act as a filter expression and widen the query.
	if not document or not isinstance(document, str):
		frappe.throw(_("Select the %s to trace.") % _(doctype))
	if item_filter and not isinstance(item_filter, str):
		frappe.throw(_("Item filter must be a single Item."))

	header_fields = ["name", "docstatus", "is_return"]
	if doctype == "Sales Invoice":
		header_fields.append("update_stock")
	# get_list applies the user's permissions; frappe.has_permission is not available here.
	header = frappe.get_list(doctype, filters={"name": document}, fields=header_fields, limit=1)
	if not header:
		frappe.throw(_("You do not have permission to read %s %s.") % (_(doctype), document))
	header = header[0]
	if header.docstatus != 1:
		frappe.throw(
			_("%s %s is not submitted. Only submitted documents can be traced.") % (_(doctype), document)
		)
	if header.is_return:
		frappe.throw(_("%s %s is a return. Trace the original document instead.") % (_(doctype), document))
	if doctype == "Sales Invoice" and not header.update_stock:
		frappe.throw(
			_(
				"Sales Invoice %s did not update stock. Trace the Delivery Note that shipped its items instead."
			)
			% document
		)

	# Read caches with .get(): the sandbox rejects subscript reads of string keys starting with "_".
	def item_info(item_code):
		if item_code not in item_cache:
			item_cache[item_code] = (
				frappe.db.get_value(
					"Item",
					item_code,
					["has_batch_no", "item_group", "stock_uom", "is_stock_item"],
					as_dict=True,
				)
				or {}
			)
		return item_cache.get(item_code)

	def get_doc(voucher_type, voucher_no):
		key = (voucher_type, voucher_no)
		if key not in doc_cache:
			doc_cache[key] = frappe.get_doc(voucher_type, voucher_no)
		return doc_cache[key]

	def bom_demand(bom_no):
		"""Stock qty of each input item per one unit of the BOM's output."""
		if bom_no not in bom_cache:
			quantity = flt(frappe.db.get_value("BOM", bom_no, "quantity"))
			demand = {}
			if quantity > 0:
				for row in frappe.get_all(
					"BOM Item",
					filters={"parent": bom_no, "parenttype": "BOM"},
					fields=["item_code", "stock_qty"],
				):
					demand[row.item_code] = demand.get(row.item_code, 0) + flt(row.stock_qty) / quantity
			bom_cache[bom_no] = demand
		return bom_cache.get(bom_no)

	def add_traced(ctx, rm_item, batch, qty, approx):
		if qty <= eps:
			return
		key = (ctx["line"].name, rm_item, batch or "")
		row = traced.get(key)
		if not row:
			row = {"qty": 0.0, "via": [], "approx": False}
			traced[key] = row
		row["qty"] = row["qty"] + qty
		row["approx"] = row["approx"] or approx or ctx["approx"]
		via = " ← ".join(ctx["path"])
		if via not in row["via"]:
			row["via"].append(via)

	def add_untraced(ctx, reason, item_code, qty, voucher=None, keep_zero=False):
		if qty <= eps and not keep_zero:
			return
		path = ctx["path"]
		if voucher and (not path or path[-1] != voucher):
			path = [*path, voucher]
		key = (ctx["line"].name, reason, item_code)
		row = untraced.get(key)
		if not row:
			row = {"qty": 0.0, "via": []}
			untraced[key] = row
		row["qty"] = row["qty"] + qty
		via = " ← ".join(path)
		if via not in row["via"]:
			row["via"].append(via)

	def step(ctx, item_code, qty):
		state["steps"] = state["steps"] + 1
		if state["steps"] > max_steps:
			state["work_limit"] = True
			add_untraced(ctx, _("Work limit reached"), item_code, qty)
			return False
		if len(ctx["path"]) > max_depth:
			add_untraced(ctx, _("Depth limit reached"), item_code, qty)
			return False
		return True

	def map_band(rows, qty_of, f0, f1):
		"""Overlap of the band [f0, f1] of the rows laid end to end → (row, g0, g1) per row."""
		total = sum(qty_of(row) for row in rows)
		out = []
		if total <= eps:
			return out
		start = 0.0
		for row in rows:
			size = qty_of(row)
			if size > eps:
				lo = max(f0 * total, start)
				hi = min(f1 * total, start + size)
				if hi - lo > eps:
					out.append((row, (lo - start) / size, (hi - start) / size))
			start = start + size
		return out

	def out_entries(voucher_type, voucher_no, detail_no, item_code, warehouse):
		key = (voucher_type, voucher_no, detail_no, item_code, warehouse)
		if key not in out_cache:
			out_cache[key] = load_out_entries(voucher_type, voucher_no, detail_no, item_code, warehouse)
		return out_cache[key]

	def load_out_entries(voucher_type, voucher_no, detail_no, item_code, warehouse):
		return frappe.get_all(
			"Stock Ledger Entry",
			filters={
				"voucher_type": voucher_type,
				"voucher_no": voucher_no,
				"voucher_detail_no": detail_no,
				"item_code": item_code,
				"warehouse": warehouse,
				"is_cancelled": 0,
				"actual_qty": ["<", 0],
			},
			fields=[
				"name",
				"posting_datetime",
				"creation",
				"actual_qty",
				"qty_after_transaction",
				"serial_and_batch_bundle",
				"batch_no",
			],
			order_by="posting_datetime asc, creation asc",
		)

	def earlier_page(out_sle, item_code, warehouse, offset):
		sle = frappe.qb.DocType("Stock Ledger Entry")
		return (
			frappe.qb.from_(sle)
			.select(
				sle.name,
				sle.voucher_type,
				sle.voucher_no,
				sle.voucher_detail_no,
				sle.qty_after_transaction,
			)
			.where(sle.item_code == item_code)
			.where(sle.warehouse == warehouse)
			.where(sle.is_cancelled == 0)
			.where(
				(sle.posting_datetime < out_sle.posting_datetime)
				| ((sle.posting_datetime == out_sle.posting_datetime) & (sle.creation < out_sle.creation))
			)
			.orderby(sle.posting_datetime, order=frappe.qb.desc)
			.orderby(sle.creation, order=frappe.qb.desc)
			.limit(page_size + 1)
			.offset(offset)
			.run(as_dict=True)
		)

	def incoming_before(out_sle, item_code, warehouse, needed):
		"""Incoming entries before out_sle, newest first, as (row, delta), until `needed` qty is covered."""
		window = window_cache.get(out_sle.name)
		if not window:
			window = {"rows": [], "covered": 0.0, "offset": 0, "done": False}
			window_cache[out_sle.name] = window
		while window["covered"] < needed - eps and not window["done"]:
			page = earlier_page(out_sle, item_code, warehouse, window["offset"])
			if len(page) <= page_size:
				window["done"] = True
			for index in range(min(len(page), page_size)):
				row = page[index]
				older = page[index + 1].qty_after_transaction if index + 1 < len(page) else 0
				delta = flt(row.qty_after_transaction) - flt(older)
				if delta > eps:
					window["rows"].append((row, delta))
					window["covered"] = window["covered"] + delta
			window["offset"] = window["offset"] + page_size
		return window["rows"]

	def bundle_batches(bundle):
		if bundle not in bundle_cache:
			bundle_cache[bundle] = [
				(entry.batch_no, abs(flt(entry.qty)))
				for entry in frappe.get_all(
					"Serial and Batch Entry", filters={"parent": bundle}, fields=["batch_no", "qty"]
				)
			]
		return bundle_cache.get(bundle)

	def trace_batches(ctx, item_code, entries, f0, f1, approx):
		for sle, g0, g1 in map_band(entries, lambda e: -flt(e.actual_qty), f0, f1):
			qty = -flt(sle.actual_qty) * (g1 - g0)
			batches = []
			if sle.serial_and_batch_bundle:
				batches = bundle_batches(sle.serial_and_batch_bundle)
			elif sle.batch_no:
				batches.append((sle.batch_no, 1.0))
			total = sum(batch_qty for batch, batch_qty in batches)
			if total <= eps:
				add_traced(ctx, item_code, _("(batch not recorded)"), qty, approx)
				continue
			for batch, batch_qty in batches:
				add_traced(ctx, item_code, batch, qty * batch_qty / total, approx)

	def trace_out(ctx, item_code, warehouse, voucher_type, voucher_no, detail_no, f0, f1, approx=False):
		"""Trace the band [f0, f1] of a voucher row's outgoing qty of item_code at warehouse."""
		entries = out_entries(voucher_type, voucher_no, detail_no, item_code, warehouse)
		size = sum(-flt(e.actual_qty) for e in entries)
		if size <= eps:
			add_untraced(ctx, _("No stock ledger entry"), item_code, 0, voucher_no, keep_zero=True)
			return
		if not step(ctx, item_code, size * (f1 - f0)):
			return
		if item_info(item_code).get("has_batch_no"):
			trace_batches(ctx, item_code, entries, f0, f1, approx)
			return
		for sle, g0, g1 in map_band(entries, lambda e: -flt(e.actual_qty), f0, f1):
			out_qty = -flt(sle.actual_qty)
			balance_before = flt(sle.qty_after_transaction) + out_qty
			# Backward distance from the newest arrival: the outgoing units are the oldest in stock.
			lo = balance_before - g1 * out_qty
			hi = balance_before - g0 * out_qty
			covered = 0.0
			for row, delta in incoming_before(sle, item_code, warehouse, hi):
				a = max(lo, covered)
				b = min(hi, covered + delta)
				if b - a > eps:
					trace_in(
						ctx,
						item_code,
						warehouse,
						row,
						(covered + delta - b) / delta,
						(covered + delta - a) / delta,
						b - a,
						approx,
					)
				covered = covered + delta
				if covered >= hi - eps:
					break
			if hi - max(lo, covered) > eps:
				add_untraced(ctx, _("Opening balance or negative stock"), item_code, hi - max(lo, covered))

	def trace_in(ctx, item_code, warehouse, sle, g0, g1, qty, approx):
		"""Band [g0, g1] (qty units) of an incoming stock ledger entry: where did it come from?"""
		key = (sle.voucher_type, sle.voucher_no, sle.voucher_detail_no)
		if key in ctx["seen"]:
			add_untraced(ctx, _("Cycle in stock movements"), item_code, qty, sle.voucher_no)
			return
		child = {
			"line": ctx["line"],
			"path": [*ctx["path"], sle.voucher_no],
			"seen": [*ctx["seen"], key],
			"approx": ctx["approx"] or approx,
		}
		if sle.voucher_type == "Stock Entry":
			stock_entry_in(child, item_code, warehouse, sle, g0, g1, qty)
		elif sle.voucher_type == "Subcontracting Receipt":
			subcontracting_in(child, item_code, warehouse, sle, g0, g1, qty)
		else:
			add_untraced(child, _(sle.voucher_type), item_code, qty)

	def is_scrap_row(row):
		return bool(row.get("is_scrap_item") or row.get("is_legacy_scrap_item") or row.get("type") == "Scrap")

	def row_qty(row):
		return flt(row.get("transfer_qty")) or flt(row.get("qty")) * flt(row.get("conversion_factor") or 1)

	def stock_entry_in(ctx, item_code, warehouse, sle, g0, g1, qty):
		entry = get_doc("Stock Entry", sle.voucher_no)
		rows = entry.get("items") or []
		row = None
		for candidate in rows:
			if candidate.name == sle.voucher_detail_no:
				row = candidate
		if not row:
			add_untraced(ctx, _("Stock Entry row not found"), item_code, qty)
			return
		if row.s_warehouse and row.t_warehouse:
			trace_out(ctx, item_code, row.s_warehouse, "Stock Entry", entry.name, row.name, g0, g1)
			return
		inputs = [r for r in rows if r.s_warehouse and not r.t_warehouse]
		if is_scrap_row(row):
			if item_info(item_code).get("item_group") == scrap_item_group:
				add_untraced(ctx, _("Scrap"), item_code, qty)
				return
			end_piece_in(ctx, item_code, entry, row, inputs, g0, g1, qty)
			return
		if not inputs:
			add_untraced(ctx, _(entry.stock_entry_type or entry.purpose or "Stock Entry"), item_code, qty)
			return
		output_in(ctx, entry, row, rows, inputs, g0, g1)

	def end_piece_in(ctx, item_code, entry, row, inputs, g0, g1, qty):
		"""An End Piece is the parent sheet: map its kg onto the entry's same-unit inputs."""
		uom = item_info(item_code).get("stock_uom")
		same_unit = [r for r in inputs if item_info(r.item_code).get("stock_uom") == uom]
		total_in = sum(row_qty(r) for r in same_unit)
		if total_in <= eps:
			add_untraced(ctx, _("End Piece without same-unit inputs"), item_code, qty)
			return
		ratio = min(1.0, row_qty(row) / total_in)
		child = {**ctx, "path": [*ctx["path"][:-1], ctx["path"][-1] + " (" + _("End Piece") + ")"]}
		for source, h0, h1 in map_band(same_unit, row_qty, g0 * ratio, g1 * ratio):
			trace_out(
				child, source.item_code, source.s_warehouse, "Stock Entry", entry.name, source.name, h0, h1
			)

	def line_bands(outputs, sides, item_code):
		"""Each line's band (b0, b1, approximate) of the entry's input of item_code.

		Joint entries split a shared input by each line's BOM-derived demand
		(line gross x BOM input qty per unit), not by piece count.
		"""
		gross = {}
		bom_of = {}
		for out in outputs:
			side = out.get(joint_side_field) or ""
			gross[side] = gross.get(side, 0) + row_qty(out)
			if out.get("bom_no") and not out.get("custom_pea_is_rejection_item"):
				bom_of[side] = out.bom_no
		demand = {}
		approx = False
		for side in sides:
			if side in bom_of:
				demand[side] = gross[side] * bom_demand(bom_of[side]).get(item_code, 0)
			else:
				approx = True
		if approx or sum(demand.values()) <= eps:
			demand = gross
			approx = True
		total = sum(demand.get(side, 0) for side in sides)
		bands = {}
		start = 0.0
		for side in sides:
			width = demand.get(side, 0) / total if total > eps else 0
			bands[side] = (start, start + width, approx)
			start = start + width
		return bands

	def output_in(ctx, entry, row, rows, inputs, g0, g1):
		"""A finished/rejected output row: the same share of the inputs its line consumed."""
		outputs = [r for r in rows if r.t_warehouse and not r.s_warehouse and not is_scrap_row(r)]
		side = row.get(joint_side_field) or ""
		line_rows = [r for r in outputs if (r.get(joint_side_field) or "") == side]
		gross = sum(row_qty(r) for r in line_rows)
		if gross <= eps:
			add_untraced(ctx, _("Stock Entry output without quantity"), row.item_code, 0, keep_zero=True)
			return
		offset = 0.0
		for r in line_rows:
			if r.name == row.name:
				break
			offset = offset + row_qty(r)
		lf0 = (offset + g0 * row_qty(row)) / gross
		lf1 = (offset + g1 * row_qty(row)) / gross
		sides = []
		for r in outputs:
			value = r.get(joint_side_field) or ""
			if value not in sides:
				sides.append(value)
		if side and len(sides) > 1:
			label = ctx["path"][-1] + " (" + _("Joint") + " " + side + ")"
			ctx = {**ctx, "path": [*ctx["path"][:-1], label]}
		groups = []
		for r in inputs:
			if r.item_code not in groups:
				groups.append(r.item_code)
		for input_item in groups:
			group_rows = [r for r in inputs if r.item_code == input_item]
			# The sandbox has no tuple-unpacking assignment, so bands travel as (b0, b1, approx).
			band = (0.0, 1.0, False)
			if len(sides) > 1:
				band = line_bands(outputs, sides, input_item).get(side)
			width = band[1] - band[0]
			if width <= eps:
				continue
			h0 = band[0] + lf0 * width
			h1 = band[0] + lf1 * width
			for source, s0, s1 in map_band(group_rows, row_qty, h0, h1):
				trace_out(
					ctx,
					input_item,
					source.s_warehouse,
					"Stock Entry",
					entry.name,
					source.name,
					s0,
					s1,
					band[2],
				)

	def subcontracting_in(ctx, item_code, warehouse, sle, g0, g1, qty):
		"""Job work came back: the same share of the raw materials supplied for that row."""
		receipt = get_doc("Subcontracting Receipt", sle.voucher_no)
		row = None
		for candidate in receipt.get("items") or []:
			if candidate.name == sle.voucher_detail_no:
				row = candidate
		if not row:
			add_untraced(ctx, _("Subcontracting Receipt row not found"), item_code, qty)
			return
		factor = flt(row.conversion_factor) or 1
		accepted = flt(row.qty) * factor
		rejected = flt(row.rejected_qty) * factor
		total = accepted + rejected
		offset = 0.0
		size = accepted
		if rejected > eps and warehouse == row.rejected_warehouse and warehouse != row.warehouse:
			offset = accepted
			size = rejected
		if total <= eps:
			add_untraced(ctx, _("Subcontracting Receipt row without quantity"), item_code, qty)
			return
		f0 = (offset + g0 * size) / total
		f1 = (offset + g1 * size) / total
		supplied = [s for s in receipt.get("supplied_items") or [] if s.reference_name == row.name]
		if not supplied:
			add_untraced(ctx, _("Subcontracting Receipt without supplied items"), item_code, qty)
			return
		child = {**ctx, "path": [*ctx["path"][:-1], ctx["path"][-1] + " (" + _("job work") + ")"]}
		for s in supplied:
			trace_out(
				child,
				s.rm_item_code,
				receipt.supplier_warehouse,
				"Subcontracting Receipt",
				receipt.name,
				s.name,
				f0,
				f1,
			)

	line_filters = {"parent": document, "parenttype": doctype}
	if item_filter:
		line_filters["item_code"] = item_filter
	lines = frappe.get_all(
		doctype + " Item",
		filters=line_filters,
		fields=["name", "idx", "item_code", "warehouse", "stock_qty"],
		order_by="idx asc",
	)
	for line in lines:
		if not item_info(line.item_code).get("is_stock_item") or state["work_limit"]:
			continue
		ctx = {"line": line, "path": [document], "seen": [], "approx": False}
		trace_out(ctx, line.item_code, line.warehouse, doctype, document, line.name, 0.0, 1.0)

	columns = [
		{"fieldname": "line", "label": _("Line"), "fieldtype": "Int", "width": 60},
		{
			"fieldname": "line_item",
			"label": _("Line Item"),
			"fieldtype": "Link",
			"options": "Item",
			"width": 160,
		},
		{"fieldname": "line_qty", "label": _("Line Qty"), "fieldtype": "Float", "width": 90},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 200},
		{
			"fieldname": "item_code",
			"label": _("RM / Stopped At Item"),
			"fieldtype": "Link",
			"options": "Item",
			"width": 180,
		},
		{"fieldname": "batch_no", "label": _("Batch"), "fieldtype": "Data", "width": 160},
		{"fieldname": "qty", "label": _("Approx Qty"), "fieldtype": "Float", "width": 110},
		{"fieldname": "uom", "label": _("UOM"), "fieldtype": "Link", "options": "UOM", "width": 70},
		{"fieldname": "share", "label": _("Share %"), "fieldtype": "Percent", "width": 80},
		{"fieldname": "via", "label": _("Via"), "fieldtype": "Data", "width": 500},
	]

	def via_text(vias):
		text = " | ".join(vias[:via_limit])
		if len(vias) > via_limit:
			text = text + " | " + (_("+%s more chains") % (len(vias) - via_limit))
		return text

	rows = []
	for line in lines:
		line_traced = [(key, value) for key, value in traced.items() if key[0] == line.name]
		uom_totals = {}
		for key, value in line_traced:
			uom = item_info(key[1]).get("stock_uom")
			uom_totals[uom] = uom_totals.get(uom, 0) + value["qty"]
		for key, value in sorted(line_traced, key=lambda kv: -kv[1]["qty"]):
			uom = item_info(key[1]).get("stock_uom")
			status = _("Traced")
			if value["approx"]:
				status = _("Traced (approx: joint split without BOM)")
			rows.append(
				{
					"line": line.idx,
					"line_item": line.item_code,
					"line_qty": line.stock_qty,
					"status": status,
					"item_code": key[1],
					"batch_no": key[2],
					"qty": flt(value["qty"], precision),
					"uom": uom,
					"share": flt(100 * value["qty"] / uom_totals[uom], 2) if uom_totals[uom] > eps else 0,
					"via": via_text(value["via"]),
				}
			)
		for key, value in untraced.items():
			if key[0] != line.name:
				continue
			rows.append(
				{
					"line": line.idx,
					"line_item": line.item_code,
					"line_qty": line.stock_qty,
					"status": _("Untraced") + ": " + key[1],
					"item_code": key[2],
					"qty": flt(value["qty"], precision),
					"uom": item_info(key[2]).get("stock_uom"),
					"via": via_text(value["via"]),
				}
			)

	message = _(
		"Approximate, assuming first-in-first-out consumption on the floor and at job workers. "
		"An entry that consumed several RM batches is split between them in proportion to kg, and joint "
		"entries split shared inputs by each line's BOM. The split can blur kg between batches that were "
		"used, but never names a batch that was not."
	)
	return [columns, rows, message]


data = rm_batch_trace(filters)
