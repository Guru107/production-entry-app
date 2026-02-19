# Plan: HTML5 Canvas Timeline Redesign

## Context

The current timeline visualization on Workstation and Operator forms uses HTML divs with inline styles. It works but looks basic — plain colored rectangles in a gray bar with browser-native `title` tooltips. The goal is to replace this with a polished HTML5 Canvas implementation featuring gradient blocks, soft shadows, hourly gridlines, a pulsing "now" indicator, rich hover tooltips, and click-to-navigate.

**No backend changes needed.** The API (`api_timeline.py`) returns the same data shape. Only `timeline_renderer.js` changes.

---

## Design

### Visual Elements

```
┌─ Running Shift Timeline: SHIFT-2026.02.03.Shift-1 ──────────────────┐
│  08:00          09:00          10:00          11:00    ▼NOW   12:00  │
│  ┌─────────┐   ┌──────────────────┐  ┌─────┐                       │
│  │ FG-001  │   │    FG-002        │  │     │         (empty)        │
│  │ 120 OK  │   │    250 OK        │  │     │                        │
│  └─────────┘   └──────────────────┘  └─────┘                       │
│  ┊          ┊          ┊          ┊    |     ┊          ┊          ┊ │
│  08:00      09:00      10:00      11:00 NOW  12:00      ...   16:00 │
└──────────────────────────────────────────────────────────────────────┘
```

1. **Background**: Light gray (`#f0f0f0`) rounded rect with subtle inner shadow
2. **Gridlines**: Dashed vertical lines at each hour mark, with time labels below
3. **Entry blocks**: Rounded rects with vertical gradient (lighter top → saturated bottom), soft shadow, 2px gap between adjacent blocks
4. **Block labels**: When block width > 60px, render FG item name + OK qty inside; otherwise show on hover only
5. **Now indicator**: Dashed red vertical line with a small triangle marker at top, gentle pulse animation (opacity 0.6↔1.0)
6. **Hover tooltip**: Custom styled floating div (not canvas) positioned near cursor — shows SE name (as link), FG item, FG qty, rejection qty, OK qty, duration
7. **Click**: Clicking a block navigates to `/app/stock-entry/{name}`

### Color Palette

12-color palette with better aesthetics than raw HSL rotation:

```javascript
const PALETTE = [
  "#4C6EF5", // blue
  "#37B24D", // green
  "#F59F00", // amber
  "#E64980", // pink
  "#7950F2", // violet
  "#20C997", // teal
  "#FD7E14", // orange
  "#1098AD", // cyan
  "#AE3EC9", // grape
  "#74B816", // lime
  "#4DABF7", // light blue
  "#FF6B6B", // red
];
```

---

## Implementation

### File: `production_entry_app/public/js/timeline_renderer.js`

Complete rewrite of the IIFE module. The public API stays identical (`render_shift_timeline`, `set_html_field`) so `workstation.js` and `operator.js` require **zero changes**.

#### Architecture

```
render_shift_timeline(frm, doctype, htmlFieldname)
  └─ frappe.call → get_shift_timeline_data
       └─ _draw_canvas_timeline(container, data)
            ├─ _create_canvas(container)        // Create <canvas>, handle DPI
            ├─ _draw_background(ctx)             // Rounded rect, inner shadow
            ├─ _draw_gridlines(ctx, shiftStart, shiftEnd)  // Hourly dashed lines + labels
            ├─ _draw_entries(ctx, entries, ...)   // Gradient blocks with labels
            ├─ _draw_now_indicator(ctx, ...)      // Red dashed "now" line
            ├─ _setup_hover(canvas, entries, ...) // mousemove → tooltip div
            ├─ _setup_click(canvas, entries, ...) // click → navigate to SE
            └─ _animate_now_pulse(canvas, ...)    // requestAnimationFrame pulse
```

#### Key Implementation Details

**1. HiDPI Canvas Setup**
```javascript
function _create_canvas(container, width, height) {
    const canvas = document.createElement("canvas");
    const dpr = window.devicePixelRatio || 1;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    canvas.style.width = width + "px";
    canvas.style.height = height + "px";
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);
    return { canvas, ctx };
}
```

**2. Entry Block Rendering (gradient + shadow)**
```javascript
function _draw_entry_block(ctx, x, y, w, h, color) {
    ctx.save();
    // Shadow
    ctx.shadowColor = "rgba(0,0,0,0.15)";
    ctx.shadowBlur = 4;
    ctx.shadowOffsetY = 2;
    // Gradient fill
    const grad = ctx.createLinearGradient(x, y, x, y + h);
    grad.addColorStop(0, _lighten(color, 0.2));
    grad.addColorStop(1, color);
    ctx.fillStyle = grad;
    _rounded_rect(ctx, x, y, w, h, 4);
    ctx.fill();
    ctx.restore();
}
```

**3. Tooltip (HTML overlay, not canvas)**

A single positioned `<div>` outside the canvas, shown/hidden on `mousemove`. This avoids canvas redraw on every mouse move and allows rich HTML content with clickable links.

```javascript
function _setup_hover(canvas, hitBoxes, tooltip) {
    canvas.addEventListener("mousemove", (e) => {
        const rect = canvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        const hit = hitBoxes.find(
            (b) => x >= b.x && x <= b.x + b.w && y >= b.y && y <= b.y + b.h
        );
        if (hit) {
            canvas.style.cursor = "pointer";
            tooltip.innerHTML = `...entry details...`;
            tooltip.style.display = "block";
            // Position near cursor but within viewport
        } else {
            canvas.style.cursor = "default";
            tooltip.style.display = "none";
        }
    });
}
```

**4. Now Indicator Pulse Animation**

Uses `requestAnimationFrame` with a cleanup pattern (stored ref on the canvas element, cancelled on re-render or form unload):

```javascript
function _animate_now_pulse(canvas, ctx, nowX, barTop, barHeight) {
    let opacity = 1;
    let direction = -1;
    function frame() {
        // Only redraw the now-line area (clip rect)
        // ... draw dashed line at nowX with current opacity
        opacity += direction * 0.015;
        if (opacity <= 0.4) direction = 1;
        if (opacity >= 1) direction = -1;
        canvas._peaAnimFrame = requestAnimationFrame(frame);
    }
    canvas._peaAnimFrame = requestAnimationFrame(frame);
}
```

**5. Click to Navigate**
```javascript
canvas.addEventListener("click", (e) => {
    const hit = _find_hit(e, hitBoxes);
    if (hit) {
        frappe.set_route("stock-entry", hit.entry.name);
    }
});
```

**6. Responsive Width**

Canvas width = container width (read from `frm.fields_dict[htmlFieldname].$wrapper.width()`). On Frappe form resize, the canvas is redrawn.

**7. Empty State**

When no entries exist, draw centered text on canvas: "No production entries for current running shift." in muted gray.

### Canvas Dimensions

| Element | Value |
|---------|-------|
| Canvas height | 120px (label area 20px + bar 60px + time axis 24px + padding 16px) |
| Canvas width | Container width (responsive) |
| Bar border radius | 6px |
| Block border radius | 4px |
| Block vertical padding | 6px inside the bar |
| Grid label font | 11px system font |
| Block label font | 11px bold, white with text shadow |

### Tooltip Styling

```css
/* Inline styles on the tooltip div */
position: absolute;
z-index: 100;
background: white;
border: 1px solid #d1d5db;
border-radius: 8px;
padding: 10px 14px;
box-shadow: 0 4px 12px rgba(0,0,0,0.12);
font-size: 12px;
line-height: 1.6;
pointer-events: none;
max-width: 260px;
```

---

## Files Changed

| File | Change |
|------|--------|
| `production_entry_app/public/js/timeline_renderer.js` | Full rewrite — Canvas-based rendering |
| `production_entry_app/public/js/workstation.js` | No change (same API) |
| `production_entry_app/public/js/operator.js` | No change (same API) |
| `production_entry_app/production_entry_app/api_timeline.py` | No change |

**Only 1 file changes.** The entire rewrite is contained in `timeline_renderer.js`.

---

## Verification

1. `bench build` — ensure JS bundles without errors
2. Open a Workstation form with a Running shift and submitted Stock Entries → canvas renders with gradient blocks, hourly gridlines, and now indicator
3. Hover over a block → styled tooltip appears with entry details
4. Click a block → navigates to the Stock Entry form
5. Open an Operator form → same canvas renders correctly
6. Resize browser → canvas redraws at correct width
7. No running shift → "No running shift found." message displays
8. Running shift, no entries → empty bar with centered message
9. Existing tests pass: `bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_api_timeline`
10. E2E tests pass: `npx playwright test tests/e2e/specs/shift-batch2.spec.js`

codex resume 019c6f51-084c-7862-a7eb-94c52253e7d4
claude --resume 5a4a1ff3-c968-4441-8455-4f38210841f8
