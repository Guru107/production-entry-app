---
name: release
description: Release checklist for production_entry_app (changelog, version bump in all carriers, PR, tag, GitHub release). Use when cutting or publishing a new version.
---

# Release Process

Follow this checklist exactly — `develop` is branch-protected, so nothing lands directly.

1. **Changelog first.** In `CHANGELOG.md` move `[Unreleased]` entries into a new
   `## [X.Y.Z] - YYYY-MM-DD` section (Keep a Changelog: Added/Changed/Fixed).
2. **Bump ALL version carriers** in the same change — historically `__init__.py` alone was bumped
   and v1.3.0 shipped showing 1.2.0 on sites:
   - `production_entry_app/__init__.py` (`__version__` — canonical; `pyproject.toml` dynamic version reads it)
   - `setup.py`
   - `package.json`
3. **Open a PR to `develop`** (release commit style: `chore: release vX.Y.Z`). Wait for all
   required checks: Linters, CI Server v15/v16, E2E v15/v16. Merge when green.
4. **Tag the merged develop:** `git switch develop && git pull && git tag vX.Y.Z && git push origin vX.Y.Z`.
5. **Publish:** `gh release create vX.Y.Z --title vX.Y.Z --notes "<mirror the changelog section>
   **Full changes:** https://github.com/Guru107/production-entry-app/compare/v<prev>...vX.Y.Z"`.
   Do not pass `--target` — it 422s when the tag already exists.
