"""Conversation and feedback log in postgres: elasticsearch stores the
knowledge, this module stores the history."""

import os
import sys

import psycopg


class ConversationLog:
    """The diary over postgres: every answered question is one row in
    conversations, every thumbs up or down one row in feedback, and
    grafana reads both to draw the dashboards.

    Same shape as the rest of the package: dependencies arrive at
    birth, nothing in here reads the environment. Each method opens
    one short-lived connection, so no connection object lingers
    between streamlit reruns."""

    def __init__(self, host, user, password, dbname):
        self.host = host
        self.user = user
        self.password = password
        self.dbname = dbname

    def _connect(self):
        """One connection per operation, used as a context manager so
        commit and close are automatic."""
        return psycopg.connect(host=self.host, user=self.user,
                               password=self.password, dbname=self.dbname)

    def create_tables(self, recreate=False):
        """IF NOT EXISTS keeps this safe to run on every startup: a
        fresh clone gets the schema, an existing database is left
        untouched.

        recreate=True is the explicit reset, same pattern as the
        elasticsearch indexer: drops both tables (feedback first, it
        references conversations) and rebuilds them. It erases the
        whole conversation history, so it only runs when asked by
        name (make reset-db)."""
        with self._connect() as conn:
            if recreate:
                conn.execute("DROP TABLE IF EXISTS feedback;")
                conn.execute("DROP TABLE IF EXISTS conversations;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id                SERIAL PRIMARY KEY,
                    question          TEXT NOT NULL,
                    answer            TEXT NOT NULL,
                    model             TEXT NOT NULL,
                    prompt_tokens     INTEGER,
                    completion_tokens INTEGER,
                    cost              NUMERIC(10, 6),
                    response_time     REAL,
                    source            TEXT NOT NULL DEFAULT 'streamlit',
                    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS feedback (
                    id              SERIAL PRIMARY KEY,
                    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
                    thumbs          INTEGER NOT NULL,
                    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
                );
            """)

    def save_conversation(self, question, answer, model, prompt_tokens,
                          completion_tokens, cost, response_time,
                          source="streamlit"):
        """One answered question becomes one row. Returns the generated
        id, which is what feedback and judge verdicts point at later."""
        with self._connect() as conn:
            row = conn.execute(
                """
                INSERT INTO conversations
                    (question, answer, model, prompt_tokens,
                     completion_tokens, cost, response_time, source)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (question, answer, model, prompt_tokens,
                 completion_tokens, cost, response_time, source),
            ).fetchone()
        return row[0]

    def save_feedback(self, conversation_id, thumbs):
        """A thumbs up (1) or down (-1) pointing at its conversation."""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO feedback (conversation_id, thumbs) VALUES (%s, %s)",
                (conversation_id, thumbs),
            )


if __name__ == "__main__":
    log = ConversationLog(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        user=os.getenv("POSTGRES_USER", "user"),
        password=os.getenv("POSTGRES_PASSWORD", "pswd"),
        dbname=os.getenv("APP_POSTGRES_DB", "obsidian_assistant"),
    )
    recreate = "--recreate" in sys.argv
    log.create_tables(recreate=recreate)
    print("tables recreated" if recreate else "tables ready")
