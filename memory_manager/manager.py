from memory_manager.backends.postgres import PostgresBackend
from memory_manager.backends.qdrant import QdrantBackend
import hashlib
import json


class MemoryManager:
    """Abstraction layer untuk semua operasi data."""

    def __init__(self, config: dict):
        self.pg = PostgresBackend(config)
        self.qdrant = QdrantBackend(config)

    # ==========================================
    # PROJECTS
    # ==========================================

    def create_project(self, name: str, slug: str, description: str = None, tags: list = None) -> dict:
        return self.pg.create_project(name, slug, description, tags)

    def get_project(self, slug: str) -> dict:
        return self.pg.get_project(slug)

    def list_projects(self, status: str = None) -> list:
        return self.pg.list_projects(status)

    # ==========================================
    # RESEARCH
    # ==========================================

    def save_research(self, research: dict) -> str:
        research["query_hash"] = hashlib.sha256(research["query_text"].encode()).hexdigest()
        return self.pg.insert_research(research)

    def get_research(self, research_id: str) -> dict:
        return self.pg.get_research(research_id)

    def get_latest_by_hash(self, query_hash: str, project_id: str = None) -> dict:
        return self.pg.get_latest_by_hash(query_hash, project_id)

    def get_recent_by_project(self, project_id: str, limit: int = 5) -> list:
        return self.pg.get_recent_by_project(project_id, limit)

    # ==========================================
    # VECTOR SEARCH
    # ==========================================

    def semantic_search(self, vector: list, project_id: str = None, limit: int = 5) -> list:
        return self.qdrant.search(vector, project_id, limit)

    def upsert_embedding(self, research_id: str, vector: list, payload: dict):
        self.qdrant.upsert(research_id, vector, payload)

    # ==========================================
    # CALIBRATION
    # ==========================================

    def get_calibration(self, domain: str, bucket: str) -> dict:
        return self.pg.get_calibration(domain, bucket)

    def record_prediction_outcome(self, domain: str, bucket: str, is_success: bool):
        self.pg.upsert_calibration(domain, bucket, is_success)

    # ==========================================
    # CACHE
    # ==========================================

    def cache_get(self, key: str) -> dict:
        return self.pg.cache_get(key)

    def cache_set(self, key: str, value: dict, ttl: int = 300):
        self.pg.cache_set(key, value, ttl)

    # ==========================================
    # CLEANUP
    # ==========================================

    def close(self):
        self.pg.close()
