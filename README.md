# File2Base v2 — Lovable Design + Functional Flask Prototype

**Tagline:** Turn business files into a database you can understand and review.

## Lovable design integration

This build integrates the visual direction and section flow from [the supplied Lovable/GitHub design](https://github.com/akshatambasta-dev/pixel-perfect-replica) into the existing Flask application. The presentation page has been ported into the Flask/Jinja template system so the deployment remains one application and does not require a separate Node server. The landing page includes the concept sections, responsive navigation, scroll progress, the geometric intro splash and animated block-letter wordmark, section-reveal and scroll-parallax effects, a subtle desktop pointer-follow cursor, process-step interaction, an interactive schema illustration, feature accordion, market/customer sections, MVP and roadmap sections, plus the actual upload and sample-data forms.

The two forms still submit to the existing Flask `/upload` and `/demo` routes. The rest of the workflow—schema review, migration safety checks, SQLite creation, table browsing and downloads—continues to use the existing backend and routes. Workflow screens have also been restyled to use the same restrained paper/navy/mono visual language. The schema illustration is explicitly illustrative; only the real analysis/review pages display data from an uploaded workspace.

File2Base is a concept-stage prototype that helps a spreadsheet-heavy business move from separate `.csv` and `.xlsx` files to a structured SQLite database. This release prioritizes a simple guided workflow, explainable rule-based suggestions and an explicit migration safety check. LLM integration is intentionally postponed until the rule-based engine is stable.

> **Public evaluator demo warning:** This prototype is not a production data service. When hosted publicly, only use fictional or non-sensitive files. Do not upload confidential customer, payment, medical, employee or other regulated data. A UUID workspace link acts as the link to that workspace; there is no account system. Workspaces are set to expire after about 6 hours and may disappear earlier during a restart or redeploy. The current deployment configuration does not use a persistent disk.

## What changed in v2

- **Guided flow:** Upload → Review schema → Migration safety check → Database.
- **Human choice of identifiers:** Review a detected key candidate or choose a generated row ID for a table.
- **Migration preflight:** Counts rows, checks candidate-key uniqueness/completeness, reports duplicate rows and numeric type concerns, and checks unmatched values before a database is written.
- **Safer relationship enforcement:** A relationship is created as an actual SQLite foreign-key constraint only when the full source value set is covered and the selected target key matches. Other accepted links are stored as recommendations.
- **Atomic database replacement:** A migration is built in a temporary file; the previous successful database is not removed unless the new database builds and passes its foreign-key check.
- **Source fingerprint checks:** SHA-256 checks detect files that are missing or have changed since upload before migration.
- **Data quality transparency:** Exact duplicate rows are flagged, not silently deleted. Type warnings are surfaced during preflight.
- **Exportable migration report:** Download a JSON summary of table counts, accepted relationships, and warnings.
- **Deletion and retention:** A workspace can be manually deleted, and stale workspace folders are cleaned periodically after their configured TTL.
- **Basic web form security:** POST forms use a CSRF token; session cookies and common response security headers are configured. The app still has no authentication or per-user account system.
- **Web hosting setup:** `render.yaml`, `Procfile`, production Gunicorn start command, environment secret generation and `/health` endpoint are included.
- **No NumPy or pandas:** CSV uses Python's built-in `csv` module; Excel uses `openpyxl`, avoiding the NumPy DLL issue encountered on some Windows machines.

## Feature scope

### Available in this prototype

- Multiple `.csv` and `.xlsx` uploads (up to 8 files, 20 MB total HTTP request, and 100,000 rows per file).
- Six-file fictional furniture-retailer workspace.
- Row/column profiling, inferred types, null percentages, uniqueness and exact duplicate counts.
- Primary-key candidates plus option to use a generated row ID.
- Relationship suggestions ranked by field-name similarity, type compatibility and value overlap.
- Editable table names and relationship acceptance/rejection.
- Preflight checks without creating a database.
- SQLite schema creation, data copy, foreign-key validation and table browser.
- SQLite database and migration-report downloads.
- CSRF validation, source-file hash verification, workspace delete and time-to-live cleanup.

### Not included yet

- LLM or trained ML integration.
- PDF/OCR ingestion, cloud database targets, Google Sheets/ERP/CRM connectors, authentication, per-user authorization, persistent storage, background jobs, advanced rollback history, or production security certification.
- Automated deletion or fuzzy merging of duplicate customer/product records.
- User-edited column data types. The current UI lets users choose the primary key or generated identifier and rename tables; other type suggestions are still generated by rules.

Relationship percentages are **heuristic scores, not calibrated probabilities**. Always review schema suggestions; test on synthetic data first.

## Run locally on Windows PowerShell

1. Extract this ZIP.
2. Open PowerShell in the extracted `file2base_mvp` folder.
3. Create an isolated Python environment:

   ```powershell
   py -m venv .venv
   ```

4. Install dependencies:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install --upgrade pip
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

5. Start the app:

   ```powershell
   .\.venv\Scripts\python.exe app.py
   ```

6. Open `http://127.0.0.1:5000`, then click **Load sample workspace**.

You can also double-click `run_windows.bat`. Keep PowerShell open while using the website. For systems where PowerShell execution policy blocks virtual-environment activation, the direct Python executable commands above avoid activation.

## Run engine tests

After installing `requirements.txt`, run:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The current test suite covers sample analysis, relationship review, preflight checks, database migration, and preserving an existing successful database after a failed replacement attempt.

## Deploy an evaluator demo to Render

The repository includes a `render.yaml` Blueprint with a Gunicorn start command, health check, generated secret key, Python version and six-hour workspace retention setting. Render's official Flask deployment instructions use a Python web service and Gunicorn; Render web services need to bind through the port it supplies, which this configuration handles. See [Render's Flask deployment guide](https://render.com/docs/deploy-flask) and [web service configuration](https://render.com/docs/web-services).

1. Extract this project folder.
2. Create a GitHub repository for the source, then commit and push the **contents of `file2base_mvp`** (the folder containing `app.py`, `requirements.txt` and `render.yaml`). Do not commit `.venv`, uploads, workspaces or generated `.sqlite` databases.
3. In Render, choose **New → Blueprint** and connect the repository. Render reads `render.yaml`; review the proposed `file2base-evaluator-demo` web service before creating it. The Blueprint selects Render’s Singapore region for a demo serving users in India.
4. Confirm `FILE2BASE_SECRET_KEY` is generated and present under environment variables. The app refuses to start on Render if this secret is missing.
5. Wait for deployment and open the Render URL. Check `/health` returns JSON with `status: ok`.
6. Test with the included sample workspace, then try the fictional CSV ZIP provided separately. Do not use confidential data.

### Hosted-demo limitations

- This is a public demo with no user accounts. Workspace IDs are unguessable UUID links, but anyone with the link can access that workspace. Do not treat UUIDs as a replacement for authentication.
- The default Render free web-service filesystem is ephemeral unless a persistent disk is configured. This setup intentionally uses no disk: all uploaded and generated files can disappear at restart/redeploy, and old workspaces are cleaned after the configured TTL. This is appropriate for an evaluator demo, not business use. Free web services can also spin down after 15 minutes of inactivity; the first visit after idle time may be slower.
- There is no distributed rate limiter, antivirus scan, access-controlled private hosting, or multi-tenant security boundary. Do not expose it as a production migration service.
- If the app is later used with real business data, implement user accounts and authorization, strict per-tenant isolation, persistent encrypted storage, malware scanning, rate limiting, audit trails, backup/recovery and a reviewed retention policy before accepting that data.

## Test with the Maple & Loom fictional data

Select all six CSV files together:

- `customers.csv`
- `products.csv`
- `orders.csv`
- `order_items.csv`
- `suppliers.csv`
- `inventory.csv`

Expected workflow: upload → analyze → review table names and key selections → choose relationship links → review migration safety → confirm creation → browse tables → download `.sqlite` and the migration report.

The built-in sample workspace includes Excel and CSV examples. The Maple & Loom set is included under `test_data/Maple_and_Loom/`; upload all six CSV files together to test another fictional business.

## Project structure

```text
file2base_mvp/
├── app.py                     # Flask app, CSRF, workspaces, routes, upload limits
├── engine/
│   ├── analyzer.py            # CSV/XLSX parsing, profiling and relation inference
│   ├── preflight.py           # Non-destructive migration safety checks
│   └── database_builder.py    # Atomic SQLite build, integrity checks and browsing
├── templates/                 # Lovable-inspired landing + review, preflight, DB and error views
├── static/                    # Theme, landing/workflow styling and interactions
├── sample_data/               # Fictional retailer data
├── tests/                     # Engine, preflight and atomic replacement tests
├── requirements.txt
├── Procfile
├── render.yaml
└── .python-version
```

File2Base prototype — v2.2 • October 2026
