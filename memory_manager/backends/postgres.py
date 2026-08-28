import psycopg2
from psycopg2.extras import RealDictCursor
import json


class PostgresBackend:

    def __init__(self, config: dict):
        self.conn = psycopg2.connect(
            host=config["POSTGRES_HOST"],
            port=config["POSTGRES_PORT"],
            dbname=config["POSTGRES_DB"],
            user=config["POSTGRES_USER"],
            password=config["POSTGRES_PASSWORD"]
        )
        self.conn.autocommit = True

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

    def close(self):
        self.conn.close()
