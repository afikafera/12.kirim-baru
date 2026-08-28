import os
from psycopg2 import connect
from qdrant_client import QdrantClient
from openai import OpenAI

# Load .env manual (tanpa library tambahan)
with open(".env") as f:
    for line in f:
        if "=" in line and not line.startswith("#"):
            key, val = line.strip().split("=", 1)
            os.environ[key] = val

print("=" * 40)
print("TEST KONEKSI")
print("=" * 40)

# 1. PostgreSQL
try:
    conn = connect(
        host=os.environ["POSTGRES_HOST"],
        port=os.environ["POSTGRES_PORT"],
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"]
    )
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM projects")
    print(f"✅ PostgreSQL: Connected ({cur.fetchone()[0]} projects)")
    cur.close()
    conn.close()
except Exception as e:
    print(f"❌ PostgreSQL: {e}")

# 2. Qdrant
try:
    qdrant = QdrantClient(
        host=os.environ["QDRANT_HOST"],
        port=int(os.environ["QDRANT_PORT"])
    )
    collections = qdrant.get_collections()
    print(f"✅ Qdrant: Connected ({len(collections.collections)} collections)")
except Exception as e:
    print(f"❌ Qdrant: {e}")

# 3. DeepSeek API
try:
    client = OpenAI(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url=os.environ["DEEPSEEK_BASE_URL"]
    )
    response = client.chat.completions.create(
        model=os.environ["DEEPSEEK_MODEL"],
        messages=[{"role": "user", "content": "Balas dengan OK"}],
        max_tokens=5
    )
    print(f"✅ DeepSeek API: {response.choices[0].message.content}")
except Exception as e:
    print(f"❌ DeepSeek API: {e}")

print("=" * 40)
