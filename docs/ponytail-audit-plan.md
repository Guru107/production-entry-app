# Ponytail Audit Plan

delete: archived agent plans and specs under `docs/superpowers`. Keep accepted product decisions in `CLAUDE.md`, README, or one short ADR per live rule. Trade-off: local narrative history moves back to git history, but current docs become searchable and maintainable. [docs/superpowers]

delete: in-app benchmark harnesses that are not runtime or CI paths. Keep measured results in `PERFORMANCE_NOTES.md`; re-add a one-off benchmark only when a current performance question needs it. Trade-off: less always-available benchmark code, but fewer app-package modules and tests to maintain. [production_entry_app/production_entry_app/report/report_benchmark.py, production_entry_app/production_entry_app/write_benchmark.py, production_entry_app/production_entry_app/report/test_report_benchmark.py, production_entry_app/production_entry_app/test_write_benchmark.py]

deferred: E2E-only setup and cleanup helpers exposed from production `api.py` were left in place. The guarded helpers (`Administrator` + `developer_mode` + `allow_e2e_tests`) are still called directly by the Playwright specs, so shrinking the API surface now would break E2E without an equivalent replacement. Revisit once the Playwright bootstrap/cleanup contract is reworked. [production_entry_app/production_entry_app/api.py, production_entry_app/production_entry_app/test_api.py, tests/e2e]

delete: unused `Production Entry Access Rule` DocType stub. Current access control is role/settings based; remove the DocType and its import assertion if no migration references remain. Trade-off: less room for a future rule-table design, but no dead schema in installed sites. [production_entry_app/production_entry_app/doctype/production_entry_access_rule]

delete: test aggregator modules that only re-export real tests. Run or discover the actual test modules directly. Trade-off: older manual `bench run-tests --module` shortcuts may need updating, but discovery becomes explicit. [production_entry_app/production_entry_app/test_reports.py, production_entry_app/production_entry_app/test_doctypes.py, production_entry_app/production_entry_app/test_utils.py]

shrink: recursive `pre-commit-all-files` hook. Use CI and explicit `pre-commit run --all-files` before handoff instead of making every local commit recurse through the entire hook suite. Trade-off: developers must remember the full run at handoff, but ordinary commits stop paying full-repo cost. [.pre-commit-config.yaml]

shrink: repeated report JavaScript date-filter boilerplate. Keep per-report files, but move shared date-range handling into `report_filter_utils.js`. Trade-off: one helper becomes a shared dependency, but report files lose copy-paste validation logic. [production_entry_app/production_entry_app/report/*/*.js]

net: -11300 lines, -0 deps possible.
