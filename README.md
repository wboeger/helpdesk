# Helpdesk

Q&A knowledge base fed from a WhatsApp group. Discussions that get lost in the
chat get curated into searchable, browsable questions & answers, and the whole
thing embeds into an existing website with two lines of HTML.

- **Ingest:** paste a WhatsApp chat export → AI extracts candidate Q&A pairs → admin reviews & publishes.
- **Roles:** admins write (HTTP Basic); everyone reads.
- **Search:** Postgres full-text (`portuguese` config), keyword + snippet highlighting.
- **Embed:** a `<script>` widget rendered in Shadow DOM (CSS-isolated).
- **Host:** Railway (app + managed Postgres).

## Stack

FastAPI + Postgres. Vanilla-JS widget, no build step.

```
app/
  main.py     FastAPI app: public read API + admin write/ingest + static serving
  db.py       engine, schema bootstrap, portuguese full-text index + triggers
  ingest.py   WhatsApp export parser + Claude-based Q&A extraction
static/
  widget.js   embeddable widget (Shadow DOM)
  index.html  standalone demo page
  admin.html  admin panel (ingest + CRUD)
```

## Embed on your homepage

**Option A — `<iframe>` (recommended if your site is built with a framework/CMS
that re-renders the page, e.g. React, Vue, WordPress page builders).** This
fully isolates the widget from your page's own DOM updates, which otherwise
can wipe out the widget's mount point mid-interaction (search box losing
focus/state):

```html
<iframe src="https://YOUR-APP.up.railway.app/" style="width:100%;min-height:600px;border:0"></iframe>
```

**Option B — inline script.** Add these two lines anywhere in your existing
HTML page:

```html
<div id="helpdesk"></div>
<script src="https://YOUR-APP.up.railway.app/widget.js" data-title="Central de Dúvidas"></script>
```

Optional `data-target="#some-id"` to mount elsewhere. Deep links use the URL
hash (`#helpdesk/q/123`), so individual answers are shareable back into WhatsApp.
Avoid this option if your page framework re-renders the container div — it
will tear down the widget's internal state.

## Deploy on Railway

1. Push this repo to GitHub.
2. Railway → New Project → Deploy from GitHub repo.
3. Add the **Postgres** plugin — it injects `DATABASE_URL` automatically.
4. Set variables:
   - `ADMIN_USER`, `ADMIN_PASSWORD` — admin login
   - `ANTHROPIC_API_KEY` — *(optional)* enables AI extraction on ingest
   - `ALLOWED_ORIGINS` — *(optional)* your homepage origin(s), comma-separated (default `*`)
5. Railway builds via Nixpacks and starts `uvicorn app.main:app` (see `railway.json`).

Tables and the full-text index are created automatically on first startup.

## Local dev

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # edit DATABASE_URL, ADMIN_PASSWORD
export $(grep -v '^#' .env | xargs)
uvicorn app.main:app --reload
```

- Widget/demo: http://localhost:8000/
- Admin: http://localhost:8000/admin
- API docs: http://localhost:8000/api/docs

## API

Public: `GET /api/groups`, `GET /api/groups/{slug}/questions`,
`GET /api/search?q=`, `GET /api/questions/{id}`.

Admin (HTTP Basic): `POST /api/admin/groups`, `POST/PATCH/DELETE /api/admin/questions`,
`POST /api/admin/questions/{id}/answers`, `GET /api/admin/questions`,
`POST /api/admin/ingest`.

## Roadmap

- Phase 4: semantic search (pgvector + embeddings), analytics on searched-but-empty
  queries to surface knowledge gaps, group tree UI.
