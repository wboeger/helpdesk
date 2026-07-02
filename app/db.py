"""Database engine, schema bootstrap, and small query helpers.

Uses raw SQL (via SQLAlchemy Core) so we keep full control over the
Postgres full-text search column and triggers, which ORMs make awkward.
"""
import os

from sqlalchemy import create_engine, text

# Railway/Heroku sometimes hand out URLs starting with the legacy
# "postgres://" scheme; SQLAlchemy + psycopg 3 expect "postgresql+psycopg://".
_raw_url = os.getenv("DATABASE_URL", "postgresql://localhost:5432/helpdesk")
if _raw_url.startswith("postgres://"):
    _raw_url = _raw_url.replace("postgres://", "postgresql://", 1)
if _raw_url.startswith("postgresql://"):
    _raw_url = _raw_url.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(_raw_url, pool_pre_ping=True, future=True)

# Portuguese text-search configuration for stemming/stop-words.
FTS_CONFIG = "portuguese"

SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS groups (
    id        SERIAL PRIMARY KEY,
    name      TEXT NOT NULL,
    slug      TEXT UNIQUE NOT NULL,
    parent_id INTEGER REFERENCES groups(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS questions (
    id          SERIAL PRIMARY KEY,
    group_id    INTEGER REFERENCES groups(id) ON DELETE SET NULL,
    title       TEXT NOT NULL,
    body        TEXT,
    author      TEXT,
    source_date DATE,
    status      TEXT NOT NULL DEFAULT 'draft',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    search_tsv  TSVECTOR
);

CREATE TABLE IF NOT EXISTS answers (
    id          SERIAL PRIMARY KEY,
    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    body        TEXT NOT NULL,
    author      TEXT,
    is_accepted BOOLEAN NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS questions_tsv_idx ON questions USING GIN(search_tsv);
CREATE INDEX IF NOT EXISTS questions_group_idx ON questions(group_id);
CREATE INDEX IF NOT EXISTS answers_question_idx ON answers(question_id);

-- Rebuild the search vector from title+body (weight A) plus all answer
-- bodies (weight B). Called by triggers on both tables.
CREATE OR REPLACE FUNCTION questions_refresh_tsv(q_id INTEGER) RETURNS void AS $$
BEGIN
    UPDATE questions q SET search_tsv =
        setweight(to_tsvector('{FTS_CONFIG}', coalesce(q.title, '')), 'A') ||
        setweight(to_tsvector('{FTS_CONFIG}', coalesce(q.body, '')), 'B') ||
        setweight(to_tsvector('{FTS_CONFIG}', coalesce(
            (SELECT string_agg(a.body, ' ') FROM answers a WHERE a.question_id = q.id),
        '')), 'B')
    WHERE q.id = q_id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION questions_tsv_trigger() RETURNS trigger AS $$
BEGIN
    PERFORM questions_refresh_tsv(NEW.id);
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION answers_tsv_trigger() RETURNS trigger AS $$
BEGIN
    PERFORM questions_refresh_tsv(COALESCE(NEW.question_id, OLD.question_id));
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS questions_tsv_upd ON questions;
CREATE TRIGGER questions_tsv_upd
    AFTER INSERT OR UPDATE OF title, body ON questions
    FOR EACH ROW EXECUTE FUNCTION questions_tsv_trigger();

DROP TRIGGER IF EXISTS answers_tsv_upd ON answers;
CREATE TRIGGER answers_tsv_upd
    AFTER INSERT OR UPDATE OR DELETE ON answers
    FOR EACH ROW EXECUTE FUNCTION answers_tsv_trigger();
"""


def init_db() -> None:
    """Create tables/triggers if missing. Safe to run on every startup."""
    with engine.begin() as conn:
        for statement in _split_sql(SCHEMA_SQL):
            conn.execute(text(statement))


def _split_sql(sql: str) -> list[str]:
    """Split a script into statements, keeping $$-quoted function bodies intact."""
    statements, buf, in_dollar = [], [], False
    for line in sql.splitlines():
        if line.count("$$") % 2 == 1:
            in_dollar = not in_dollar
        buf.append(line)
        if not in_dollar and line.rstrip().endswith(";"):
            chunk = "\n".join(buf).strip()
            if chunk:
                statements.append(chunk)
            buf = []
    tail = "\n".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements
