# Lovable + File2Base integration notes

## What was integrated

- Ported the supplied Lovable File2Base concept presentation into `templates/index.html` and `static/css/landing.css` / `static/js/landing.js`.
- Kept the deployment as one Flask application. The project does not require Node.js or a separate frontend host.
- Reused the working Flask upload and sample-data form endpoints (`/upload` and `/demo`) inside the new design.
- Kept the existing workflow routes and processing modules unchanged: `/review/<workspace_id>`, `/preflight/<workspace_id>`, `/create/<workspace_id>`, `/database/<workspace_id>`, table browsing, SQLite downloads, report downloads and workspace deletion.
- Updated shared workflow styles in `static/css/style.css` so the review and migration screens fit the same paper/navy design.
- Restored the original landing-page motion: a full-screen geometric intro, staggered SVG block-letter construction, click/keyboard skip, an animated hero wordmark, a small desktop pointer-follow cursor, in-view heading/card reveals, and scroll-driven movement of oversized section labels.
- Honored `prefers-reduced-motion`: the intro/cursor are disabled and content remains visible without motion for visitors who request reduced animation.

## Important implementation detail

The Lovable repository is a React/TanStack Start concept/presentation, while the working File2Base prototype is Flask/Jinja. The visual design and interactions were adapted into the existing Flask template system instead of mounting a second web application. This avoids changing backend routes or introducing a second deployment target. The interactive schema diagram is a concept illustration; it is not presented as the uploaded data's actual schema. Actual results remain on the live review pages generated from the backend.

## Local run (Windows PowerShell)

From the folder containing `app.py`:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Open `http://127.0.0.1:5000`. Choose **Try prototype** / **Try the working prototype**, then upload CSV/XLSX files or use the sample workspace.

## Validation notes

The engine test suite was run in the build environment. The engine tests passed. Flask route smoke tests are included in `tests/test_web.py` but could not run in the build sandbox because Flask is not installed there and package installation was unavailable. They should run after the standard `pip install -r requirements.txt` step.
