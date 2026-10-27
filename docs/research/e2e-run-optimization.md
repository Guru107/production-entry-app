# E2E run time optimization

Research date: 2026-10-26. Scope: cut the ~30-minute-per-job Playwright E2E CI time (matrix jobs v15 and v16 in `.github/workflows/e2e.yml`). Research only; nothing implemented. Repo claims cite file:line. External claims cite URL + section. All minute figures in §7–§8 are estimates derived from the structure of the run, not from profiled CI logs.

## Sources opened

- Frappe Framework source, branch `version-15`: `frappe/auth.py`, `frappe/sessions.py`, `frappe/app.py`, `frappe/www/app.py`, `frappe/www/app.html`, `frappe/www/login.py` — via raw.githubusercontent.com/frappe/frappe/version-15/...
- Frappe Framework source, branch `version-16`: `frappe/auth.py` — via raw.githubusercontent.com/frappe/frappe/version-16/frappe/auth.py
- Playwright docs (suite pins `@playwright/test` 1.58.2, package.json):
  - <https://playwright.dev/docs/navigations> ("Basic navigation", "When is the page loaded?")
  - <https://playwright.dev/docs/test-parallel> ("Limit workers", "Test locks", "Isolate test data between parallel workers", "Worker index and parallel index")
  - <https://playwright.dev/docs/test-sharding> ("Balancing Shards", "GitHub Actions example", "Merging reports")
  - <https://playwright.dev/docs/videos> ("Record video")
  - <https://playwright.dev/docs/ci> ("Workers", "Caching browsers", "Global timeout", "Fail-Fast")
  - <https://playwright.dev/docs/browser-contexts> ("What is Test Isolation?")

## 1. Anatomy of the current run

Per CI job (one Frappe version):

1. **Bench build phase** — `bench init --skip-assets`, two `bench get-app`, `bench setup requirements --dev`, `bench build` (.github/workflows/e2e.yml:85-95), then `npx playwright install --with-deps chromium` (:105-107).
2. **Site phase** — `scripts/run_ephemeral_e2e.sh` creates the ephemeral site (:68), installs erpnext + app (:69-70), runs `bench build --app production_entry_app` (:71) **and `bench build --app frappe` (:76)** — i.e. Frappe's desk bundles are built a second time after the workflow's full `bench build` at e2e.yml:95 — installs fixtures, sets `developer_mode 1` and `allow_e2e_tests 1` (:83-84), starts `bench serve --noreload` (:90).
3. **Test phase** — 145 tests in 19 spec files, `workers: 1`, `fullyParallel: false` (playwright.config.js:13-14), each test in a fresh browser context with `storageState: admin.json` (:36).

Per test, three costs repeat:

- **CSRF-motivated Desk load at test start.** ~136 of 146 `goto(getRoute(...))` calls in specs go to `/home` (e.g. tests/e2e/specs/shift-lifecycle.spec.js:12,37,72,84; reports.spec.js:111). The page exists only so `getCsrfToken` can read `window.frappe.csrf_token` (tests/e2e/fixtures/frappe.js:19-38) for `callFrappeMethod` (frappe.js:40-47).
- **A second CSRF-motivated Desk load in afterEach.** `registerE2ELifecycle` (used by 15 of 20 spec files) runs `loginAsAdmin` + `page.goto(getRoute("/home"))` + `cleanupE2E` after every test (tests/e2e/fixtures/lifecycle.js:28-34). The goto exists because re-login replaces the `sid` cookie with a fresh session that has no CSRF token until a Desk page renders (see §2).
- **Video recording on every test.** `video: "retain-on-failure"` records every test and deletes the file on success (playwright.config.js:23; docs/videos "Record video": "'retain-on-failure' — Record video for each test, but remove all videos from successful test runs").

Per-test Desk loads therefore number ~2 (start + afterEach) plus the navigations the test itself needs (form/report pages). ~280–300 full Desk boots per run.

## 2. Question A — is the Desk load avoidable? (Frappe CSRF, primary source)

**Yes, on both versions, twice over.**

### 2.1 CSRF is enforced for cookie-session POSTs

`HTTPRequest.validate_csrf_token` runs for every non-OPTIONS request, including `/api/method/*` (frappe/app.py `init_request` constructs `HTTPRequest`; auth.py `UNSAFE_HTTP_METHODS = ("POST", "PUT", "DELETE", "PATCH")`):

- version-15 `frappe/auth.py`, `HTTPRequest.validate_csrf_token` (raw.githubusercontent.com/frappe/frappe/version-15/frappe/auth.py): early-returns only if the method is safe, **`frappe.conf.ignore_csrf` is truthy**, there is no session, **or no token was ever saved on the session** (`not (saved_token := frappe.session.data.csrf_token)`); otherwise it compares `X-Frappe-CSRF-Token` (or a `csrf_token` form field) to the saved token and `frappe.throw(..., frappe.CSRFTokenError)`.
- version-16 `frappe/auth.py`, same function (raw.githubusercontent.com/frappe/frappe/version-16/frappe/auth.py): identical logic plus one extra exemption, `self.is_allowed_referrer()` (Origin/Referer match against the `allowed_referrers` site config).

### 2.2 Why global-teardown's CSRF-less POST genuinely works

`Session.start` (frappe/sessions.py, version-15) never sets `csrf_token`. A token is created only by `generate_csrf_token()` via `get_csrf_token()` (same file), which is called from the Desk page renderer — `frappe/www/app.py` `get_context` (`csrf_token = frappe.sessions.get_csrf_token()` followed by `frappe.db.commit()`) — and embedded in the HTML as `frappe.csrf_token = "{{ csrf_token }}"` (`frappe/www/app.html`). `frappe/www/login.py` `get_context` does **not** set any CSRF token.

So a session created by `POST /api/method/login` has **no saved token**, and `validate_csrf_token` early-returns on `not (saved_token := ...)`. tests/e2e/global-teardown.js:26-28 therefore works by design of the "no saved token" path, not by the warn-and-continue path — *provided that sid never renders a Desk page* (the first Desk render would persist a token and subsequent token-less POSTs would throw CSRFTokenError). Note the teardown is skipped entirely in CI (`PLAYWRIGHT_EPHEMERAL_SITE === "1"`, global-teardown.js:7-9), so this only matters for local persistent-site runs.

### 2.3 Cheapest ways to a token-less or cheap-token setup

1. **`ignore_csrf` site config (best).** `frappe.conf.ignore_csrf` short-circuits the check on both branches (§2.1). The ephemeral site already carries test-only config (`developer_mode 1`, `allow_e2e_tests 1`; run_ephemeral_e2e.sh:83-84) and is dropped after the run (:45-49), so disabling CSRF there has no production security impact. This is the answer to question D's "config flag": it exists, though it appears to be undocumented — it is visible only in source.
2. **Rely on the no-saved-token path (zero config).** As long as bootstrap/cleanup POSTs go through a session that never renders Desk (e.g. `loginAsAdmin`'s fresh sid in lifecycle.js:8-18), any header value — or none — passes. This is fragile by inspection: one stray Desk render on that sid flips it to hard failures.
3. **API key auth.** `Authorization: token api_key:api_secret` (frappe/auth.py `validate_auth_via_api_keys`, both branches) authenticates without a cookie session; a cookie-less request resumes as Guest whose session data has no `csrf_token`, so CSRF passes. Needs key generation in setup; bigger diff than option 1.
4. **Read the token from server-rendered HTML.** `/app` embeds `frappe.csrf_token` in the HTML (app.html above), so a plain `request.get` could scrape it — but the server still renders full bootinfo for that response (`frappe/sessions.py` `get()` → `frappe/boot.py` `get_bootinfo()`), so it saves only browser JS execution, not server work. Strictly worse than option 1.

## 3. Question B — Playwright levers (docs, v1.58.x)

- **`page.goto` waits for `load` by default** (docs/navigations, "Basic navigation": "loads the page and waits for the web page to fire the `load` event … including all dependent resources"). Docs also state interaction is safe earlier because actions auto-wait ("When is the page loaded?"). This suite already gates on app-level readiness (`waitForFunction(() => Boolean(window.cur_frm?.doc))`, frappe.js:13,79,136-146), so `waitUntil: "domcontentloaded"` is safe for Desk navigations and returns earlier per navigation. Small win (~150+ in-flow navigations).
- **Video cost.** Docs/videos quantifies nothing, but `retain-on-failure` records for *every* test (§1). `on-first-retry` records only when a test is retried; the config already retries once in CI (playwright.config.js:26), so failures still yield a video — of the retry, not the original run. **This is the one lever that weakens failure debugging** for tests that fail differently on retry.
- **Browser contexts are not the bottleneck.** Docs/browser-contexts: contexts are "fast and cheap to create and are completely isolated". The cost here is the Desk app boot per *page load* (JS bundle fetch+execute in a cache-less fresh context), not context creation.
- **Parallelism/sharding are officially supported.** Docs/test-parallel: workers via `--workers`/`workers` config; "Test locks" (`test('...', { lock: 'name' })`) serialize named shared resources across workers and projects; "Isolate test data between parallel workers" is exactly this repo's `e2ePrefix(testInfo)` pattern using `workerIndex` (tests/e2e/fixtures/prefix.js:1-10 — prefix already embeds `W<workerIndex>`). Docs/test-sharding: `--shard=x/y` splits by **file** without `fullyParallel` ("Balancing Shards" — uneven files yield uneven shards; reports.spec.js is 814 lines / 22 gotos, so shards of these 19 uneven files will balance poorly), with a GitHub Actions matrix example and blob-report merging.
- **Docs recommend `workers: 1` on shared CI runners** (docs/ci, "Workers") — which this repo follows — and suggest sharding for wider parallelism.

## 4. Question C — GitHub Actions / bench setup levers

- **Playwright browser install.** Docs/ci, "Caching browsers": "Caching browser binaries is not recommended, since the amount of time it takes to restore the cache is comparable to the time it takes to download the binaries. Especially under Linux, operating system dependencies need to be installed, which are not cacheable. If you still want to cache … against a hash of the Playwright version." So: caching `~/.cache/ms-playwright` keyed by the `@playwright/test` version is *possible but officially discouraged*; the `--with-deps` apt half (e2e.yml:107) cannot be cached and re-runs every job. The officially blessed alternative is the prebuilt container `mcr.microsoft.com/playwright:v<version>-noble` (docs/ci, "Via Containers") — browsers + OS deps preinstalled — but this job also needs MariaDB/Redis services and a Python bench toolchain, so adopting it is a workflow restructure, not a tweak.
- **Redundant bench builds (concrete, in-repo).** The workflow runs `bench build` (all apps) at e2e.yml:95; the runner script then rebuilds `production_entry_app` **and `frappe`** (run_ephemeral_e2e.sh:71,76). In CI both script builds are fully redundant (the v16 half-boot comment at :72-75 applies to `--skip-assets` benches that never ran a full build; CI did). Skipping them when assets already exist removes two webpack/esbuild desk builds per job.
- **Caching `~/frappe-bench`.** `bench init` re-clones frappe and `get-app` re-clones erpnext every run (e2e.yml:88,92-93). Caching `~/frappe-bench/apps` (plus `env`, plus `sites/assets`) keyed on OS + Python/Node versions + branch could skip clones, pip installs and builds, but it caches a multi-GB moving target keyed to upstream branch heads — high invalidation churn and correctness risk (stale frappe/erpnext while the matrix claims to test them). Not recommended as a first move; the redundant-build removal above captures the safe share of the same minutes.

## 5. Question D — server-side knobs

- `ignore_csrf` config: exists on both branches (§2.3.1). One line in run_ephemeral_e2e.sh next to :83-84.
- `bench serve` is already threaded: frappe/app.py `serve(...)` ends with `threaded=not no_threading`, and the script passes only `--noreload` (run_ephemeral_e2e.sh:90) — so the Werkzeug dev server handles concurrent requests. Concurrency would still serialize on the GIL for Python work, and the single dev server is not the constraint at `workers: 1`.
- No other E2E-relevant speed config surfaced in the sources read.

## 6. Parallelism feasibility on one site (finding 6, assessed)

Data is per-prefix for most artifacts: warehouses, items, operator, workstation, department, BOMs, shift (e2e_api.py:678-817), and the prefix embeds the worker index (prefix.js:2,9). But `workers>1` against one site is **not safe today**:

1. `bootstrap_e2e_context(cleanup_running=1)` calls `cleanup_running_shifts()`, which completes **every** Running Shift site-wide (utils/test_bootstrap.py:519-521), and `_complete_other_running_e2e_shifts` completes Running shifts of **other** E2E departments (e2e_api.py:554-569, called at :808). Worker A's bootstrap can kill worker B's mid-test Running shift.
2. Settings snapshot/restore mutates global singletons per prefix (Production Entry Settings, System Settings `float_precision`, Stock Entry Type rework flags; e2e_api.py:265-361, 861-871) — concurrent workers would poison each other's snapshots. Playwright's named test locks (docs/test-parallel) could serialize this subset, but not hazard 1.
3. Company and Branch are shared across prefixes (utils/test_bootstrap.py:27-54).

Sharding across jobs/machines (docs/test-sharding) has none of these hazards — each shard job gets its own ephemeral bench site and DB (run_ephemeral_e2e.sh creates/drops one per invocation). Cost: each shard repeats the full setup phase, and file-level sharding of uneven files balances poorly (§3).

## 7. Time budget estimate (per ~30-min job)

Estimates, not measurements. Desk boot = server boot render + multi-MB JS bundle fetch/execute in a cache-less context; assumed 2–4 s on a CI runner.

| Phase | What | Est. time |
|---|---|---|
| CI setup | bench init, get-app ×2, requirements, `bench build`, playwright `--with-deps` | 10–15 min |
| Site setup | new-site, install-app ×2, two redundant `bench build`, fixtures, serve startup | 5–8 min |
| Test phase | 145 tests, serial | 12–18 min |
| ↳ CSRF Desk loads | ~136 start `/home` + ~134 afterEach `/home` ≈ 270 loads × 2–4 s | 9–18 min of test phase |
| ↳ bootstrap/cleanup API | ~145 × (bootstrap 1–3 s + cleanup 1–2 s), server-side | 4–8 min of test phase |
| ↳ actual UI flow + video overhead | remainder | remainder |

The single biggest lever is removing CSRF-motivated Desk loads (§2): it converts ~270 Desk boots into zero and also removes the afterEach navigation's flakiness surface.

## 8. Ranked recommendations

| # | Change | Est. saved / job | Risk | Effort |
|---|---|---|---|---|
| 1 | `bench --site "$SITE_NAME" set-config ignore_csrf 1` in run_ephemeral_e2e.sh; make `callFrappeMethod` not require a page token (fixtures/frappe.js:40-47); delete the start-of-test `/home` gotos where the test navigates on anyway (~136 sites) and the afterEach goto (lifecycle.js:30-32) | 8–15 min | Low. Ephemeral site is dropped post-run; CSRF still exercised implicitly because Desk sends the token. Verify no spec asserts CSRF behavior. | Small (one config line + fixture tweak + mechanical goto removal) |
| 2 | Skip the two redundant `bench build` calls in CI (run_ephemeral_e2e.sh:71,76 — already built at e2e.yml:95) | 1–3 min | Low. Keep them for local runs (gate on asset presence or an env flag). | Tiny |
| 3 | `video: "on-first-retry"` instead of `retain-on-failure` (playwright.config.js:23) | ~0.5–1.5 min (docs give no number; estimate) | **Weakens failure debugging**: video covers the retry, not the first failure. Keep `screenshot` and `trace` as-is. | One line |
| 4 | Cache `~/.cache/ms-playwright` keyed by `@playwright/test` version; keep `--with-deps` (uncacheable OS deps) | 1–3 min | Low; officially "not recommended" because restore ≈ download (docs/ci) — measure before keeping | Small workflow change |
| 5 | Shard each version job 2 ways via the docs/test-sharding GitHub Actions matrix pattern (each shard = own ephemeral site) | test phase ≈ halves; net −5–8 min wall after #1/#2 | Low correctness risk (separate sites); uneven file-level shards (§3, §6); doubles CI-minute consumption and job count | Medium (workflow + blob report merge) |
| 6 | `waitUntil: "domcontentloaded"` on Desk navigations | 0.5–1 min | Low; suite already waits on `cur_frm`/`window.frappe` | Small |
| — | `workers>1` on one site | (rejected) | High: cross-prefix shift completion and global settings mutation (§6) | Requires e2e_api.py changes first |
| — | Cache `~/frappe-bench` | (rejected for now) | Stale-branch correctness risk, cache churn (§4) | — |
| — | Add `globalTimeout` (docs/ci) alongside `timeout-minutes: 60` (e2e.yml:20) | 0 min — reliability only: guarantees a report on hangs | None | One line |

## 9. Measured CI evidence (run 40321352729, 2026-10-26, both jobs green)

Timestamps from the GitHub job logs (`gh api .../actions/jobs/<id>/logs`). This supersedes the §7 estimates where they disagree.

| Phase | v15 measured | v16 measured | §7 estimate |
|---|---|---|---|
| Setup (checkout, setup-python/node, mariadb-client) | ~0.8 min | ~3.1 min (apt stall) | 10–15 min (too high) |
| `bench init` + get-app ×2 + requirements + `bench build` | 1.4 min | 1.7 min | (part of above) |
| `npx playwright install --with-deps chromium` | 0.3 min | **12.2 min** | 1–3 min |
| Site setup in `run_ephemeral_e2e.sh` (new-site → serve up, incl. the two redundant builds) | 2.5 min | 2.0 min | 5–8 min (too high) |
| Test phase (147 tests, 1 worker) | **26.9 min** | **19.0 min** | 12–18 min (too low for v15) |
| Job wall | 31.8 min | 37.6 min (25.4 without the apt stall) | ~30 min |

Corrections to earlier assumptions:

- **A Desk boot is ≤1 s on CI, not 2–4 s.** Proof: `downtime-reason.spec.js` "requires a code…" completes in 1.1 s on v15 while containing a cold-context Desk form load (`goto /downtime-reason/new`), and `shift-lifecycle.spec.js` "cleanup is idempotent" fits 3 Desk loads + 4 API calls in 6.7 s. Consequence: removing the ~270 CSRF-only `/home` loads saves **~3–5 min (v15) / ~2–3 min (v16)**, not 9–18 min. Still the biggest *code* lever in the test phase.
- **Playwright-reported test durations already include hooks** (beforeEach/afterEach), so inter-test overhead is ~0 (median 0.0 s): bootstrap, both `/home` loads, and cleanup all live inside the reported 10.6 s (v15) / 7.1 s (v16) median. Nothing is "hidden" between tests.
- **The v16 12.2 min browser install was an apt mirror stall**, not the browser download: log line `Fetched 25.2 MB in 11min 48s (35.7 kB/s)` during the `--with-deps` apt phase; the Chromium zip itself took ~5 s on v15. Browser-binary caching (§8 #4) would NOT have helped; the binary download is already seconds. Mitigation options: accept the variance, add apt retries, or restructure onto the Playwright container image (§4). Not cacheable.
- **v15 runs the same suite ~41% slower than v16** (median 10.6 s vs 7.1 s; reports.spec.js 5.3 m vs 3.6 m). The v15 job is the wall-clock constraint of the matrix.
- **reports.spec.js is the slowest file** (5.3 min v15, 22 tests) — it is also the balance floor for file-level sharding: no shard can finish faster than ~5.3 min + setup on v15.
- One flaky retry on v16 (`rework-lifecycle.spec.js:378` failed once, passed on retry) — retries:1 already absorbs it; cost ≈ one test duration.
- Site-setup teardown (`bench drop-site`) ~5 s; negligible.

Revised lever table (measured, per job):

| Change | v15 | v16 | Note |
|---|---|---|---|
| Remove CSRF-only Desk loads (§8 #1) | −3 to −5 min | −2 to −3 min | estimate revised down from §7 |
| Drop redundant script `bench build`s (§8 #2) | ~−0.5–1 min | ~−0.5–1 min | site setup measured at 2–2.5 min total |
| **Shard ×2** (own ephemeral site per shard) | wall ≈ 5 + 13.5 ≈ **18.5 min** | wall ≈ 5 + 9.5 ≈ **14.5 min** | biggest *wall-clock* lever; floor set by reports.spec.js ≈ 10.3 min on v15 |
| Shard ×3 | wall ≈ 14 min | wall ≈ 11 min | diminishing; reports.spec.js shard approaches the floor |
| Browser cache / container image | 0 normally; avoids rare 12-min apt stalls (container only) | same | apt stall is the observed failure mode, not download time |

## Recommended order (revised after measurement)

1. **#1 (ignore_csrf + delete CSRF-only Desk loads)** — still first: biggest code lever, low risk, and it shrinks the phase that sharding then divides. Measured: ~3–5 min/job.
2. **#2 (drop redundant bench builds)** — ~0.5–1 min, trivially safe in CI.
3. **#5 (shard ×2 per version)** — the biggest wall-clock lever per §9: v15 ≈ 18.5 min, v16 ≈ 14.5 min. Setup is only ~5 min, so sharding pays better than the pre-measurement estimate suggested. Balance floor: reports.spec.js.
4. **#6 (domcontentloaded)** — small, safe, do whenever a navigation is touched.
5. **#3 (video on-first-retry)** only if losing first-failure video is acceptable; **#4 (browser cache)** rejected by measurement — the observed 12-min stall was apt (`--with-deps`), which no browser cache fixes; if stalls recur, evaluate the Playwright container image instead.
