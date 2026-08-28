from datetime import datetime
import uuid


class OutcomeLogger:

    def __init__(self, memory_manager, calibrator):
        self.mm = memory_manager
        self.cal = calibrator

    def log_outcome(
        self,
        research_id: str,
        status: str,
        raw_confidence: float,
        domain: str = "global",
        user_feedback: str = None,
        execution_cost: float = None,
        usefulness_rating: int = None,
        api_cost: float = None
    ) -> dict:
        # Validasi
        if status not in ("success", "partial_success", "failed", "not_executed"):
            return {"error": f"Status tidak valid: {status}"}

        # Simpan outcome
        cur = self.mm.pg.conn.cursor()
        cur.execute(
            """INSERT INTO research_outcomes
            (research_id, status, user_feedback, execution_cost, usefulness_rating, api_cost, executed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (research_id, status, user_feedback, execution_cost, usefulness_rating, api_cost, datetime.now())
        )
        outcome_id = str(cur.fetchone()[0])
        cur.close()

        # Update kalibrasi (hanya success/failed)
        if status in ("success", "failed"):
            is_success = (status == "success")
            self.cal.record_outcome(raw_confidence, domain, is_success)

        return {
            "outcome_id": outcome_id,
            "research_id": research_id,
            "status": status,
            "calibration_updated": status in ("success", "failed")
        }

    def get_outcomes(self, research_id: str) -> list:
        cur = self.mm.pg.conn.cursor()
        cur.execute(
            "SELECT * FROM research_outcomes WHERE research_id = %s ORDER BY created_at DESC",
            (research_id,)
        )
        rows = cur.fetchall()
        cur.close()
        cols = ["id", "research_id", "status", "user_feedback", "actual_result", "correction",
                "additional_notes", "executed_at", "execution_cost", "execution_time_minutes",
                "tools_required", "api_cost", "usefulness_rating", "would_recommend", "created_at"]
        return [dict(zip(cols, r)) for r in rows]
