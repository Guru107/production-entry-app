# Domain Docs

Before exploring the codebase, read:

- `CONTEXT.md` at the repository root
- relevant ADRs under `docs/adr/`

If these files do not exist, proceed silently. Domain-modeling skills create them when terminology or decisions are resolved.

## Layout

This is a single-context repository:

```text
/
├── CONTEXT.md
├── docs/adr/
└── production_entry_app/
```

Use terminology defined in `CONTEXT.md`. Surface conflicts with existing ADRs rather than silently overriding them.
