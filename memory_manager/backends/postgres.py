import psycopg2
from psycopg2.extras import Json, RealDictCursor
import json
from contextlib import contextmanager
from datetime import timedelta


class ConversationNotFoundError(Exception):
    """Raised when a conversation is not owned by the requested identity."""


class PostgresBackend:

    def __init__(self, config: dict):
        self._connection_params = {
            "host": config["POSTGRES_HOST"],
            "port": config["POSTGRES_PORT"],
            "dbname": config["POSTGRES_DB"],
            "user": config["POSTGRES_USER"],
            "password": config["POSTGRES_PASSWORD"],
        }
        self.conn = psycopg2.connect(**self._connection_params)
        self.conn.autocommit = True

    @contextmanager
    def _transaction_connection(self):
        """Use a request-scoped connection for atomic chat persistence."""
        conn = psycopg2.connect(**self._connection_params)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def create_project(self, name, slug, description=None, tags=None):
        cur = self.conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "INSERT INTO projects (name, slug, description, tags) VALUES (%s, %s, %s, %s) RETURNING *",
            (name, slug, description, tags or [])
        )
        r = dict(cur.fetchone())
        cur.close()
        return r

    def get_project(self, slug):
        cur = self.conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM projects WHERE slug = %s", (slug,))
        r = cur.fetchone()
        cur.close()
        return dict(r) if r else None

    def list_projects(self, status=None):
        cur = self.conn.cursor(cursor_factory=RealDictCursor)
        if status:
            cur.execute("SELECT * FROM projects WHERE status = %s ORDER BY last_activity DESC", (status,))
        else:
            cur.execute("SELECT * FROM projects ORDER BY last_activity DESC")
        return [dict(x) for x in cur.fetchall()]

    def insert_research(self, research):
        cur = self.conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """INSERT INTO research_entries
            (project_id, query_hash, query_text, summary, full_analysis, sources, tags,
             confidence_score_raw, confidence_score_calibrated, api_cost, tokens_input, tokens_output)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (
                research.get("project_id"),
                research["query_hash"],
                research["query_text"],
                research.get("summary"),
                json.dumps(research.get("full_analysis")) if research.get("full_analysis") else None,
                json.dumps(research.get("sources", [])),
                research.get("tags", []),
                research.get("confidence_score_raw"),
                research.get("confidence_score_calibrated"),
                research.get("api_cost", 0.0),
                research.get("tokens_input", 0),
                research.get("tokens_output", 0),
            )
        )
        rid = str(cur.fetchone()["id"])
        cur.close()
        return rid

    def get_research(self, research_id):
        cur = self.conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM research_entries WHERE id = %s", (research_id,))
        r = cur.fetchone()
        cur.close()
        return dict(r) if r else None

    def get_latest_by_hash(self, query_hash, project_id=None):
        cur = self.conn.cursor(cursor_factory=RealDictCursor)
        if project_id:
            cur.execute(
                "SELECT * FROM research_entries WHERE query_hash = %s AND project_id = %s AND is_latest = true",
                (query_hash, project_id)
            )
        else:
            cur.execute(
                "SELECT * FROM research_entries WHERE query_hash = %s AND is_latest = true",
                (query_hash,)
            )
        r = cur.fetchone()
        cur.close()
        return dict(r) if r else None

    def get_recent_by_project(self, project_id, limit=5):
        cur = self.conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT * FROM research_entries WHERE project_id = %s ORDER BY created_at DESC LIMIT %s",
            (project_id, limit)
        )
        return [dict(x) for x in cur.fetchall()]

    def get_calibration(self, domain, bucket, granularity="domain"):
        cur = self.conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """SELECT * FROM calibration_data
            WHERE calibration_domain = %s AND confidence_bucket = %s AND granularity_level = %s
            ORDER BY calibration_version DESC LIMIT 1""",
            (domain, bucket, granularity)
        )
        r = cur.fetchone()
        cur.close()
        return dict(r) if r else None

    def upsert_calibration(self, domain, bucket, is_success):
        cur = self.conn.cursor()
        cur.execute(
            """INSERT INTO calibration_data
            (calibration_domain, confidence_bucket, total_predictions, total_successes, actual_success_rate)
            VALUES (%s, %s, 1, %s, %s)
            ON CONFLICT (calibration_domain, granularity_level, confidence_bucket)
            DO UPDATE SET
                total_predictions = calibration_data.total_predictions + 1,
                total_successes = calibration_data.total_successes + %s,
                actual_success_rate = (calibration_data.total_successes + %s)::FLOAT / (calibration_data.total_predictions + 1)""",
            (domain, bucket, int(is_success), float(is_success), int(is_success), int(is_success))
        )
        cur.close()

    def cache_get(self, key):
        cur = self.conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT cache_value FROM cache_entries WHERE cache_key = %s AND expires_at > NOW()", (key,)
        )
        r = cur.fetchone()
        cur.close()
        return r["cache_value"] if r else None

    def cache_set(self, key, value, ttl_seconds=300):
        cur = self.conn.cursor()
        v = json.dumps(value)
        cur.execute(
            "INSERT INTO cache_entries (cache_key, cache_value, expires_at) VALUES (%s, %s, NOW() + make_interval(secs => %s)) "
            "ON CONFLICT (cache_key) DO UPDATE SET cache_value = %s, expires_at = NOW() + make_interval(secs => %s)",
            (key, v, ttl_seconds, v, ttl_seconds)
        )
        cur.close()

    def create_conversation(self, owner_user_id, title="New Chat", model=None):
        cur = self.conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """INSERT INTO conversations (owner_user_id, title, model)
                VALUES (%s, %s, %s) RETURNING *""",
                (owner_user_id, title or "New Chat", model),
            )
            return dict(cur.fetchone())
        finally:
            cur.close()

    def list_conversations(self, owner_user_id):
        cur = self.conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """SELECT * FROM conversations
                WHERE owner_user_id = %s
                ORDER BY updated_at DESC, id DESC""",
                (owner_user_id,),
            )
            return [dict(row) for row in cur.fetchall()]
        finally:
            cur.close()

    def get_conversation(self, owner_user_id, conversation_id):
        conversation_id = str(conversation_id)
        cur = self.conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """SELECT * FROM conversations
                WHERE id = %s AND owner_user_id = %s""",
                (conversation_id, owner_user_id),
            )
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            cur.close()

    def list_messages(self, owner_user_id, conversation_id):
        conversation_id = str(conversation_id)
        cur = self.conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """SELECT m.*
                FROM messages AS m
                JOIN conversations AS c ON c.id = m.conversation_id
                WHERE c.id = %s AND c.owner_user_id = %s
                ORDER BY m.created_at ASC, m.id ASC""",
                (conversation_id, owner_user_id),
            )
            return [dict(row) for row in cur.fetchall()]
        finally:
            cur.close()

    @staticmethod
    def _next_message_timestamp(cur, conversation_id):
        cur.execute(
            """SELECT GREATEST(
                CURRENT_TIMESTAMP::timestamp without time zone,
                COALESCE(
                    MAX(created_at) + INTERVAL '1 microsecond',
                    CURRENT_TIMESTAMP::timestamp without time zone
                )
            ) AS next_created_at
            FROM messages WHERE conversation_id = %s""",
            (str(conversation_id),),
        )
        return cur.fetchone()["next_created_at"]

    def create_message(self, conversation_id, role, content):
        conversation_id = str(conversation_id)
        with self._transaction_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                created_at = self._next_message_timestamp(cur, conversation_id)
                cur.execute(
                    """INSERT INTO messages (conversation_id, role, content, created_at)
                    VALUES (%s, %s, %s, %s) RETURNING *""",
                    (conversation_id, role, Json(content), created_at),
                )
                message = dict(cur.fetchone())
                cur.execute(
                    """UPDATE conversations SET updated_at = GREATEST(
                        CURRENT_TIMESTAMP::timestamp without time zone, %s
                    ) WHERE id = %s""",
                    (created_at, conversation_id),
                )
                if cur.rowcount != 1:
                    raise ConversationNotFoundError()
                return message

    def persist_chat_exchange(
        self,
        owner_user_id,
        conversation_id,
        title,
        model,
        user_content,
        assistant_content,
    ):
        """Atomically create/validate a conversation and persist one exchange."""
        if conversation_id is not None:
            conversation_id = str(conversation_id)
        with self._transaction_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if conversation_id is None:
                    cur.execute(
                        """INSERT INTO conversations (owner_user_id, title, model)
                        VALUES (%s, %s, %s) RETURNING *""",
                        (owner_user_id, title or "New Chat", model),
                    )
                    conversation = dict(cur.fetchone())
                    conversation_id = str(conversation["id"])
                else:
                    cur.execute(
                        """SELECT * FROM conversations
                        WHERE id = %s AND owner_user_id = %s
                        FOR UPDATE""",
                        (conversation_id, owner_user_id),
                    )
                    row = cur.fetchone()
                    if row is None:
                        raise ConversationNotFoundError()
                    conversation = dict(row)
                    if conversation["title"] == "New Chat":
                        cur.execute(
                            """SELECT EXISTS (
                                SELECT 1 FROM messages WHERE conversation_id = %s
                            ) AS has_messages""",
                            (conversation_id,),
                        )
                        if not cur.fetchone()["has_messages"]:
                            cur.execute(
                                """UPDATE conversations SET title = %s
                                WHERE id = %s AND owner_user_id = %s
                                RETURNING *""",
                                (title or "New Chat", conversation_id, owner_user_id),
                            )
                            conversation = dict(cur.fetchone())

                user_created_at = self._next_message_timestamp(cur, conversation_id)
                assistant_created_at = user_created_at + timedelta(microseconds=1)
                cur.execute(
                    """INSERT INTO messages (conversation_id, role, content, created_at)
                    VALUES (%s, %s, %s, %s)""",
                    (conversation_id, "user", Json(user_content), user_created_at),
                )
                cur.execute(
                    """INSERT INTO messages (conversation_id, role, content, created_at)
                    VALUES (%s, %s, %s, %s)""",
                    (conversation_id, "assistant", Json(assistant_content), assistant_created_at),
                )
                cur.execute(
                    """UPDATE conversations
                    SET model = %s, updated_at = GREATEST(
                        CURRENT_TIMESTAMP::timestamp without time zone, %s
                    )
                    WHERE id = %s AND owner_user_id = %s
                    RETURNING *""",
                    (model, assistant_created_at, conversation_id, owner_user_id),
                )
                updated = cur.fetchone()
                if updated is None:
                    raise ConversationNotFoundError()
                return dict(updated)

    def close(self):
        self.conn.close()
