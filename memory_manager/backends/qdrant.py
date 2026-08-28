from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue
import uuid


class QdrantBackend:

    COLLECTION_NAME = "research_embeddings"
    VECTOR_DIM = 1536

    def __init__(self, config: dict):
        self.client = QdrantClient(
            host=config["QDRANT_HOST"],
            port=int(config["QDRANT_PORT"])
        )
        self._ensure_collection()

    def _ensure_collection(self):
        names = [c.name for c in self.client.get_collections().collections]
        if self.COLLECTION_NAME not in names:
            self.client.create_collection(
                collection_name=self.COLLECTION_NAME,
                vectors_config=VectorParams(size=self.VECTOR_DIM, distance=Distance.COSINE)
            )

    def _to_id(self, point_id: str):
        try:
            return str(uuid.UUID(point_id))
        except ValueError:
            return str(hash(point_id) % (2**63))

    def upsert(self, point_id: str, vector: list, payload: dict):
        self.client.upsert(
            collection_name=self.COLLECTION_NAME,
            points=[PointStruct(id=self._to_id(point_id), vector=vector, payload=payload)]
        )

    def search(self, vector: list, filter_project_id: str = None, limit: int = 10) -> list:
        qf = None
        if filter_project_id:
            qf = Filter(must=[FieldCondition(key="project_id", match=MatchValue(value=filter_project_id))])
        res = self.client.query_points(
            collection_name=self.COLLECTION_NAME,
            query=vector,
            limit=limit,
            query_filter=qf
        )
        return [{"id": r.id, "score": r.score, "payload": r.payload} for r in res.points]

    def delete(self, point_id: str):
        self.client.delete(collection_name=self.COLLECTION_NAME, points_selector=[self._to_id(point_id)])

    def count(self) -> int:
        return self.client.count(collection_name=self.COLLECTION_NAME).count
