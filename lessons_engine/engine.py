import json
from datetime import datetime


class LessonsEngine:

    def __init__(self, memory_manager, llm_analyzer):
        self.mm = memory_manager
        self.llm = llm_analyzer

    def generate_lessons(self, project_id: str = None) -> list:
        # Ambil semua outcome
        cur = self.mm.pg.conn.cursor()
        if project_id:
            cur.execute(
                """SELECT o.*, r.query_text, r.confidence_score_raw
                FROM research_outcomes o
                JOIN research_entries r ON o.research_id = r.id
                WHERE r.project_id = %s AND o.status IN ('success', 'failed')
                ORDER BY o.created_at DESC LIMIT 50""",
                (project_id,)
            )
        else:
            cur.execute(
                """SELECT o.*, r.query_text, r.confidence_score_raw
                FROM research_outcomes o
                JOIN research_entries r ON o.research_id = r.id
                WHERE o.status IN ('success', 'failed')
                ORDER BY o.created_at DESC LIMIT 50"""
            )
        rows = cur.fetchall()
        cur.close()

        if len(rows) < 5:
            return []  # Butuh minimal 5 outcome

        # Format data untuk LLM
        outcomes_text = ""
        for i, r in enumerate(rows[-10:]):  # 10 terakhir
            outcomes_text += f"{i+1}. Query: {r[14]}\n   Status: {r[2]} | Feedback: {r[3] or '-'}\n\n"

        prompt = f"""Berikut adalah hasil riset dan outcome-nya:

{outcomes_text}

Berdasarkan data di atas, berikan 1-3 pelajaran (lessons learned) dalam format JSON:
[{{"lesson_type": "source_reliability/method_effectiveness/pitfall_warning/optimization_tip",
   "title": "judul singkat",
   "content": "isi pelajaran"}}]

Hanya return JSON, tanpa teks lain."""

        result = self.llm.analyze(
            "Kamu adalah Lessons Engine. Analisis outcome riset dan berikan pelajaran.",
            prompt
        )

        # Parse JSON
        try:
            lessons = json.loads(result["content"].strip().replace("```json", "").replace("```", ""))
        except json.JSONDecodeError:
            return []

        # Simpan lessons
        saved = []
        for l in lessons:
            cur = self.mm.pg.conn.cursor()
            cur.execute(
                """INSERT INTO lessons_learned
                (source_type, project_id, lesson_type, title, content, confidence)
                VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
                ("pattern_analysis", project_id, l["lesson_type"], l["title"], l["content"], 0.7)
            )
            lid = str(cur.fetchone()[0])
            cur.close()
            saved.append({"id": lid, **l})

        return saved

    def get_active_lessons(self, project_id: str = None, limit: int = 10) -> list:
        cur = self.mm.pg.conn.cursor()
        if project_id:
            cur.execute(
                """SELECT * FROM lessons_learned
                WHERE project_id = %s AND is_active = true
                ORDER BY times_reinforced DESC, created_at DESC LIMIT %s""",
                (project_id, limit)
            )
        else:
            cur.execute(
                """SELECT * FROM lessons_learned
                WHERE is_active = true
                ORDER BY times_reinforced DESC, created_at DESC LIMIT %s""",
                (limit,)
            )
        rows = cur.fetchall()
        cur.close()
        cols = ["id", "source_type", "related_research_ids", "project_id", "lesson_type",
                "title", "content", "evidence", "confidence", "times_reinforced",
                "last_reinforced_at", "is_active", "applied_count", "success_rate", "created_at"]
        return [dict(zip(cols, r)) for r in rows]
