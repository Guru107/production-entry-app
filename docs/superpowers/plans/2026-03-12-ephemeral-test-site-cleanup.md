# Ephemeral Test Site Cleanup Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run authoritative Python and Playwright suites against disposable Frappe sites that are always dropped at the end of the run.

**Architecture:** Add a small shared helper module for ephemeral-site naming, validation, and stale-site discovery, then wrap Python and E2E test execution in explicit create/setup/run/drop scripts. Keep existing per-test cleanup for local persistent-site workflows, but move end-of-run correctness to site deletion instead of document-by-document sweeping.

**Tech Stack:** Frappe/ERPNext bench CLI, Python 3.10, Bash, GitHub Actions, Playwright

---

## File Structure

**Create**
- `production_entry_app/production_entry_app/utils/ephemeral_test_site.py`
  - shared naming, allowlist validation, stale-site discovery, and small command builders
- `production_entry_app/production_entry_app/utils/test_ephemeral_test_site.py`
  - unit tests for ephemeral-site helper behavior
- `scripts/run_ephemeral_python_tests.sh`
  - authoritative Python suite wrapper: create site, configure, setup, run tests, drop site
- `scripts/run_ephemeral_e2e.sh`
  - authoritative Playwright wrapper: create site, configure, setup, serve, run tests, drop site
- `scripts/cleanup_stale_ephemeral_sites.py`
  - manual recovery utility for stale `pea-py-*` and `pea-e2e-*` sites

**Modify**
- `.github/workflows/ci.yml`
  - replace inline persistent-site Python setup with the Python wrapper
- `.github/workflows/e2e.yml`
  - replace inline persistent-site E2E setup with the E2E wrapper
- `playwright.config.js`
  - keep `PLAYWRIGHT_BASE_URL` / credential env usage explicit for ephemeral runners
- `tests/e2e/global-teardown.js`
  - keep as best-effort local cleanup and make its non-authoritative role explicit
- `production_entry_app/production_entry_app/utils/test_setup.py`
  - keep local bootstrap focused on per-site setup, not suite-final cleanup ownership
- `production_entry_app/production_entry_app/utils/test_cleanup.py`
  - keep local fallback cleanup but document that authoritative cleanup now happens at site level
- `README.md`
  - document authoritative ephemeral runs vs local persistent-site debugging

**Test**
- `production_entry_app/production_entry_app/utils/test_ephemeral_test_site.py`
- focused workflow-script smoke runs executed locally from the bench

## Chunk 1: Shared Ephemeral Site Helper

### Task 1: Add helper tests first

**Files:**
- Create: `production_entry_app/production_entry_app/utils/test_ephemeral_test_site.py`
- Create: `production_entry_app/production_entry_app/utils/ephemeral_test_site.py`

- [ ] **Step 1: Write the failing tests**

```python
from production_entry_app.production_entry_app.utils import ephemeral_test_site


def test_build_site_name_uses_expected_prefix_and_run_id() -> None:
	assert ephemeral_test_site.build_site_name("py", "abc123") == "pea-py-abc123.localhost"


def test_validate_ephemeral_site_accepts_allowed_prefixes_only() -> None:
	assert ephemeral_test_site.validate_ephemeral_site_name("pea-e2e-42.localhost") is None


def test_validate_ephemeral_site_rejects_non_ephemeral_names() -> None:
	with pytest.raises(frappe.ValidationError):
		ephemeral_test_site.validate_ephemeral_site_name("development.localhost")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.utils.test_ephemeral_test_site
```

Expected: FAIL because the helper module and tests do not exist yet.

- [ ] **Step 3: Write the minimal helper implementation**

```python
EPHEMERAL_SITE_PREFIXES: tuple[str, ...] = ("pea-py-", "pea-e2e-")


def build_site_name(kind: str, run_id: str) -> str:
	return f"pea-{kind}-{run_id}.localhost"


def validate_ephemeral_site_name(site_name: str) -> None:
	if not site_name.startswith(EPHEMERAL_SITE_PREFIXES):
		frappe.throw(_("Refusing to operate on non-ephemeral site {0}").format(site_name))
```

Also add helpers for:
- discovering stale site directories by prefix
- extracting age / last modified time
- returning bench CLI argument lists used by the wrapper scripts

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.utils.test_ephemeral_test_site
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add production_entry_app/production_entry_app/utils/ephemeral_test_site.py production_entry_app/production_entry_app/utils/test_ephemeral_test_site.py
git commit -m "Add ephemeral test site helper"
```

### Task 2: Add stale-site recovery coverage

**Files:**
- Modify: `production_entry_app/production_entry_app/utils/test_ephemeral_test_site.py`
- Modify: `production_entry_app/production_entry_app/utils/ephemeral_test_site.py`
- Create: `scripts/cleanup_stale_ephemeral_sites.py`

- [ ] **Step 1: Write the failing tests**

Add tests for:
- stale-site filtering only returns `pea-py-*` and `pea-e2e-*`
- recovery output includes age / modified timestamp
- deletion commands are refused for non-ephemeral names

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.utils.test_ephemeral_test_site
```

Expected: FAIL on missing recovery helpers.

- [ ] **Step 3: Implement the recovery utility**

Implement:
- pure-Python helper functions in `ephemeral_test_site.py`
- a thin CLI in `scripts/cleanup_stale_ephemeral_sites.py` that lists stale sites by default
- explicit `--delete <site>` behavior guarded by `validate_ephemeral_site_name(...)`

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.utils.test_ephemeral_test_site
python scripts/cleanup_stale_ephemeral_sites.py --help
```

Expected: tests PASS, CLI prints help.

- [ ] **Step 5: Commit**

```bash
git add production_entry_app/production_entry_app/utils/ephemeral_test_site.py production_entry_app/production_entry_app/utils/test_ephemeral_test_site.py scripts/cleanup_stale_ephemeral_sites.py
git commit -m "Add stale ephemeral site recovery tooling"
```

## Chunk 2: Python Authoritative Runner

### Task 3: Write Python runner script tests and setup contracts

**Files:**
- Modify: `production_entry_app/production_entry_app/utils/test_setup.py`
- Modify: `production_entry_app/production_entry_app/utils/test_cleanup.py`
- Create: `scripts/run_ephemeral_python_tests.sh`
- Modify: `.github/workflows/ci.yml`
- Test: `production_entry_app/production_entry_app/utils/test_test_setup.py`

- [ ] **Step 1: Write the failing tests**

Add/adjust tests to enforce:
- `before_tests()` remains site-local bootstrap only
- authoritative suite cleanup is not encoded inside `before_tests()`
- the Python runner requires `allow_tests=true` before `run-tests`

Example assertion:

```python
def test_before_tests_does_not_assume_global_suite_teardown() -> None:
	test_setup.before_tests()
	assert True
```

Use mocks around the new wrapper command builder rather than trying to create/drop sites in unit tests.

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.utils.test_test_setup
```

Expected: FAIL because the new runner contract is not represented yet.

- [ ] **Step 3: Implement the Python runner**

Implement `scripts/run_ephemeral_python_tests.sh` to:
1. generate a unique `pea-py-<run-id>.localhost` site name
2. create the site with deterministic admin password
3. install `erpnext` and `production_entry_app`
4. run fixtures install
5. set `allow_tests=true`
6. run `production_entry_app.production_entry_app.utils.test_setup.before_tests`
7. run `bench --site <site> run-tests --app production_entry_app`
8. drop the site in a shell `trap` even when tests fail

Keep the script simple Bash with small Python/helper calls only where they improve validation.

- [ ] **Step 4: Update CI to use the wrapper**

Replace the inline site creation block in `.github/workflows/ci.yml` with the new script invocation.

- [ ] **Step 5: Run verification**

Run:
```bash
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.utils.test_test_setup
bash scripts/run_ephemeral_python_tests.sh production_entry_app.production_entry_app.utils.test_ephemeral_test_site
```

Expected: unit tests PASS; wrapper creates and drops a temporary site cleanly.

- [ ] **Step 6: Commit**

```bash
git add production_entry_app/production_entry_app/utils/test_setup.py production_entry_app/production_entry_app/utils/test_cleanup.py production_entry_app/production_entry_app/utils/test_test_setup.py scripts/run_ephemeral_python_tests.sh .github/workflows/ci.yml
git commit -m "Run Python tests on ephemeral sites"
```

## Chunk 3: Playwright Authoritative Runner

### Task 4: Lock the E2E runner contract to the new site lifecycle

**Files:**
- Create: `scripts/run_ephemeral_e2e.sh`
- Modify: `.github/workflows/e2e.yml`
- Modify: `playwright.config.js`
- Modify: `tests/e2e/global-teardown.js`
- Modify: `README.md`
- Test: `production_entry_app/production_entry_app/test_api.py`

- [ ] **Step 1: Write the failing tests**

Add/adjust tests to enforce:
- the documented E2E bootstrap still requires `allow_e2e_tests`
- the local cleanup endpoint remains callable, but authoritative correctness does not depend on it
- any helper that builds E2E runner env exports deterministic admin credentials

Example unit target:

```python
def test_assert_e2e_api_allowed_blocks_without_allow_e2e_tests_flag(self) -> None:
	...
```

The failing part here should be missing coverage for the new runner assumptions, not browser automation itself.

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_api
```

Expected: FAIL on new runner-contract assertions.

- [ ] **Step 3: Implement the E2E wrapper**

Implement `scripts/run_ephemeral_e2e.sh` to:
1. generate `pea-e2e-<run-id>.localhost`
2. create the site with `--admin-password 123` or another deterministic exported value
3. install apps and fixtures
4. run `erpnext.setup.utils.before_tests`
5. set `developer_mode=1` and `allow_e2e_tests=1`
6. start `bench --site <site> serve --port 8002 --noreload`
7. export `PLAYWRIGHT_BASE_URL=http://localhost:8002`, `PLAYWRIGHT_USERNAME=Administrator`, `PLAYWRIGHT_PASSWORD=<password>`
8. run `npm run test:e2e` or `npm run test:e2e:ci`
9. stop the web server and drop the site in `trap` cleanup

- [ ] **Step 4: Update workflow and local teardown expectations**

Update `.github/workflows/e2e.yml`, `playwright.config.js`, and `tests/e2e/global-teardown.js` so:
- CI uses the wrapper script
- `globalTeardown` is clearly best-effort only
- local persistent-site runs still work without forcing site deletion semantics

- [ ] **Step 5: Run verification**

Run:
```bash
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_api
npx playwright test tests/e2e/specs/auth.setup.spec.js
bash scripts/run_ephemeral_e2e.sh smoke
```

Expected: API tests PASS; setup auth spec passes against the ephemeral runner; the wrapper drops the site after the smoke suite.

- [ ] **Step 6: Update docs and commit**

Document:
- authoritative ephemeral commands
- local persistent-site fallback expectations
- stale-site recovery command

Commit:

```bash
git add scripts/run_ephemeral_e2e.sh .github/workflows/e2e.yml playwright.config.js tests/e2e/global-teardown.js README.md production_entry_app/production_entry_app/test_api.py
git commit -m "Run Playwright suites on ephemeral sites"
```

## Chunk 4: Final Verification

### Task 5: End-to-end validation and cleanup checks

**Files:**
- Modify: `README.md`
- Verify: `.github/workflows/ci.yml`
- Verify: `.github/workflows/e2e.yml`

- [ ] **Step 1: Run formatting and targeted tests**

Run:
```bash
pre-commit run --all-files
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.utils.test_ephemeral_test_site
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.utils.test_test_setup
bench --site development.localhost run-tests --app production_entry_app --module production_entry_app.production_entry_app.test_api
```

Expected: PASS.

- [ ] **Step 2: Run both authoritative wrappers**

Run:
```bash
bash scripts/run_ephemeral_python_tests.sh production_entry_app.production_entry_app.utils.test_ephemeral_test_site
bash scripts/run_ephemeral_e2e.sh smoke
python scripts/cleanup_stale_ephemeral_sites.py
```

Expected:
- both wrappers create and drop their sites
- recovery command shows no leftover fresh sites after successful runs

- [ ] **Step 3: Commit final doc/workflow polish**

```bash
git add README.md .github/workflows/ci.yml .github/workflows/e2e.yml
git commit -m "Document ephemeral test site workflow"
```
