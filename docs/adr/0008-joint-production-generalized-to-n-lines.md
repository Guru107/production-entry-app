# Joint Production generalized to N BOM lines

A single forming die tool now produces three parts per stroke. Each part has its own BOM with its own
input item; only the die tool, the time window, and the stroke count are shared. The existing Joint
Production Stock Entry Type — not yet used by any entry on the production site — is redefined to cover
this case generally: a Joint Production entry carries a child table of **Joint Production Lines**
(BOM, gross quantity, rejection quantity), two or more lines, and the output composition is not
constrained. Lines may produce the same finished item (the previous same-item pairing) or distinct
finished items (the multi-part die). Every line consumes its own BOM's inputs independently for every
Operation, exactly like the post-Shearing plan; the Shearing shared-sheet material plan stays exclusive
to Joint LH/RH Production. One Die Tool Item and one Total Press Strokes value belong to the entry, and
the die tool counter counts the strokes once per run, not per line.

This supersedes the Joint Production pairing recorded in ADR 0003 ("pairs two BOMs of one finished item
whose inputs differ"). Joint LH/RH Production is unchanged: it keeps its two header slots, its LH/RH
labels, and the Shearing shared-sheet semantics. A two-line Joint Production entry with distinct
finished items is therefore expressible in both joint types; the overlap is accepted. Joint LH/RH is
the mirrored-pair pairing, Joint Production the independent-recipes pairing.

## Data model

- The LH/RH header field pairs are not reused for Joint Production. A Joint Production Line child
  DocType on Stock Entry carries `bom_no`, `gross_qty`, and `rejection_qty` per line. The Joint LH/RH
  header pairs remain in the fixture for that type only.
- Output Side labels generalize from "BOM 1"/"BOM 2" to "BOM 1"…"BOM N" on Stock Entry Detail rows
  (`custom_pea_joint_output_side`) and Rejection Breakup rows (`output_side`).
- Validation changes shape, not strength: two or more lines (one line is a Manufacture Production
  Entry), BOMs distinct across lines, no two lines repeat the same finished item and input item set
  (generalizing "Joint Production BOMs must use different raw materials"), and the existing per-BOM
  rules (submitted and active, Operation match, Company match, positive inputs and quantities) apply
  per line.
- Because the type has no submitted entries in production, no migration or backfill is needed; drafts
  saved before the change must be re-fetched.

## Report changes

Reports classify Joint Production entries from the Stock Entry Type flag, as before
(`add_stock_entry_type_flags`, `paired_repack_type_criterion` are unchanged), but every reader that
assumes the two header slots moves to line-derived facts:

- **Slot machinery** (`report_utils.py`): `OutputSlot` survives as the reader-facing shape.
  `paired_output_slots` returns the static LH/RH header slots for Joint LH/RH entries and N
  line-derived slots for Joint Production entries. `get_entry_output_quantities` and
  `get_item_bom_quality_facts` already iterate slots, so their meaning (entry totals, per-side
  quality facts keyed by `(parent, side)`) is unchanged at any N.
- **Line loading**: header quantities ride along in the parent query today
  (`iter_stock_entries_in_chunks` appends the four LH/RH quantity fields to every chunk). Joint
  Production lines are child rows, so the chunk pipeline attaches them with one batched child-table
  query per chunk, keyed by parent, before flags are enriched — no per-entry queries, no N+1.
- **Static side list removed**: `_get_joint_output_item_map` filters
  `custom_pea_joint_output_side.isin(_JOINT_OUTPUT_SIDES)` against the fixed set LH/RH/BOM 1/BOM 2.
  The set is replaced by a dynamic filter (or dropped in favour of the existing non-scrap criterion)
  so "BOM 3" and beyond resolve their output items.
- **BOM filter matching**: `get_stock_entries_for_bom` matches Joint LH/RH entries through the header
  fields and everything through `Stock Entry Detail.bom_no`. Joint Production entries match through
  their line rows (the detail-row `bom_no` path already covers the materialized good-output rows, so
  the line table only needs checking where headers were checked).
- **Per-BOM attribution preserved**: the Shift per-BOM aggregate attributes the entry's full
  Total Press Strokes and production minutes to each line's BOM — the existing convention at two
  lines, kept at N (every recipe ran on every stroke).
- **Per-line item attribution**: `_build_item_bom_rows` keyed Joint Production aggregates on one
  entry-level item code, which was only correct while all lines produced the same finished item. It
  now derives the item per line from the BOM, as `get_shift_aggregate_production_entries` already does
  with its BOM-to-item map.
- **Unchanged surfaces**: Production OEE and Monthly Production OEE (their quality bases come from
  `get_entry_output_quantities` slot sums, so entry totals keep one meaning), FG-item report filters
  (row-based, mode-agnostic), `get_parent_quantity_metrics` and Rejection Breakup aggregation
  (`output_side` is a string key), die tool stroke and maintenance reports (the counter is keyed on
  the Die Tool Item), operator SPM reports (entry-level strokes), and every rework report (Rework
  Operations are separate Material Transfer entries). Paired entries still skip
  `_set_entry_metrics`, and die tool health metrics still key on the Die Tool Item.

## Considered Options

- **A third Stock Entry Type for multi-part dies.** Rejected: the pairing is the same concept as Joint
  Production at N=3 — one run, multiple recipes, shared die and strokes — so a third type would
  duplicate the engine and the UI for a cardinality difference.
- **N header field pairs.** Rejected: it re-fixes the arity that just changed, and the form layout
  cannot grow a field pair per part.
- **One multi-output BOM with the extra parts as BOM scrap** (the End Piece mechanism). Rejected:
  End Pieces are salvage — scrap by definition, routed to the Scrap Warehouse at the BOM scrap rate.
  The three die parts are intended co-products that must land in WIP as good output with allocated
  value, per-line rejection, and per-line rework tracking. BOM scrap cannot express that.
- **Unify Joint LH/RH into the same line table.** Deferred: LH/RH entries exist in production and the
  type owns the Shearing shared-sheet plan. Generalizing it is a separate decision with a migration
  cost; nothing in this change blocks it later.

## Consequences

- Three Stock Entry Types remain (two joint, one rework) and exactly one type per pairing still holds;
  ADR 0003's type-uniqueness enforcement is untouched.
- Reports must load Joint Production lines before reading slots; an entry flagged Joint Production
  with no lines attached is invalid and fails validation loudly rather than reporting zero.
- CONTEXT.md's Joint Production entry is rewritten and Joint Production Line is added as the term for
  the child row.
- The duplicate-recipe guard is deliberately weaker than the old pairwise rule: two lines may share
  the same finished item with different inputs (the original pairing), or distinct items with any
  inputs; only an exact recipe repeat is rejected.
