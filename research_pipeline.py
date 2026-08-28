from config import load_config
from memory_manager.manager import MemoryManager
from calibration.calibrator import ConfidenceCalibrator
from llm_analyzer.analyzer import LLMAnalyzer
import hashlib
import json


class ResearchPipeline:

    def __init__(self):
        config = load_config()
        self.mm = MemoryManager(config)
        self.cal = ConfidenceCalibrator(self.mm)
        self.llm = LLMAnalyzer(config)

    def research(self, query: str, project_slug: str = None, domain: str = "global") -> dict:
        # 1. Cek/tentukan project
        project = None
        if project_slug:
            project = self.mm.get_project(project_slug)
            if not project:
                return {"error": f"Project '{project_slug}' tidak ditemukan"}

        # 2. Cek apakah query sudah pernah diriset
        query_hash = hashlib.sha256(query.encode()).hexdigest()
        existing = self.mm.get_latest_by_hash(query_hash, project["id"] if project else None)

        # 3. Panggil LLM
        system_prompt = "Kamu adalah asisten riset teknis. Berikan jawaban yang akurat, singkat, dan berikan sumber jika memungkinkan."
        llm_result = self.llm.analyze(system_prompt, query)

        # 4. Kalibrasi confidence (placeholder - nanti pakai confidence dari LLM)
        raw_confidence = 0.85  # placeholder
        calibrated, cal_meta = self.cal.apply_calibration(raw_confidence, domain)

        # 5. Simpan ke database
        research_data = {
            "query_text": query,
            "project_id": project["id"] if project else None,
            "summary": llm_result["content"][:200],
            "full_analysis": {"content": llm_result["content"]},
            "sources": [],
            "tags": [],
            "confidence_score_raw": raw_confidence,
            "confidence_score_calibrated": calibrated,
            "api_cost": llm_result["api_cost"],
            "tokens_input": llm_result["tokens_input"],
            "tokens_output": llm_result["tokens_output"],
        }
        research_id = self.mm.save_research(research_data)

        # 6. Return hasil
        return {
            "research_id": research_id,
            "query": query,
            "project": project["name"] if project else None,
            "answer": llm_result["content"],
            "confidence_raw": raw_confidence,
            "confidence_calibrated": calibrated,
            "calibration_meta": cal_meta,
            "existing_research": existing is not None,
            "api_cost": llm_result["api_cost"],
        }

    def close(self):
        self.mm.close()
