# File2Base v2 implementation plan

## Release goal

Make the MVP simpler for non-technical users, improve explainability, reduce migration risk, and prepare it for a temporary evaluator-facing web deployment. Do not add an LLM until the deterministic workflow is stable.

## Implemented in v2

### A. Guided user experience
- Three explicit stages: upload/analyze, review schema, safety check/create.
- Plain-language labels and a public-demo data warning.
- Editable table names and a primary-key selector with a generated-ID fallback.
- Quick controls to select only constraint-safe relationships or clear all relationship suggestions.
- A final page to browse the generated database and download both SQLite and migration report files.

### B. Explainable intelligence
- Retain deterministic profiling and relationship scoring based on field-name similarity, type compatibility and value overlap.
- Use confidence scores as heuristic rankings, not probabilities.
- Mark links as database constraints only when the source-value coverage is complete and the selected target key is still the intended key.
- Do not auto-delete duplicate rows; report them to the user instead.

### C. Migration safety
- Add a non-destructive preflight that checks selected identifiers, duplicate rows, numeric type concerns and unmatched relationship values.
- Compare uploaded source files against their SHA-256 fingerprints before preview and again before creation.
- Ask the user to explicitly confirm migration after reviewing warnings.
- Build a replacement database in a temporary SQLite file, check referential integrity, then use atomic file replacement on success.
- Preserve the previous successful database if table creation, row insertion or integrity checks fail.
- Add workspace deletion, automatic expiry cleanup, a 20 MB upload request limit and a maximum of eight files.

### D. Web hosting preparation
- Add Render Blueprint, Procfile, Python version pin and Gunicorn dependency for Linux deployment.
- Add a health endpoint and set the web server to bind to the hosting provider's port.
- Add CSRF validation for POST forms, secure session-cookie settings on Render, and common security response headers.
- Document that this is a public demo without authentication and must only receive synthetic/non-sensitive data.

## Verification performed for this release

- Core analysis and migration unit tests pass.
- Migration preflight tests pass on the included six-file retailer sample.
- Failed replacement migration test confirms the previous successful SQLite database remains available.
- A separate Maple & Loom six-CSV dataset was analyzed and migrated: 6 tables, 68 rows and zero foreign-key violations.
- Python files compile, Jinja templates parse, JavaScript syntax checks pass, and `render.yaml` parses.

Flask route tests are included in `tests/test_web.py`. They could not be executed in the build environment because Flask is not installed there and external package downloads are unavailable in that environment. They run after installing `requirements.txt`.

## Next milestones (not implemented yet)

1. Add user-editable column names and data types with preview diffs.
2. Add migration report in CSV/PDF format plus downloadable rejected-records report.
3. Add database search, row filtering and CSV export from the browser.
4. Add test-data fixtures for ambiguous IDs, missing keys, duplicate primary keys, and conflicting types.
5. Add authentication and per-workspace authorization before accepting anything beyond demo data.
6. Add persistent storage / PostgreSQL, backups, deletion/audit controls and rate limiting for a production service.
7. Add an optional LLM semantic suggestion layer with JSON-schema validation and a strict no-auto-execute rule; only start this after deterministic tests and acceptance criteria are stable.
