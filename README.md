### Production Entry App

An erpnext module to simplify production entries

## Supported versions

Tested against Frappe/ERPNext **v15.110+** and **v16.20 / 16.21+**.
ERPNext is a required dependency (`required_apps = ["erpnext"]`).

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app production_entry_app
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/production_entry_app
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

## Admin notes

The app is always role-gated through native Frappe Roles, DocPerms, and User
Permissions. Assign `PEA User` for write access and `PEA Read Only` for
read-only access. `System Manager` keeps full access through native
permissions. There is no open or disabled access-control mode, and the app
never auto-grants roles. Branch isolation depends on native Branch User
Permissions and assumes System Settings `apply_strict_user_permissions`
stays OFF; if it is enabled, empty-branch Stock Entries can remain visible to
branch-restricted users.

### CI

This app can use GitHub Actions for CI. The following workflows are configured:

- CI: Installs this app and runs unit tests on every push to `develop` branch.
- Linters: Runs [Frappe Semgrep Rules](https://github.com/frappe/semgrep-rules) and [pip-audit](https://pypi.org/project/pip-audit/) on every pull request.
- E2E Playwright: Runs browser-based end-to-end smoke tests on PRs and full regression on nightly schedule.

Authoritative CI runs now create disposable Frappe sites and drop them after the suite finishes.
Persistent local sites remain useful for debugging, but they are not the cleanup boundary anymore.

### Authoritative Ephemeral Runs

Run from `apps/production_entry_app` with a bench available at `BENCH_ROOT` and a MariaDB root password
available in `DB_ROOT_PASSWORD`:

```bash
BENCH_ROOT=/path/to/frappe-bench DB_ROOT_PASSWORD=... bash scripts/run_ephemeral_python_tests.sh
BENCH_ROOT=/path/to/frappe-bench DB_ROOT_PASSWORD=... bash scripts/run_ephemeral_e2e.sh smoke
BENCH_ROOT=/path/to/frappe-bench DB_ROOT_PASSWORD=... bash scripts/run_ephemeral_e2e.sh ci
```

These commands create a fresh site, run the target suite, then drop that site in teardown.

To inspect leftover disposable sites after an interrupted run:

```bash
/path/to/frappe-bench/env/bin/python scripts/cleanup_stale_ephemeral_sites.py
```

### E2E (Playwright)

Run from `apps/production_entry_app`:

```bash
npm install
npx playwright install chromium
npm run test:e2e
npm run test:e2e:regression
npm run test:e2e:ci
```

Branch isolation suite:

```bash
npx playwright test tests/e2e/specs/branch-isolation.spec.js
```

Notes:

- `npm run test:e2e` runs only `@smoke`.
- `npm run test:e2e:regression` runs only `@regression` (includes Phase 7 permission tests).
- `npm run test:e2e:ci` runs all E2E tests.
- `tests/e2e/global-teardown.js` remains best-effort cleanup for persistent local sites; authoritative
  ephemeral runs do not depend on it.

Environment variables (defaults shown) are in `tests/e2e/.env.example`:

- `PLAYWRIGHT_BASE_URL=http://localhost:8002`
- `PLAYWRIGHT_USERNAME=Administrator`
- `PLAYWRIGHT_PASSWORD=123`


### License

mit
