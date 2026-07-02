"""Helpdesk: WhatsApp-fed Q&A knowledge base.

Public read API (search + browse) is open; write and ingest endpoints are
gated behind HTTP Basic using ADMIN_USER / ADMIN_PASSWORD.
"""
import os
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import text

from .db import FTS_CONFIG, engine, init_db
from .ingest import extract_qa, extract_qa_freeform, parse_export

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="Helpdesk", docs_url="/api/docs")

_origins = os.getenv("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    init_db()


# ---------------------------------------------------------------- auth
security = HTTPBasic()


def require_admin(creds: HTTPBasicCredentials = Depends(security)) -> str:
    user_ok = secrets.compare_digest(
        creds.username, os.getenv("ADMIN_USER", "admin")
    )
    pass_ok = secrets.compare_digest(
        creds.password, os.getenv("ADMIN_PASSWORD", "change-me")
    )
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciais inválidas",
            headers={"WWW-Authenticate": "Basic"},
        )
    return creds.username


# ---------------------------------------------------------------- schemas
class GroupIn(BaseModel):
    name: str
    slug: str | None = None
    parent_id: int | None = None


class QuestionIn(BaseModel):
    title: str
    body: str | None = None
    group_id: int | None = None
    author: str | None = None
    source_date: str | None = None
    status: str = "draft"


class AnswerIn(BaseModel):
    body: str
    author: str | None = None
    is_accepted: bool = False


class IngestIn(BaseModel):
    raw: str


class AskIn(BaseModel):
    title: str
    body: str | None = None
    author: str | None = None


def _slugify(value: str) -> str:
    import re

    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "grupo"


# ---------------------------------------------------------------- public read
@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/groups")
def list_groups():
    sql = text(
        """
        SELECT g.id, g.name, g.slug, g.parent_id,
               COUNT(q.id) FILTER (WHERE q.status = 'published') AS question_count
        FROM groups g
        LEFT JOIN questions q ON q.group_id = g.id
        GROUP BY g.id
        ORDER BY g.name
        """
    )
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(sql).mappings()]


@app.get("/api/groups/{slug}/questions")
def questions_in_group(slug: str):
    sql = text(
        """
        SELECT q.id, q.title, q.author, q.source_date
        FROM questions q JOIN groups g ON g.id = q.group_id
        WHERE g.slug = :slug AND q.status = 'published'
        ORDER BY q.created_at DESC
        """
    )
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(sql, {"slug": slug}).mappings()]


@app.get("/api/search")
def search(q: str, limit: int = 20):
    if not q.strip():
        return []
    sql = text(
        f"""
        SELECT q.id, q.title,
               ts_headline('{FTS_CONFIG}', coalesce(q.body, q.title),
                   plainto_tsquery('{FTS_CONFIG}', :q),
                   'MaxWords=30, MinWords=10, ShortWord=3') AS snippet,
               g.name AS group_name, g.slug AS group_slug,
               GREATEST(
                   ts_rank(q.search_tsv, plainto_tsquery('{FTS_CONFIG}', :q)),
                   similarity(immutable_unaccent(lower(q.title)), immutable_unaccent(lower(:q)))
               ) AS rank
        FROM questions q
        LEFT JOIN groups g ON g.id = q.group_id
        WHERE q.status = 'published'
          AND (
              q.search_tsv @@ plainto_tsquery('{FTS_CONFIG}', :q)
              OR similarity(immutable_unaccent(lower(q.title)), immutable_unaccent(lower(:q))) > 0.2
          )
        ORDER BY rank DESC
        LIMIT :limit
        """
    )
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(sql, {"q": q, "limit": limit}).mappings()]


@app.get("/api/questions/{qid}")
def get_question(qid: int):
    with engine.connect() as conn:
        q = conn.execute(
            text(
                """
                SELECT q.id, q.title, q.body, q.author, q.source_date, q.status,
                       g.name AS group_name, g.slug AS group_slug
                FROM questions q LEFT JOIN groups g ON g.id = q.group_id
                WHERE q.id = :id AND q.status = 'published'
                """
            ),
            {"id": qid},
        ).mappings().first()
        if not q:
            raise HTTPException(404, "Pergunta não encontrada")
        answers = conn.execute(
            text(
                """
                SELECT id, body, author, is_accepted, created_at
                FROM answers WHERE question_id = :id
                ORDER BY is_accepted DESC, created_at
                """
            ),
            {"id": qid},
        ).mappings()
        return {"question": dict(q), "answers": [dict(a) for a in answers]}


@app.post("/api/questions/ask")
def ask_question(a: AskIn):
    """Public: visitor didn't find an answer, submit it as a draft for
    coordinators to answer from the admin panel (feeds the knowledge base).
    """
    title = a.title.strip()[:300]
    if not title:
        raise HTTPException(400, "Pergunta obrigatória")
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO questions (title, body, author, status)
                VALUES (:title, :body, :author, 'draft')
                RETURNING id
                """
            ),
            {
                "title": title,
                "body": (a.body or "").strip()[:5000] or None,
                "author": (a.author or "").strip()[:200] or None,
            },
        ).scalar_one()
    return {"id": row}


# ---------------------------------------------------------------- admin write
@app.post("/api/admin/groups")
def create_group(g: GroupIn, _: str = Depends(require_admin)):
    slug = g.slug or _slugify(g.name)
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "INSERT INTO groups (name, slug, parent_id) "
                "VALUES (:name, :slug, :parent_id) RETURNING id"
            ),
            {"name": g.name, "slug": slug, "parent_id": g.parent_id},
        ).scalar_one()
    return {"id": row, "slug": slug}


@app.post("/api/admin/questions")
def create_question(q: QuestionIn, _: str = Depends(require_admin)):
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO questions (title, body, group_id, author, source_date, status)
                VALUES (:title, :body, :group_id, :author,
                        NULLIF(:source_date, '')::date, :status)
                RETURNING id
                """
            ),
            q.model_dump(),
        ).scalar_one()
    return {"id": row}


@app.patch("/api/admin/questions/{qid}")
def update_question(qid: int, q: QuestionIn, _: str = Depends(require_admin)):
    with engine.begin() as conn:
        res = conn.execute(
            text(
                """
                UPDATE questions SET title=:title, body=:body, group_id=:group_id,
                    author=:author, source_date=NULLIF(:source_date,'')::date,
                    status=:status
                WHERE id=:id
                """
            ),
            {**q.model_dump(), "id": qid},
        )
        if res.rowcount == 0:
            raise HTTPException(404, "Pergunta não encontrada")
    return {"id": qid}


@app.delete("/api/admin/questions/{qid}")
def delete_question(qid: int, _: str = Depends(require_admin)):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM questions WHERE id=:id"), {"id": qid})
    return {"deleted": qid}


@app.post("/api/admin/questions/{qid}/answers")
def add_answer(qid: int, a: AnswerIn, _: str = Depends(require_admin)):
    with engine.begin() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM questions WHERE id=:id"), {"id": qid}
        ).first()
        if not exists:
            raise HTTPException(404, "Pergunta não encontrada")
        row = conn.execute(
            text(
                "INSERT INTO answers (question_id, body, author, is_accepted) "
                "VALUES (:qid, :body, :author, :is_accepted) RETURNING id"
            ),
            {"qid": qid, **a.model_dump()},
        ).scalar_one()
    return {"id": row}


@app.get("/api/admin/questions")
def admin_list_questions(_: str = Depends(require_admin)):
    sql = text(
        """
        SELECT q.id, q.title, q.status, g.name AS group_name,
               COUNT(a.id) AS answer_count
        FROM questions q
        LEFT JOIN groups g ON g.id = q.group_id
        LEFT JOIN answers a ON a.question_id = q.id
        GROUP BY q.id, g.name
        ORDER BY q.created_at DESC
        """
    )
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(sql).mappings()]


@app.post("/api/admin/ingest")
def ingest(body: IngestIn, _: str = Depends(require_admin)):
    """Parse pasted text and return candidate Q&A pairs.

    Recognises WhatsApp exports (author/timestamp per line) and extracts
    Q&A from the conversation. Any other pasted text (FAQ docs, articles,
    notes) falls back to asking the model to extract/synthesize Q&A pairs
    directly from the raw text.

    Nothing is persisted here: the admin reviews the pairs and posts the
    accepted ones back through the normal question/answer endpoints.
    """
    if not body.raw.strip():
        raise HTTPException(400, "Cole algum texto")
    messages = parse_export(body.raw)
    if messages:
        return extract_qa(messages)
    return extract_qa_freeform(body.raw)


# ---------------------------------------------------------------- static
@app.get("/")
def root():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/admin")
def admin_page():
    return FileResponse(STATIC_DIR / "admin.html")


app.mount("/", StaticFiles(directory=STATIC_DIR), name="static")
