import re
import json
import contextvars
import threading
import time
import logging
from urllib.parse import urlparse
from hermes_agent.jsonl_logger import log_event, init_request_id
from concurrent.futures import ThreadPoolExecutor, as_completed
from aran_search.searcher import AgentReachSearcher
from aran_search.evidence import DocumentIntelligence
from hermes_agent.task_planner import TaskPlanner
from hermes_agent.completeness_checker import CompletenessChecker
from hermes_agent.plan_validator import PlannerContractValidator
from hermes_agent.knowledge_graph import KnowledgeGraph, NodeExecutionState
from hermes_agent.capability import (
    Capability,
    CapabilityRegistry,
    CapabilityResolver,
    CapabilityScheduler,
)
from hermes_agent.semantic_router import SemanticRouter
from hermes_agent.skill_router import SkillRouter
from hermes_agent.skill_bridge import SkillBridge
from hermes_agent.skill_executors import (
    agent_reach_executor,
    agent_reach_fetch_executor,
    weather_executor,
)
from hermes_agent.search_strategy import SearchStrategy
from hermes_agent.fact_checker import FactChecker, extract_json
from hermes_agent.llm_output_contract import llm_output_failure
from hermes_agent.fact_ranker import FactRanker
from hermes_agent.token_profiler import TokenProfiler
from hermes_agent.latency_profiler import LatencyProfiler
from hermes_agent.user_memory import UserMemory
from hermes_agent.manifest_builder import ManifestBuilder
from hermes_agent.section_scheduler import SectionScheduler
from hermes_agent.section_store import SectionStore
from hermes_agent.section_worker import SectionWorker
from hermes_agent.coverage_evaluator import CoverageEvaluator
from hermes_agent.section_splitter import SectionSplitter
from hermes_agent.outcome_classifier import OutcomeClassifier
from hermes_agent.continuation_policy import ContinuationPolicy
from hermes_agent.continuation_engine import ContinuationEngine
from hermes_agent.output_aggregator import OutputAggregator
from hermes_agent.output_manifest import SectionStatus

logger = logging.getLogger(__name__)

_WEB_OCR_LOCK = threading.Lock()


class HermesAgent:

    MAX_ITERATIONS = 20
    PARALLEL_NODES = 3
    MIN_COVERAGE = 50
    MAX_RETRIES = 2
    MAX_TOTAL_FACTS = 80
    EARLY_STOP_COVERAGE = 85
    MIN_FACTS_TO_STOP = 25
    MAX_FACTS_PER_NODE = 8
    MAX_FACTS_IN_ANSWER = 5
    MAX_WORKERS = 4
    CACHE_MAX = 500
    RESEARCH_THRESHOLD = 5
    MAX_RECOVERY_ATTEMPTS = 1

    def __init__(self, memory_manager, calibrator, llm_analyzer, outcome_logger, lessons_engine):
        self.mm = memory_manager
        self.cal = calibrator
        self.llm = llm_analyzer
        self.outcome = outcome_logger
        self.lessons = lessons_engine
        self.user_memory = UserMemory()
        self.task_planner = TaskPlanner(llm_analyzer)
        self.router = SemanticRouter()
        self.skill_router = SkillRouter()
        self.capability_registry = CapabilityRegistry()
        self.capability_scheduler = CapabilityScheduler(self.capability_registry)
        self.completeness = CompletenessChecker(llm_analyzer)
        self.strategy = SearchStrategy(llm_analyzer)
        self.searcher = AgentReachSearcher(llm_analyzer)

        # Skill bridge: core delegates capability execution to registered skills.
        self.skill_bridge = SkillBridge(self.skill_router)
        self.skill_bridge.register(
            "agent-reach",
            lambda query, **kwargs: agent_reach_executor(
                self.searcher,
                query,
                **kwargs,
            ),
        )
        self.skill_bridge.register(
            "agent-reach-fetch",
            lambda url, **kwargs: agent_reach_fetch_executor(
                self.searcher,
                url,
                **kwargs,
            ),
        )
        self.skill_bridge.register(
            "weather",
            lambda query, **kwargs: weather_executor(
                self.searcher,
                query,
                **kwargs,
            ),
        )
        self.docintel = DocumentIntelligence()
        self.facts = FactChecker(llm_analyzer)
        self.ranker = FactRanker()
        self._strategy_cache = {}
        self._validation_cache = {}

        # Output Scaling components.
        # Mutable per-request state (scheduler/store) is created
        # inside research() to prevent cross-request state leakage.
        self.manifest_builder = ManifestBuilder()
        self.output_aggregator = OutputAggregator()
        self.outcome_classifier = OutcomeClassifier()
        self.continuation_policy = ContinuationPolicy()
        self.section_worker = SectionWorker(self.llm)
        self.coverage_evaluator = CoverageEvaluator(self.llm)
        self.section_splitter = SectionSplitter()

    def _make_requirement_id(self, topic: str, need: str) -> str:
        return f"{topic} [{need}]"

    def _extract_memory_intent(self, goal: str):
        prompt = f"""The user gave this instruction to remember something:

"{goal}"

Extract what should be remembered as JSON:
{{"topic": "short topic name", "field": "short field name", "value": "the value to remember"}}

RULES:
- topic and field must be short snake_case-like labels (max 3 words each).
- value must be the exact value the user wants remembered (e.g. a code, name, number).
- Do not invent information not present in the instruction.
- Return ONLY the JSON object, nothing else.
"""
        try:
            result = self.llm.analyze(
                system_prompt=(
                    "You are a strict memory-extraction assistant. "
                    "Extract only what is explicitly stated. Return JSON only."
                ),
                user_query=prompt,
                temperature=0.0,
            )
            raw = result["content"].strip()
            import json
            try:
                parsed = json.loads(raw)
            except Exception:
                start = raw.find("{")
                end = raw.rfind("}")
                parsed = json.loads(raw[start:end + 1]) if start >= 0 and end > start else None

            if (
                isinstance(parsed, dict)
                and all(k in parsed for k in ("topic", "field", "value"))
                and all(isinstance(parsed[k], str) and parsed[k].strip() for k in ("topic", "field", "value"))
            ):
                return parsed
            return None
        except Exception as exc:
            logger.warning("[extract_memory_intent] fail: %s", exc)
            return None

    def _total_facts(self, kg: KnowledgeGraph, scope: set = None) -> int:
        nodes = kg.graph["nodes"]
        if scope is not None:
            nodes = {k: v for k, v in nodes.items() if k in scope}
        return sum(len(n.get("facts", [])) for n in nodes.values())

    def _coverage(self, kg: KnowledgeGraph, scope: set = None) -> float:
        nodes = kg.graph["nodes"]
        if scope is not None:
            nodes = {k: v for k, v in nodes.items() if k in scope}
        found = sum(1 for n in nodes.values() if n.get("status") in ("found", "verified"))
        total = sum(1 for n in nodes.values() if n.get("type") != "project")
        return (found / total * 100) if total > 0 else 0

    def _fetch_url_parallel(self, urls: list, seen: set, query: str, errors: dict = None) -> list:
        results = []
        def fetch_one(url):
            if url in seen: return None
            raw = self.skill_bridge.execute_skill(
                "agent-reach-fetch",
                url,
            )
            if raw and raw.startswith("Error fetch"):
                logger.info("[AUDIT FETCH ERROR] url=%s raw=%r", url, raw[:300])
                if errors is not None:
                    errors[url] = raw
                return None
            if raw and len(raw) > 50:
                processed = self.docintel.process(raw, query, url=url)

                content = processed["formatted"]

                # Web image OCR bridge: optional enrichment only.
                if "![" in content:
                    try:
                        from aran_search.agent_browser_asset_resolver import (
                            AgentBrowserAssetResolver,
                        )

                        with _WEB_OCR_LOCK:
                            resolver = AgentBrowserAssetResolver()
                            assets = resolver.fetch_spec_assets(url)

                        ocr_blocks = []
                        for asset_url, asset_bytes in assets.items():
                            asset_type = resolver.classify_asset(asset_url)
                            if resolver.processing_strategy(asset_type) != "ocr_extract":
                                continue

                            ocr_result = resolver.ocr_asset_paddle(
                                asset_bytes,
                                asset_type=asset_type,
                            )
                            texts = ocr_result.get("texts", [])
                            ocr_text = "\n".join(
                                str(text).strip()
                                for text in texts
                                if str(text).strip()
                            )

                            if ocr_text:
                                ocr_blocks.append(
                                    f"[WEB IMAGE OCR | {asset_type}] {asset_url}\n{ocr_text}"
                                )
                                logger.info(
                                    "[AUDIT WEB OCR] url=%s asset=%s asset_type=%s texts=%d",
                                    url, asset_url, asset_type, len(texts),
                                )

                        if ocr_blocks:
                            content += "\n\n" + "\n\n".join(ocr_blocks)

                    except Exception as exc:
                        logger.warning(
                            "[AUDIT WEB OCR ERROR] url=%s error=%s", url, exc,
                        )

                logger.info(
                    "[AUDIT DOCINTEL] url=%s doc_type=%s sections_total=%s sections_kept=%s char_before=%s char_after=%s",
                    url, processed.get("doc_type"), processed.get("sections_total"),
                    processed.get("sections_kept"), processed.get("char_before"), processed.get("char_after"),
                )
                return {"url": url, "content": content, "doc_type": processed["doc_type"]}
            else:
                if errors is not None and url not in errors:
                    errors[url] = "EMPTY_CONTENT" if raw is not None else "NO_RESPONSE"
            return None
        with ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as executor:
            futures = {
                executor.submit(contextvars.copy_context().run, fetch_one, url): url
                for url in urls
                if url not in seen
            }

            fetched = {}
            for future in as_completed(futures):
                result = future.result()
                if result:
                    fetched[futures[future]] = result

        return [
            fetched[url]
            for url in urls
            if url in fetched
        ]

    def _get_strategy(self, topic: str, need: str) -> dict:
        cache_key = f"{topic}|{need}"
        if cache_key not in self._strategy_cache:
            if len(self._strategy_cache) >= self.CACHE_MAX:
                keys = list(self._strategy_cache.keys())[:100]
                for k in keys: del self._strategy_cache[k]
            self._strategy_cache[cache_key] = self.strategy.generate(
                f"{topic} {need}", "general", "general", topic
            )
        return self._strategy_cache[cache_key]

    @staticmethod
    def _filter_evidence_by_source_policy(evidence: list, constraints: list) -> list:
        """Apply deterministic source restrictions before evidence validation."""
        if not evidence or not constraints:
            return evidence

        constraint_text = " ".join(
            str(c).strip().lower()
            for c in constraints
            if str(c).strip()
        )

        if "official" not in constraint_text or "ietf" not in constraint_text:
            return evidence

        official_domains = {
            "rfc-editor.org",
            "datatracker.ietf.org",
            "ietf.org",
        }

        filtered = []
        for ev in evidence:
            url = str(ev.get("url", "")).strip()
            host = urlparse(url).netloc.lower().split(":")[0]

            if (
                host in official_domains
                or any(host.endswith("." + domain) for domain in official_domains)
            ):
                filtered.append(ev)
            else:
                logger.info(
                    "[AUDIT SOURCE POLICY] decision=REJECT "
                    "reason=official_ietf_only url=%s host=%s",
                    url,
                    host,
                )

        logger.info(
            "[AUDIT SOURCE POLICY] policy=official_ietf_only "
            "input=%d accepted=%d rejected=%d",
            len(evidence),
            len(filtered),
            len(evidence) - len(filtered),
        )
        return filtered

    def _evaluate_requirement_fulfillment(
        self,
        topic: str,
        need: str,
        success_criteria: list,
        facts: dict,
        cache: dict,
    ):
        """
        Determine whether extracted request-local facts fulfill the
        planner's success criteria for a requirement.

        This is a semantic completion gate. It must use only supplied
        facts and must never invent missing values.
        """
        if not facts:
            return False, "no_request_facts", []

        import json

        cache_key = (
            topic,
            need,
            tuple(success_criteria or []),
            json.dumps(facts, ensure_ascii=False, sort_keys=True, default=str),
        )

        if cache_key in cache:
            fulfilled, reason, missing = cache[cache_key]
            logger.info(
                "[AUDIT SEMANTIC CACHE] topic=%s decision=%s missing=%s",
                topic,
                "FULFILLED" if fulfilled else "MISSING",
                missing,
            )
            return fulfilled, reason, missing

        prompt = f"""You are a strict research requirement fulfillment evaluator.

REQUIREMENT TOPIC:
{topic}

REQUIREMENT NEED:
{need}

SUCCESS CRITERIA:
{json.dumps(success_criteria or [], ensure_ascii=False)}

EXTRACTED FACTS:
{json.dumps(facts, ensure_ascii=False, default=str)}

TASK:
Determine whether the supplied extracted facts fulfill ALL factual
requirements represented by the success criteria.

IMPORTANT:
- Judge ONLY from the supplied facts.
- Do not use general knowledge.
- Do not infer values that are not explicitly present in the facts.
- The existence of facts does NOT itself mean the requirement is fulfilled.
- Every factual component required by the success criteria must be supported.
- If any required factual component is missing, return fulfilled=false.
- Never invent or complete missing values.
- A documentation endpoint or parameter description does not count as
  the actual requested value unless that value is explicitly present.
- Return fulfilled=true only when the supplied facts support the required
  factual result.

Return ONLY valid JSON:
{{"fulfilled": true_or_false, "missing": ["specific missing criteria 1", "specific missing criteria 2"], "reason": "short reason"}}
"""

        try:
            result = self.llm.analyze(
                system_prompt=(
                    "You are a strict research requirement fulfillment "
                    "evaluator. Use only the supplied facts. "
                    "Never infer or invent missing values."
                ),
                user_query=prompt,
                temperature=0.0,
            )

            raw = result.get("content", "").strip()
            parsed = None

            try:
                parsed = json.loads(raw)
            except Exception:
                start = raw.find("{")
                end = raw.rfind("}")
                if start >= 0 and end > start:
                    try:
                        parsed = json.loads(raw[start:end + 1])
                    except Exception:
                        parsed = None

            fulfilled = (
                isinstance(parsed, dict)
                and parsed.get("fulfilled") is True
            )
            reason = (
                parsed.get("reason", "no reason")
                if isinstance(parsed, dict)
                else "invalid evaluator response"
            )
            missing = []
            if isinstance(parsed, dict) and isinstance(parsed.get("missing"), list):
                missing = [str(m).strip() for m in parsed["missing"] if str(m).strip()]

        except Exception as exc:
            fulfilled = False
            reason = f"evaluator_error:{type(exc).__name__}"
            missing = []

        cache[cache_key] = (fulfilled, reason, missing)

        logger.info(
            "[AUDIT SEMANTIC REQUIREMENT] topic=%s decision=%s missing=%s reason=%s",
            topic,
            "FULFILLED" if fulfilled else "MISSING",
            missing,
            reason,
        )

        return fulfilled, reason, missing

    def _extract_weather_target(self, text: str) -> tuple[str | None, str | None]:
        """
        Extract target location and target date from market question or topic.
        """
        if not text:
            return None, None

        KNOWN_CITIES = [
            "Shanghai", "Dallas", "New Orleans", "Wellington", "Munich",
            "Hong Kong", "San Francisco", "Beijing", "Tokyo", "London",
            "Paris", "New York", "Singapore", "Jakarta", "Sydney", "Berlin",
        ]
        loc = None
        for city in KNOWN_CITIES:
            if re.search(r"\b" + re.escape(city) + r"\b", text, re.IGNORECASE):
                loc = city
                break

        if not loc:
            m_city = re.search(r"(?:in|for|at)\s+([A-Z][a-zA-Z\s]+?)(?:\s+on|\s*\?|$)", text)
            if m_city:
                candidate = m_city.group(1).strip()
                if candidate.lower() not in {"the", "a", "an"}:
                    loc = candidate

        target_date = None
        m_iso = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
        if m_iso:
            target_date = m_iso.group(1)
        else:
            m_date = re.search(
                r"\b(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s*,?\s*(20\d{2}))?\b",
                text,
                re.IGNORECASE,
            )
            if m_date:
                month_name = m_date.group(1).lower()
                day = int(m_date.group(2))
                year = int(m_date.group(3)) if m_date.group(3) else 2026
                month_map = {
                    "jan": 1, "january": 1, "feb": 2, "february": 2,
                    "mar": 3, "march": 3, "apr": 4, "april": 4,
                    "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
                    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
                    "oct": 10, "october": 10, "nov": 11, "november": 11,
                    "dec": 12, "december": 12,
                }
                m_num = month_map.get(month_name, 9)
                target_date = f"{year:04d}-{m_num:02d}-{day:02d}"

        return loc, target_date

    def _resolve_recovery_requirement(
        self,
        unmet_reason: str,
        current_facts: dict,
        plan: dict,
        missing_items: list | None = None,
        goal: str = "",
    ) -> dict | None:
        """
        Generic Continuation Planner:
        Transforms structured missing criteria into 1 generic targeted requirement.
        Strictly requires missing_items from semantic evaluator; no loose fallback.
        """
        if not missing_items:
            return None

        clean_missing = [str(m).strip() for m in missing_items if str(m).strip()]
        if not clean_missing:
            return None

        primary_missing = "; ".join(clean_missing[:3])
        base_subject = plan.get("goal") or goal or "Research target"

        return {
            "topic": f"{base_subject} - {primary_missing}",
            "need": f"Collect specific verifiable data: {primary_missing}",
            "priority": "high",
            "depends_on": [],
            "is_recovery": True,
        }

    def _inject_recovery_requirement(
        self,
        new_k: dict,
        plan: dict,
        requirement_map: dict,
        kg,
        request_scope: set,
        goal: str,
    ) -> str | None:
        """
        Phase 1 Atomic 4-Way State Injection.
        """
        req_id = self._make_requirement_id(new_k["topic"], new_k["need"])
        if req_id in requirement_map:
            return None

        # 1. plan['knowledge_required'] (wajib untuk dependency resolution)
        plan.setdefault("knowledge_required", []).append(new_k)

        # 2. requirement_map (antrian baca request_ready_nodes)
        requirement_map[req_id] = new_k

        # 3. KnowledgeGraph nodes & edges
        kg.add_node(req_id, status="planned", confidence=0.7)
        kg.add_relation(goal, "requires", req_id)
        for dep in new_k.get("depends_on", []):
            for existing in plan.get("knowledge_required", []):
                if existing["topic"] == dep:
                    dep_id = self._make_requirement_id(existing["topic"], existing["need"])
                    kg.add_relation(req_id, "depends_on", dep_id)
                    break

        # 4. request_scope (set untuk metrik coverage & facts limit)
        request_scope.add(req_id)

        return req_id

    def _validate_evidence_relevance(
        self,
        topic: str,
        need: str,
        evidence: list,
    ) -> list:
        """
        Requirement-level evidence gate.

        Evidence hanya diteruskan ke extraction jika dokumen secara
        substantif membahas requirement yang sedang diproses.

        Validator bersifat generic:
        - tidak hardcode nama protokol;
        - tidak hardcode angka benchmark;
        - tidak menentukan fakta teknis;
        - hanya menentukan apakah evidence relevan dengan topic + need.

        Jika LLM validator gagal, evidence TIDAK otomatis dianggap valid.
        """

        if not evidence:
            return []

        validated = []

        for ev in evidence:
            url = ev.get("url", "")
            content = ev.get("content", "")

            cache_key = (topic, need, url, content)

            if cache_key not in self._validation_cache:
                same_url_keys = [
                    k for k in self._validation_cache
                    if len(k) == 4 and k[2] == url
                ]
                if same_url_keys:
                    logger.info(
                        "[AUDIT EVIDENCE CACHE MISS] topic=%s url=%s "
                        "same_url_keys=%d",
                        topic,
                        url,
                        len(same_url_keys),
                    )

            if cache_key in self._validation_cache:
                relevant, reason = self._validation_cache[cache_key]

                logger.info(
                    "[AUDIT EVIDENCE CACHE] topic=%s url=%s decision=%s",
                    topic,
                    url,
                    "ACCEPT" if relevant else "REJECT",
                )

                if relevant:
                    validated.append(ev)

                continue

            source_type = str(
                ev.get("source_type")
                or ev.get("evidence_type")
                or ev.get("doc_type")
                or ""
            ).lower()

            if not content or (len(content.strip()) < 80 and source_type != "user_attachment"):
                logger.info(
                    "[AUDIT EVIDENCE GATE] topic=%s url=%s decision=REJECT reason=empty_or_short",
                    topic,
                    url,
                )
                continue

            prompt = f"""You are an evidence relevance validator.

REQUIREMENT TOPIC:
{topic}

REQUIREMENT NEED:
{need}

EVIDENCE URL:
{url}

EVIDENCE CONTENT:
{content[:5000]}

TASK:
Determine whether this document substantively provides evidence for the
specific requirement above.

IMPORTANT:
- Judge ONLY from the supplied evidence content.
- Do not use general knowledge.
- A document merely mentioning the entity/topic is NOT sufficient.
- Configuration information is not sufficient for a performance requirement.
- General metadata is not sufficient for a technical requirement.
- The document must contain substantive information that contributes to
  answering one or more parts of the stated requirement.
- A document does NOT need to satisfy the entire requirement by itself.
- If the requirement contains multiple factual components, fields,
  attributes, or sub-requirements, mark the document relevant if it
  provides reliable evidence for ANY one or more of those components.
- Partial evidence is relevant evidence.
- Do NOT reject a document merely because another requested component
  is missing from that document.
- Overall completeness must be determined later by evidence aggregation,
  fact extraction, and requirement coverage.
- Reject the document only when it provides no substantive information
  that contributes to the requirement, or when the content is clearly
  unrelated or unusable.

Return ONLY valid JSON:

{{"relevant": true_or_false, "reason": "short reason"}}
"""

            try:
                result = self.llm.analyze(
                    system_prompt=(
                        "You are a strict evidence relevance classifier. "
                        "Use only the supplied document. "
                        "Never infer missing evidence from general knowledge."
                    ),
                    user_query=prompt,
                    temperature=0.0,
                )

                # Type & contract normalization:
                content = result.get("content") if isinstance(result, dict) else None

                parsed = None
                if isinstance(content, dict):
                    parsed = content
                elif isinstance(content, list):
                    parsed = content[0] if content and isinstance(content[0], dict) else None
                elif isinstance(content, str):
                    raw = content.strip()
                    if raw:
                        parsed_candidate = extract_json(raw)
                        if isinstance(parsed_candidate, dict):
                            parsed = parsed_candidate
                        elif isinstance(parsed_candidate, list) and parsed_candidate and isinstance(parsed_candidate[0], dict):
                            parsed = parsed_candidate[0]

                if isinstance(parsed, dict) and isinstance(parsed.get("relevant"), bool):
                    relevant = parsed["relevant"]
                    reason = str(parsed.get("reason") or ("accepted" if relevant else "rejected"))
                elif isinstance(parsed, dict):
                    relevant = False
                    reason = "validator_contract_failure:non_boolean_relevant"
                else:
                    contract_fail = llm_output_failure(result)
                    relevant = False
                    if contract_fail:
                        reason = f"validator_contract_failure:{contract_fail}"
                    else:
                        reason = "invalid validator response"

            except Exception as exc:
                relevant = False
                reason = f"validator_error:{type(exc).__name__}"

            self._validation_cache[cache_key] = (relevant, reason)

            logger.info(
                "[AUDIT EVIDENCE GATE] topic=%s url=%s decision=%s reason=%s",
                topic,
                url,
                "ACCEPT" if relevant else "REJECT",
                reason,
            )

            if relevant:
                validated.append(ev)

        logger.info(
            "[AUDIT EVIDENCE GATE SUMMARY] topic=%s accepted=%d rejected=%d total=%d",
            topic,
            len(validated),
            len(evidence) - len(validated),
            len(evidence),
        )

        return validated


    @staticmethod
    def _source_policy(goal: str) -> dict:
        """Allow media only when the user explicitly asks for it."""
        text = (goal or "").lower()
        video_terms = (
            "youtube", "youtu.be", "video", "video review", "review video",
            "demo", "sound test", "tes suara", "pengamatan", "tonton",
        )
        social_terms = (
            "tiktok", "instagram", "facebook", "social media", "media sosial",
        )
        return {
            "allow_video": any(term in text for term in video_terms),
            "allow_social": any(term in text for term in social_terms),
        }

    def research(self, goal: str, context: str = "", attachments: list | None = None) -> dict:
        profiler = TokenProfiler()
        req_id = init_request_id()

        # Capability selection is separate from research planning.
        selected_skill = self.skill_router.select(goal)
        logger.info(
            "[skill-router] req_id=%s selected=%s score=%s",
            req_id,
            selected_skill["name"] if selected_skill else None,
            selected_skill["score"] if selected_skill else None,
        )

        # Persistent user memory.
        # Memory is user context, NOT research evidence.
        logger.info(
            "[AUDIT MEMORY QUERY] req_id=%s goal=%r",
            req_id,
            goal,
        )
        memory_results = self.user_memory.search(goal)

        memory_context = ""
        if memory_results:
            memory_context = "\n".join(
                f"- {m['topic']}: {m['field']} = {m['value']}"
                for m in memory_results[:10]
            )

            logger.info(
                "[USER MEMORY] req_id=%s matches=%d",
                req_id,
                len(memory_results),
            )

        log_event(
            "research_start",
            {
                "goal": goal,
            },
        )
        latency = LatencyProfiler()

        # Request-local fact snapshot.
        # Persistent KG tetap menyimpan historical facts, tetapi synthesis
        # hanya boleh memakai facts yang dihasilkan pada research run ini.
        request_facts = {}
        request_facts_lock = threading.Lock()
        semantic_completion_cache = {}

        def request_requirement_complete(req_id):
            prefix = f"{req_id}/"
            return any(key.startswith(prefix) for key in request_facts)

        t0_total = time.time()

        logger.info(
            "[AUDIT RESEARCH ATTACHMENTS] count=%d types=%s contents=%s",
            len(attachments or []),
            [
                e.get("source_type") or e.get("evidence_type") or e.get("doc_type")
                for e in (attachments or [])
                if isinstance(e, dict)
            ],
            [
                len(e.get("content", ""))
                for e in (attachments or [])
                if isinstance(e, dict)
            ],
        )

        # 1. Plan
        
        logger.info(
            "[TRACE ROUTE INPUT] goal=%r has_context=%s context_chars=%d",
            goal,
            bool(context.strip()),
            len(context),
        )

        route = self.router.route(
            goal,
            has_context=bool(context.strip()),
            has_attachments=bool(attachments),
        )

        logger.info(
            "[router] mode=%s reason=%s conf=%.2f",
            route.mode,
            route.reason,
            route.confidence,
        )

        if route.mode == "memory":
            logger.info("[router] memory write intent")

            extracted = self._extract_memory_intent(goal)

            if extracted:
                self.user_memory.add(
                    topic=extracted["topic"],
                    field=extracted["field"],
                    value=extracted["value"],
                    source="user",
                )
                logger.info(
                    "[AUDIT MEMORY WRITE] topic=%s field=%s value=%s",
                    extracted["topic"],
                    extracted["field"],
                    extracted["value"],
                )
                return (
                    f"Dicatat: {extracted['topic']} / "
                    f"{extracted['field']} = {extracted['value']}"
                )

            logger.warning("[AUDIT MEMORY WRITE] extraction_failed goal=%r", goal)
            return (
                "Maaf, saya tidak bisa mengekstrak apa yang perlu diingat "
                "dari permintaan itu. Bisa dijelaskan ulang?"
            )

        if route.mode == "direct":
            logger.info("[router] bypass planner/search")

            attachment_context = ""
            if attachments:
                attachment_context = "\n\n".join(
                    e.get("content", "").strip()
                    for e in attachments
                    if isinstance(e, dict) and e.get("content")
                )

                if attachment_context:
                    logger.info(
                        "[AUDIT DIRECT ATTACHMENT] documents=%d chars=%d",
                        len(attachments),
                        len(attachment_context),
                    )

            direct_query = goal

            if context:
                direct_query = (
                    "CONVERSATION CONTEXT:\n"
                    f"{context.strip()}\n\n"
                    "USER QUESTION:\n"
                    f"{goal}"
                )

            if attachment_context:
                direct_query += (
                    "\n\n"
                    "USER ATTACHMENT EVIDENCE:\n"
                    f"{attachment_context}"
                )

            if memory_context:
                direct_query += (
                    "\n\n"
                    "PERSISTENT USER MEMORY:\n"
                    f"{memory_context}"
                )

            result = self.llm.analyze(
                system_prompt=(
                    "You are a precise technical assistant. "
                    "Answer directly and concisely. "
                    "Use only facts provided by the user. "
                    "Treat CONVERSATION CONTEXT as prior discussion and verified information from previous turns. "
                    "Treat USER ATTACHMENT EVIDENCE as user-provided evidence. "
                    "Do not invent missing facts, labels, constraints, or assumptions. "
                    "For logic and reasoning problems, distinguish facts from assumptions. "
                    "If the information is insufficient for a unique answer, say so clearly "
                    "and identify what information is missing. "
                    "Do not search the web. "
                    "Do not use the research pipeline."
                ),
                user_query=direct_query,
                temperature=0.2,
            )

            return result["content"]


        # KnowledgeGraph is research-only. Direct requests must not acquire
        # the global KG lock.
        kg = KnowledgeGraph()

        logger.info(
            "[AUDIT KG LOAD] pre_existing_nodes=%d pre_existing_facts=%d",
            len(kg.graph["nodes"]),
            sum(len(n.get("facts", [])) for n in kg.graph["nodes"].values()),
        )

        logger.info(f"[orchestrator] planning: {goal[:80]}")
        latency.start("planner")
        plan = self.task_planner.plan(goal, context=context)
        # Unconditional defensive validation: Ensure plan is valid before execution
        plan = PlannerContractValidator.validate(plan, goal=goal)
        profiler.add("planner", {"tokens_input": 0, "tokens_output": 0, "api_cost": 0})
        # Do not let CompletenessChecker expand a plan produced by the
        # deterministic TaskPlanner fallback. The fallback exists because
        # structured planning failed; allowing another LLM to mutate that
        # degraded plan can create requirements outside the active request.
        if (
            not plan.get("planner_fallback")
            and (
                plan.get("confidence", 0) < 0.7
                or len(plan.get("knowledge_required", [])) > 3
            )
        ):
            plan = self.completeness.check(plan)
            plan = PlannerContractValidator.validate(plan, goal=goal)
        elif plan.get("planner_fallback"):
            logger.info(
                "[AUDIT COMPLETENESS SKIP] planner_fallback=True "
                "requirements=%d",
                len(plan.get("knowledge_required", [])),
            )
        latency.stop("planner")

        log_event(
            "planner_done",
            {
                "confidence": plan.get("confidence"),
                "requirements": len(plan.get("knowledge_required", [])),
            },
        )

        num_requirements = len(plan.get("knowledge_required", []))
        force_research = num_requirements >= self.RESEARCH_THRESHOLD
        profiler.set_metadata(nodes=num_requirements)

        # Preserve URLs explicitly supplied by the user so the research
        # pipeline can fetch the exact target instead of searching for
        # generic methods to access it.
        direct_urls = re.findall(r'https?://[^\s<>"]+', goal)

        if direct_urls:
            logger.info(
                "[AUDIT DIRECT URL INPUT] req_id=%s urls=%s",
                req_id,
                direct_urls,
            )

        # 2. Build requirement graph
        kg.add_node(goal, node_type="project", status="planned")
        requirement_map = {}
        for k in plan.get("knowledge_required", []):
            req_id = self._make_requirement_id(k["topic"], k["need"])
            requirement_map[req_id] = k
            kg.add_node(req_id, status="planned", confidence=0.7)
            kg.add_relation(goal, "requires", req_id)
            for dep_topic in k.get("depends_on", []):
                for k2 in plan.get("knowledge_required", []):
                    if (
                        k2.get("id") == dep_topic
                        or k2.get("topic") == dep_topic
                        or PlannerContractValidator.canonical_id(k2.get("id")) == PlannerContractValidator.canonical_id(dep_topic)
                        or PlannerContractValidator.normalize_topic(k2.get("topic")) == PlannerContractValidator.normalize_topic(dep_topic)
                    ):
                        dep_req_id = self._make_requirement_id(k2["topic"], k2["need"])
                        kg.add_relation(req_id, "depends_on", dep_req_id)
                        break

        request_scope = set(requirement_map.keys()) | {goal}
        source_policy = self._source_policy(goal)
        logger.info(
            "[SOURCE POLICY] video=%s social=%s goal=%r",
            source_policy["allow_video"],
            source_policy["allow_social"],
            goal[:120],
        )

        all_evidence = []

        # Request-local fetch cache.
        # A direct user URL must be fetched only once per research request.
        request_fetch_cache = {}
        attachment_evidence = [
            {**e, "req_id": "attachment"}
            for e in (attachments or [])
            if isinstance(e, dict) and e.get("content")
        ]
        if attachment_evidence:
            logger.info(
                "[AUDIT ATTACHMENT EVIDENCE] documents=%d chars=%d",
                len(attachment_evidence),
                sum(len(e.get("content", "")) for e in attachment_evidence),
            )
        iterations_completed = 0
        retry_count = {}
        recovery_attempts = 0
        max_recovery_attempts = getattr(self, "MAX_RECOVERY_ATTEMPTS", 1)
        attempted_recovery_sigs = set()

        # 2.5 Direct URL preload
        #
        # Explicit URLs supplied by the user are request-level HARD TARGETS.
        # Fetch each target exactly once before requirement execution so
        # parallel planner requirements cannot race and invoke the same
        # connector repeatedly.
        request_fetch_cache = {}

        if direct_urls:
            preload_urls = list(dict.fromkeys(direct_urls))

            logger.info(
                "[AUDIT DIRECT PRELOAD] req_id=%s urls=%s",
                req_id,
                preload_urls,
            )

            preload_results = self._fetch_url_parallel(
                preload_urls,
                set(),
                goal,
            )

            for evidence in preload_results:
                url = evidence.get("url")
                if url:
                    request_fetch_cache[url] = evidence

                    evidence_copy = {
                        **evidence,
                        "req_id": "direct_url",
                    }
                    all_evidence.append(evidence_copy)

            logger.info(
                "[AUDIT DIRECT PRELOAD DONE] req_id=%s fetched=%d urls=%s",
                req_id,
                len(request_fetch_cache),
                list(request_fetch_cache.keys()),
            )

        # 3. Graph-driven loop
        # IMPORTANT: execution scope must come only from the current request plan.
        # Persistent KG is memory, not a source of tasks for this request.
        def request_ready_nodes():
            ready = []

            # AUDIT ONLY: jangan mengubah keputusan readiness.
            logger.info(
                "[AUDIT READY INIT] requirements=%d nodes=%d",
                len(requirement_map),
                len(kg.graph.get("nodes", {})),
            )


            for req_id, k in requirement_map.items():
                node = kg.graph["nodes"].get(req_id, {})
                status = node.get("status", "MISSING_NODE")
                deps = k.get("depends_on", [])

                # Persistent KG status is historical state only.
                # It must NOT mark this requirement complete for the
                # current request. Current-request evidence/facts are
                # evaluated later by the request-local audit.
                if status in ("found", "verified"):
                    logger.info(
                        "[AUDIT REQ NODE] req_id=%s status=%s deps=%s "
                        "decision=EXECUTE_CURRENT_PERSISTENT_COMPLETE",
                        req_id,
                        status,
                        deps,
                    )

                # Current-request completion has priority over persistent KG
                # status. A requirement already satisfied in this research run
                # must not be searched/extracted again.
                if request_requirement_complete(req_id):
                    logger.info(
                        "[AUDIT REQ NODE] req_id=%s status=%s deps=%s "
                        "decision=SKIP_CURRENT_REQUEST_COMPLETE",
                        req_id,
                        status,
                        deps,
                    )
                    continue

                retries = retry_count.get(req_id, 0)
                if retries >= self.MAX_RETRIES:
                    logger.info(
                        "[AUDIT REQ NODE] req_id=%s status=%s deps=%s retries=%d "
                        "decision=SKIP_MAX_RETRIES",
                        req_id,
                        status,
                        deps,
                        retries,
                    )
                    continue

                dependencies_met = True
                blocked_by = None

                for dep_topic in deps:
                    dep_req_id = None

                    for k2 in plan.get("knowledge_required", []):
                        if (
                            k2.get("id") == dep_topic
                            or k2.get("topic") == dep_topic
                            or PlannerContractValidator.canonical_id(k2.get("id")) == PlannerContractValidator.canonical_id(dep_topic)
                            or PlannerContractValidator.normalize_topic(k2.get("topic")) == PlannerContractValidator.normalize_topic(dep_topic)
                        ):
                            dep_req_id = self._make_requirement_id(
                                k2["topic"],
                                k2["need"],
                            )
                            break

                    if dep_req_id:
                        dep_node = kg.graph["nodes"].get(dep_req_id, {})
                        dep_status = dep_node.get("status", "MISSING_NODE")

                        if dep_status not in ("found", "verified"):
                            dependencies_met = False
                            blocked_by = f"{dep_req_id}:{dep_status}"
                            break

                    else:
                        logger.warning(
                            "[AUDIT REQ DEP MISSING] req_id=%s dep_topic=%s",
                            req_id,
                            dep_topic,
                        )

                decision = "READY" if dependencies_met else "BLOCKED"

                logger.info(
                    "[AUDIT REQ NODE] req_id=%s status=%s deps=%s retries=%d "
                    "dependencies_met=%s blocked_by=%s decision=%s",
                    req_id,
                    status,
                    deps,
                    retries,
                    dependencies_met,
                    blocked_by,
                    decision,
                )

                if dependencies_met:
                    ready.append({
                        "topic": req_id,
                        "relation": "requires",
                        "status": status,
                    })

            logger.info(
                "[AUDIT READY NODES] ready=%d total_requirements=%d",
                len(ready),
                len(requirement_map),
            )

            return ready

        while iterations_completed < self.MAX_ITERATIONS:
            ready = request_ready_nodes()

            if not ready:
                # CONTROLLER TERMINATION & RECOVERY GATE
                current_facts = dict(request_facts)
                semantic_topic = plan.get("goal", goal)
                semantic_need = "research goal fulfillment"
                fulfilled, reason, missing = self._evaluate_requirement_fulfillment(
                    semantic_topic,
                    semantic_need,
                    plan.get("success_criteria", []),
                    current_facts,
                    semantic_completion_cache,
                )

                if fulfilled:
                    logger.info("[CONTROLLER GATE] all success criteria met -> complete")
                    break

                if recovery_attempts >= max_recovery_attempts:
                    logger.info(
                        "[CONTROLLER GATE] max recovery reached (%d/%d) -> graceful incomplete",
                        recovery_attempts,
                        max_recovery_attempts,
                    )
                    break

                recovery_k = self._resolve_recovery_requirement(
                    reason, current_facts, plan, missing_items=missing, goal=goal
                )
                if not recovery_k:
                    logger.info("[CONTROLLER GATE] no actionable recovery -> graceful incomplete")
                    break

                req_sig = (recovery_k.get("topic"), recovery_k.get("need"))
                if req_sig in attempted_recovery_sigs:
                    logger.info("[CONTROLLER GATE] duplicate recovery rejected -> graceful incomplete")
                    break

                attempted_recovery_sigs.add(req_sig)
                injected_id = self._inject_recovery_requirement(
                    recovery_k, plan, requirement_map, kg, request_scope, goal
                )
                if not injected_id:
                    break

                recovery_attempts += 1
                logger.info("[CONTROLLER RECOVERY] cycle=%d injected=%s", recovery_attempts, injected_id)
                continue

            batch = ready[:self.PARALLEL_NODES]

            log_event(
                "iteration_start",
                {
                    "iteration": iterations_completed + 1,
                    "ready_nodes": len(batch),
                },
            )

            logger.info(f"[orchestrator] iteration {iterations_completed + 1}: {len(batch)} nodes")

            new_evidence_count = 0

            def process_node(node_info):
                nonlocal new_evidence_count
                req_id = node_info["topic"]
                retries = retry_count.get(req_id, 0)
                if retries >= self.MAX_RETRIES:
                    kg.update_status(req_id, NodeExecutionState.FAILED)
                    return 0
                kg.update_status(req_id, NodeExecutionState.SEARCHING)
                kg.increment_search(req_id)
                retry_count[req_id] = retries + 1
                k = requirement_map.get(req_id, {"topic": req_id, "need": "documentation"})
                topic = k["topic"]
                need = k.get("need", "documentation")
                strategy = self._get_strategy(topic, need)

                latency.start("search_api")

                log_event(
                    "search_start",
                    {
                        "topic": topic,
                        "need": need,
                    },
                )

                # User-provided attachment evidence is request-local input.
                # It supplements web evidence; it does not replace the search path.
                attachment_for_req = []
                if attachment_evidence:
                    attachment_for_req = self._validate_evidence_relevance(
                        topic,
                        need,
                        attachment_evidence,
                    )
                    for evidence in attachment_for_req:
                        evidence_copy = {**evidence, "req_id": req_id}
                        all_evidence.append(evidence_copy)
                    logger.info(
                        "[AUDIT ATTACHMENT MATCH] req_id=%s topic=%s accepted=%d",
                        req_id,
                        topic,
                        len(attachment_for_req),
                    )

                    # ATTACHMENT GATE:
                    # User-provided evidence gets one extraction attempt before web search.
                    # If it sufficiently covers the requirement, skip web research.
                    # If insufficient, the existing search path remains unchanged.
                    if attachment_for_req:
                        logger.info(
                            "[AUDIT ATTACHMENT EXTRACTION] req_id=%s topic=%s documents=%d",
                            req_id,
                            topic,
                            len(attachment_for_req),
                        )

                        latency.start("extract")
                        t0 = time.time()

                        checklist = [
                        {
                            "field_id": req_id,
                            "label": f"{topic}: {need}",
                        }
                    ]

                        new_facts, usage = self.facts.extract_facts_batch(
                            attachment_for_req,
                            checklist,
                        )

                        ranked = self.ranker.rank(
                            new_facts,
                            f"{topic} {need}",
                        )
                        ranked = dict(ranked.items())

                        eval_result = self.facts.evaluate(
                            [{"field_id": k, "label": k} for k in ranked.keys()],
                            ranked,
                            attachment_for_req,
                        )

                        profiler.add(
                            "extract",
                            usage,
                            (time.time() - t0) * 1000,
                        )
                        profiler.add_facts("extract", len(ranked))
                        latency.stop("extract")

                        logger.info(
                            "[AUDIT ATTACHMENT COVERAGE] req_id=%s topic=%s "
                            "facts=%d coverage=%.1f%%",
                            req_id,
                            topic,
                            len(ranked),
                            eval_result["coverage_pct"],
                        )

                        if eval_result["coverage_pct"] >= self.MIN_COVERAGE:
                            kg.learn(req_id, ranked, plan)

                            with request_facts_lock:
                                for field, fact in ranked.items():
                                    if isinstance(fact, dict):
                                        request_facts[f"{req_id}/{field}"] = {
                                            "value": fact.get("value"),
                                            "source": fact.get("source", "unknown"),
                                            "source_type": fact.get(
                                                "source_type",
                                                "user_attachment",
                                            ),
                                        }

                            kg.update_status(req_id, "found")

                            logger.info(
                                "[AUDIT ATTACHMENT GATE] req_id=%s "
                                "decision=SUFFICIENT skip_web_search=true",
                                req_id,
                            )

                            return 1

                        logger.info(
                            "[AUDIT ATTACHMENT GATE] req_id=%s "
                            "decision=INSUFFICIENT continue_web_search=true",
                            req_id,
                        )

                # Fase 3: Capability-Aware Scheduler
                # Match requirement (topic + need) -> capability -> compatible provider
                scheduled = self.capability_scheduler.schedule(topic, need)

                if scheduled is None:
                    req_cap = CapabilityResolver.resolve(topic, need)
                    logger.warning(
                        "[AUDIT CAPABILITY MISMATCH] req_id=%s topic=%s need=%s "
                        "required_capability=%s status=BLOCKED no_compatible_provider",
                        req_id,
                        topic,
                        need,
                        req_cap,
                    )
                    kg.update_status(req_id, NodeExecutionState.BLOCKED)
                    return 0

                selected_skill = scheduled

                logger.info(
                    "[AUDIT SKILL SELECT] req_id=%s topic=%s need=%s selected=%s",
                    req_id,
                    topic,
                    need,
                    selected_skill,
                )

                import re

                # Preserve user-provided URLs as direct research evidence.
                # Search results remain unchanged; direct URLs are added
                # to the same existing fetch pipeline.
                all_urls = list(direct_urls)

                if all_urls:
                    logger.info(
                        "[AUDIT DIRECT URL] req_id=%s topic=%s urls=%s",
                        req_id,
                        topic,
                        all_urls,
                    )

                def search_one(q):
                    if selected_skill is None:
                        logger.warning(
                            "[AUDIT SKILL SELECT] req_id=%s topic=%s "
                            "no_skill_selected query=%s",
                            req_id,
                            topic,
                            q,
                        )
                        return []

                    if retries >= 1:
                        logger.info(
                            "[AUDIT AGENT-REACH FALLBACK] req_id=%s "
                            "retry=%d query=%s",
                            req_id,
                            retries,
                            q,
                        )

                    results = self.skill_bridge.execute_selected(
                        selected_skill,
                        q,
                        sources=["searxng"],
                        allow_video=source_policy["allow_video"],
                        allow_social=source_policy["allow_social"],
                    )

                    if not results:
                        logger.warning(
                            "[AUDIT SKILL EXEC] req_id=%s query=%s "
                            "invalid_result=%r",
                            req_id,
                            q,
                            results,
                        )
                        return []

                    # SkillBridge returns an envelope:
                    # {"skill": ..., "result": <executor result>}
                    # Unwrap it before interpreting the search payload.
                    if isinstance(results, dict) and "result" in results:
                        results = results.get("result")

                    if isinstance(results, list):
                        return [
                            item.get("url")
                            for item in results
                            if isinstance(item, dict) and item.get("url")
                        ]

                    if isinstance(results, str):
                        result_text = results

                        import re
                        return re.findall(
                            r'https?://[^\s\n<>"\')\]]+',
                            result_text,
                        )

                    if isinstance(results, dict):
                        result_text = results.get("result", "")

                        if not isinstance(result_text, str):
                            result_text = str(result_text or "")

                        import re
                        return re.findall(
                            r'https?://[^\s\n<>"\')\]]+',
                            result_text,
                        )

                    logger.warning(
                        "[AUDIT SKILL EXEC] req_id=%s query=%s "
                        "unsupported_result=%r",
                        req_id,
                        q,
                        type(results).__name__,
                    )
                    return []
                # Direct user URLs and node target URLs are HARD TARGETS.
                # Fetch the exact target first instead of searching for generic
                # procedures to access the target.
                node_target = k.get("target")
                if node_target:
                    logger.info(
                        "[AUDIT REQ TARGET MODE] req_id=%s topic=%s target=%s",
                        req_id,
                        topic,
                        node_target,
                    )
                    all_urls = [node_target]
                elif direct_urls and not k.get("is_recovery"):
                    logger.info(
                        "[AUDIT DIRECT TARGET MODE] req_id=%s topic=%s urls=%s",
                        req_id,
                        topic,
                        direct_urls,
                    )
                    all_urls = list(direct_urls)
                else:
                    with ThreadPoolExecutor(max_workers=2) as ex:
                        futs = [
                            ex.submit(search_one, q)
                            for q in strategy.get(
                                "search_queries",
                                [f"{topic} {need}"],
                            )[:2]
                        ]
                        for fu in as_completed(futs):
                            all_urls.extend(fu.result())

                # Score, deduplicate and limit URLs
                seen = set()
                unique_urls = []

                for u in all_urls:
                    if u in seen:
                        continue
                    seen.add(u)
                    unique_urls.append(u)

                unique_urls.sort(
                    key=lambda u: self.strategy.score_url(u, strategy),
                    reverse=True,
                )

                logger.info(
                    "[AUDIT CANDIDATES] req_id=%s topic=%s candidates=%d",
                    req_id,
                    topic,
                    len(unique_urls),
                )

                for rank, url in enumerate(unique_urls[:15], 1):
                    logger.info(
                        "[AUDIT CANDIDATE] req_id=%s rank=%d score=%.2f url=%s",
                        req_id,
                        rank,
                        self.strategy.score_url(url, strategy),
                        url,
                    )

                selected_urls = []
                mdn_selected = False

                # Explicit user URLs and node target URLs have absolute priority.
                # They are the exact targets requested and must not
                # be rejected by generic search-result scoring.
                for u in direct_urls:
                    if u in unique_urls and u not in selected_urls:
                        selected_urls.append(u)

                if node_target and node_target in unique_urls and node_target not in selected_urls:
                    selected_urls.append(node_target)

                for u in unique_urls:
                    if u in direct_urls or u == node_target:
                        continue

                    if self.strategy.score_url(u, strategy) < 0.30:
                        continue

                    host = urlparse(u).netloc.lower().split(":")[0]

                    # Keep at most one MDN result.
                    if host == "developer.mozilla.org":
                        if mdn_selected:
                            continue
                        mdn_selected = True

                    selected_urls.append(u)

                    if len(selected_urls) >= 5:
                        break

                all_urls = selected_urls

                latency.stop("search_api")

                log_event(
                    "search_done",
                    {
                        "topic": topic,
                        "urls": len(all_urls),
                    },
                )

                latency.start("fetch")

                # P0-1: URL deduplication remains global for HTTP fetching,
                # but evidence ownership is per requirement.
                #
                # If a URL was already fetched for another requirement,
                # reuse its processed document instead of fetching it again.
                # A separate dict copy receives the current req_id so the
                # requirement can independently consume the evidence.
                existing_by_url = {
                    e.get("url"): e
                    for e in all_evidence
                    if e.get("url")
                }

                # Request-local cache prevents the same direct URL from
                # being fetched repeatedly by multiple planner requirements.
                new_urls = [
                    u for u in all_urls
                    if u not in existing_by_url
                    and u not in request_fetch_cache
                ]

                fetch_errors = {}
                if new_urls:
                    logger.info(
                        "[AUDIT FETCH NEW] req_id=%s topic=%s urls=%s",
                        req_id,
                        topic,
                        new_urls,
                    )

                    fetched_results = self._fetch_url_parallel(
                        new_urls,
                        set(),
                        f"{topic} {need}",
                        errors=fetch_errors,
                    )

                    for fetched in fetched_results:
                        fetched_url = fetched.get("url")
                        if fetched_url:
                            request_fetch_cache[fetched_url] = fetched
                else:
                    fetched_results = []

                fetched_by_url = {
                    r.get("url"): r
                    for r in fetched_results
                    if r.get("url")
                }

                # Include request-local cached evidence.
                fetched_by_url.update(request_fetch_cache)

                evidence_for_req = list(attachment_for_req)

                # Request-level HARD TARGET cache has highest priority.
                # Direct user URLs were preloaded before requirement execution,
                # so requirements must reuse that evidence instead of fetching
                # the same target through the connector again.
                for url in all_urls:
                    if url in request_fetch_cache:
                        evidence = request_fetch_cache[url]
                        evidence_copy = {
                            **evidence,
                            "req_id": req_id,
                        }
                        all_evidence.append(evidence_copy)
                        evidence_for_req.append(evidence_copy)

                        logger.info(
                            "[AUDIT DIRECT EVIDENCE REUSE] req_id=%s topic=%s url=%s",
                            req_id,
                            topic,
                            url,
                        )

                for url in all_urls:
                    if url in request_fetch_cache:
                        continue

                    if url in fetched_by_url:
                        evidence = fetched_by_url[url]
                        evidence_copy = {
                            **evidence,
                            "req_id": req_id,
                        }
                        all_evidence.append(evidence_copy)
                        evidence_for_req.append(evidence_copy)

                    elif url in existing_by_url:
                        # Reuse already fetched/processed evidence.
                        evidence = existing_by_url[url]
                        evidence_copy = {
                            **evidence,
                            "req_id": req_id,
                        }
                        all_evidence.append(evidence_copy)
                        evidence_for_req.append(evidence_copy)

                        logger.info(
                            "[AUDIT EVIDENCE REUSE] req_id=%s topic=%s url=%s",
                            req_id,
                            topic,
                            url,
                        )

                latency.stop("fetch")

                log_event(
                    "fetch_done",
                    {
                        "topic": topic,
                        "urls_requested": len(all_urls),
                        "urls_new": len(new_urls),
                        "documents_fetched": len(fetched_results),
                        "documents_for_requirement": len(evidence_for_req),
                    },
                )

                if evidence_for_req:

                    logger.info(
                        "[AUDIT REQUIREMENT EVIDENCE] req_id=%s topic=%s "
                        "fetched=%d evidence_for_req=%d urls=%s",
                        req_id,
                        topic,
                        len(fetched_results),
                        len(evidence_for_req),
                        [e.get("url") for e in evidence_for_req],
                    )

                    # Apply explicit source constraints before relevance
                    # validation so rejected sources cannot enter validation
                    # cache or fact extraction.
                    evidence_for_req = self._filter_evidence_by_source_policy(
                        evidence_for_req,
                        plan.get("constraints", []),
                    )

                    if not evidence_for_req:
                        logger.warning(
                            "[AUDIT REQUIREMENT EVIDENCE GAP] "
                            "req_id=%s topic=%s reason=source_policy",
                            req_id,
                            topic,
                        )
                        kg.update_status(req_id, "partial")
                        return 0

                    # P0: validate evidence against the CURRENT requirement
                    # before allowing fact extraction.
                    validated_evidence = self._validate_evidence_relevance(
                        topic,
                        need,
                        evidence_for_req,
                    )

                    if not validated_evidence:
                        logger.warning(
                            "[AUDIT REQUIREMENT EVIDENCE GAP] "
                            "req_id=%s topic=%s reason=no_relevant_evidence",
                            req_id,
                            topic,
                        )
                        kg.update_status(req_id, "partial")
                        return 0

                    evidence_for_req = validated_evidence

                    logger.info(
                        "[AUDIT REQUIREMENT EVIDENCE ACCEPTED] "
                        "req_id=%s topic=%s accepted=%d urls=%s",
                        req_id,
                        topic,
                        len(evidence_for_req),
                        [e.get("url") for e in evidence_for_req],
                    )

                    latency.start("extract")

                    log_event(
                        "extract_start",
                        {
                            "topic": topic,
                            "documents": len(evidence_for_req),
                        },
                    )

                    t0 = time.time()
                    checklist = [
                        {
                            "field_id": req_id,
                            "label": f"{topic}: {need}",
                        }
                    ]

                    logger.info("=" * 80)
                    logger.info(
                        "[DEBUG] Before extract_facts_batch req_id=%s",
                        req_id,
                    )

                    for idx, ev in enumerate(evidence_for_req):
                        logger.info(
                            "[EVIDENCE %d]\nURL=%s\nCONTENT=\n%s",
                            idx,
                            ev.get("url"),
                            ev.get("content", "")[:800],
                        )

                    logger.info("=" * 80)

                    new_facts, usage = self.facts.extract_facts_batch(
                        evidence_for_req,
                        checklist,
                    )

                    if not new_facts:
                        logger.warning(
                            "[AUDIT EXTRACTION EMPTY] req_id=%s topic=%s evidence=%d",
                            req_id,
                            topic,
                            len(evidence_for_req),
                        )
                        kg.update_status(req_id, "partial")
                        latency.stop("extract")
                        return 0

                    logger.info(
                        "[EXTRACT RESULT] req_id=%s count=%d",
                        req_id,
                        len(new_facts),
                    )

                    acr_sample = [
                        f for f in new_facts
                        if any(
                            k in str(f).lower()
                            for k in ["acr", "55", "450", "qts", "woofer"]
                        )
                    ]

                    logger.info(
                        "[EXTRACT ACR FACTS] count=%d sample=%s",
                        len(acr_sample),
                        acr_sample[:3],
                    )

                    profiler.add(
                        "extract",
                        usage,
                        (time.time() - t0) * 1000,
                    )

                    ranked = self.ranker.rank(
                        new_facts,
                        f"{topic} {need}",
                    )

                    # PATCH: simpan seluruh fakta hasil ranking.
                    # Jangan dipotong di level node.
                    ranked = dict(ranked.items())

                    logger.info(
                        "[AUDIT RANKED FACTS] req_id=%s topic=%s count=%d fields=%s",
                        req_id,
                        topic,
                        len(ranked),
                        list(ranked.keys()),
                    )

                    profiler.add_facts("extract", len(ranked))

                    eval_result = self.facts.evaluate(
                        [{"field_id": k, "label": k} for k in ranked.keys()],
                        ranked,
                        evidence_for_req,
                    )

                    logger.info(
                        "[AUDIT EVALUATE RAW] req_id=%s filled=%d empty=%d "
                        "coverage=%.1f weighted=%.1f sufficient=%s combined=%.1f "
                        "source_types=%s",
                        req_id,
                        eval_result.get("filled", 0),
                        eval_result.get("empty", 0),
                        eval_result.get("coverage_pct", 0.0),
                        eval_result.get("weighted_score", 0.0),
                        eval_result.get("sufficient", False),
                        eval_result.get("combined_score", 0.0),
                        eval_result.get("source_types", []),
                    )

                    logger.info(
                        "[AUDIT FACT COVERAGE DETAIL] req_id=%s "
                        "ranked=%d coverage=%.1f%% min_required=%.1f "
                        "fields=%s",
                        req_id,
                        len(ranked),
                        eval_result.get("coverage_pct", 0.0),
                        self.MIN_COVERAGE,
                        list(ranked.keys()),
                    )

                    latency.stop("extract")

                    log_event(
                        "extract_done",
                        {
                            "topic": topic,
                            "facts": len(ranked),
                            "coverage": eval_result["coverage_pct"],
                        },
                    )

                    if eval_result["coverage_pct"] >= self.MIN_COVERAGE:
                        kg.learn(req_id, ranked, plan)

                        # Simpan hanya facts hasil extraction run ini.
                        # Historical facts di persistent KG tidak masuk
                        # ke synthesis.
                        with request_facts_lock:
                            for field, fact in ranked.items():
                                if isinstance(fact, dict):
                                    request_facts[f"{req_id}/{field}"] = {
                                        "value": fact.get("value"),
                                        "source": fact.get("source", "unknown"),
                                        "source_type": fact.get("source_type", "other"),
                                    }

                        kg.update_status(req_id, NodeExecutionState.FOUND)
                    else:
                        kg.update_status(req_id, NodeExecutionState.PARTIAL)

                    return 1

                # -----------------------------------------------------------------
                # P5: Explicit failure state when evidence_for_req is empty.
                # Evict dangling 'searching' state based on actual fetch conditions:
                # -----------------------------------------------------------------
                if not all_urls:
                    logger.warning(
                        "[AUDIT REQ FAILURE] req_id=%s topic=%s reason=no_urls status=empty_content",
                        req_id,
                        topic,
                    )
                    kg.update_status(req_id, NodeExecutionState.EMPTY_CONTENT)
                else:
                    err_texts = " ".join(str(v).lower() for v in fetch_errors.values())
                    if any(tok in err_texts for tok in ("timeout", "timed out", "deadline", "timedout")):
                        logger.warning(
                            "[AUDIT REQ FAILURE] req_id=%s topic=%s reason=fetch_timeout status=timeout",
                            req_id,
                            topic,
                        )
                        kg.update_status(req_id, NodeExecutionState.TIMEOUT)
                    elif any(tok in err_texts for tok in ("401", "403", "unauthorized", "forbidden", "auth")):
                        logger.warning(
                            "[AUDIT REQ FAILURE] req_id=%s topic=%s reason=fetch_auth status=auth_failure",
                            req_id,
                            topic,
                        )
                        kg.update_status(req_id, NodeExecutionState.AUTH_FAILURE)
                    elif all(v in ("EMPTY_CONTENT", "NO_RESPONSE") or not str(v).startswith("Error fetch") for v in fetch_errors.values()) and fetch_errors:
                        logger.warning(
                            "[AUDIT REQ FAILURE] req_id=%s topic=%s reason=empty_fetch status=empty_content",
                            req_id,
                            topic,
                        )
                        kg.update_status(req_id, NodeExecutionState.EMPTY_CONTENT)
                    else:
                        logger.warning(
                            "[AUDIT REQ FAILURE] req_id=%s topic=%s reason=fetch_failed status=failed errors=%s",
                            req_id,
                            topic,
                            list(fetch_errors.values())[:3],
                        )
                        kg.update_status(req_id, NodeExecutionState.FAILED)

                return 0

            with ThreadPoolExecutor(max_workers=min(len(batch), self.MAX_WORKERS)) as executor:
                node_futures = [
                    executor.submit(contextvars.copy_context().run, process_node, ni)
                    for ni in batch
                ]
                for future in as_completed(node_futures):
                    new_evidence_count += future.result()

            # FIX: increment SEBELUM early stop check
            iterations_completed += 1

            total_f = self._total_facts(kg, request_scope)
            coverage = self._coverage(kg, request_scope)

            # PROBE ONLY: requirement coverage must be measured separately
            # from KG fact coverage. Do not change termination behavior yet.
            requirement_total = len(requirement_map)
            requirement_found = sum(
                1
                for req_id in requirement_map
                if kg.graph["nodes"].get(req_id, {}).get("status")
                in ("found", "verified")
            )
            requirement_coverage = (
                (requirement_found / requirement_total) * 100
                if requirement_total
                else 100.0
            )

            logger.info(
                "[AUDIT REQUIREMENT COVERAGE LOOP] "
                "found=%d total=%d coverage=%.1f%% facts=%d kg_coverage=%.1f%%",
                requirement_found,
                requirement_total,
                requirement_coverage,
                total_f,
                coverage,
            )
            if total_f >= self.MAX_TOTAL_FACTS:
                retryable = any(
                    not request_requirement_complete(req_id)
                    and retry_count.get(req_id, 0) < self.MAX_RETRIES
                    for req_id in requirement_map
                )

                logger.info(
                    "[AUDIT FACT LIMIT] facts=%d limit=%d retryable_requirements=%s",
                    total_f,
                    self.MAX_TOTAL_FACTS,
                    retryable,
                )

                if not retryable:
                    logger.info(f"[orchestrator] early stop: {total_f} facts")
                    break
            if (
                coverage >= self.EARLY_STOP_COVERAGE
                and total_f >= self.MIN_FACTS_TO_STOP
                and not any(
                    not request_requirement_complete(req_id)
                    and retry_count.get(req_id, 0) < self.MAX_RETRIES
                    for req_id in requirement_map
                )
            ):
                logger.info(f"[orchestrator] early stop: coverage={coverage:.0f}% with {total_f} facts")
                break

            if new_evidence_count == 0 and iterations_completed >= 3:
                logger.info(f"[orchestrator] no new evidence, stopping")
                break

        log_event(
            "iteration_done",
            {
                "iterations": iterations_completed,
                "facts": self._total_facts(kg, request_scope),
                "coverage": self._coverage(kg, request_scope),
            },
        )

        profiler.set_metadata(iterations=iterations_completed)
        pipeline_type = "research" if iterations_completed > 0 else "direct"

        # 4. Build answer
        # Synthesis hanya memakai facts yang dibuat selama research run ini.
        # Persistent KnowledgeGraph tetap menyimpan historical facts.
        all_facts = dict(request_facts)

        _this_request_nodes = set(requirement_map.keys()) | {goal}
        _own = sum(
            1 for k in all_facts
            if k.split("/", 1)[0] in _this_request_nodes
        )

        # AUDIT ONLY: ukur coverage requirement berdasarkan evidence dan facts
        # current request. Belum mengubah keputusan synthesis.
        requirement_audit = []

        for req_id, req in requirement_map.items():
            node = kg.graph["nodes"].get(req_id, {})
            facts = node.get("facts", [])
            status = node.get("status")

            evidence_count = sum(
                1 for e in all_evidence
                if e.get("req_id") == req_id
            )

            requirement_audit.append({
                "req_id": req_id,
                "topic": req.get("topic", req_id) if isinstance(req, dict) else str(req),
                "status": status,
                "evidence": evidence_count,
                "facts": len(facts),
            })

        with_evidence = sum(
            1 for r in requirement_audit if r["evidence"] > 0
        )
        with_facts = sum(
            1 for r in requirement_audit if r["facts"] > 0
        )
        # Semantic completeness is evaluated at research-goal level.
        # success_criteria belongs to the complete plan, so it must be
        # evaluated against all facts collected for this request rather
        # than against each individual requirement node.
        semantic_topic = plan.get("goal", goal)
        semantic_need = "research goal fulfillment"

        semantic_fulfilled, semantic_reason, semantic_missing = (
            self._evaluate_requirement_fulfillment(
                semantic_topic,
                semantic_need,
                plan.get("success_criteria", []),
                all_facts,
                semantic_completion_cache,
            )
        )

        missing = [] if semantic_fulfilled else requirement_audit

        for r in requirement_audit:
            r["semantic_fulfilled"] = semantic_fulfilled
            r["semantic_reason"] = semantic_reason
            r["semantic_missing"] = semantic_missing

        logger.info(
            "[AUDIT REQUIREMENT COVERAGE] total=%d with_evidence=%d "
            "with_facts=%d missing=%d",
            len(requirement_audit),
            with_evidence,
            with_facts,
            len(missing),
        )

        for r in missing:
            logger.info(
                "[AUDIT REQUIREMENT MISSING] req_id=%s topic=%s "
                "status=%s evidence=%d facts=%d",
                r["req_id"],
                r["topic"],
                r["status"],
                r["evidence"],
                r["facts"],
            )

        research_incomplete = bool(missing)

        logger.info(
            "[AUDIT RESEARCH COMPLETENESS] complete=%s missing=%d",
            not research_incomplete,
            len(missing),
        )

        logger.info(
            "[AUDIT SYNTHESIS] total_all_facts=%d own_request_facts=%d foreign_facts=%d "
            "nodes_this_request=%d nodes_total_in_kg=%d",
            len(all_facts), _own, len(all_facts) - _own,
            len(_this_request_nodes), len(kg.graph["nodes"]),
        )

        # PATCH 6: fail-closed on zero extracted facts. Proven live on two
        # independent traces that the synthesis LLM fabricates a complete
        # answer (fake prices, fake sources not present anywhere in the
        # evidence) even when EXTRACTED FACTS is explicitly {} and the
        # prompt already forbids fabrication -- prompt-only enforcement is
        # not enough. Skip the synthesis LLM call entirely in this case and
        # return a deterministic incomplete-status answer built only from
        # requirement_audit/missing (already computed above), so there is
        # no LLM in the loop that could hallucinate when there is nothing
        # to synthesize from.
        if not all_facts:
            logger.warning(
                "[SYNTHESIS SKIP] zero facts extracted -- returning incomplete "
                "status without calling the synthesis LLM"
            )
            missing_topics = [r["topic"] for r in missing] or [
                r["topic"] for r in requirement_audit
            ]
            if missing_topics:
                answer = (
                    "Riset tidak dapat diselesaikan: tidak ada fakta terverifikasi "
                    "yang berhasil diekstrak dari sumber yang ditemukan.\n\n"
                    "Requirement yang belum terpenuhi:\n"
                    + "\n".join(f"- {t}" for t in missing_topics)
                )
            else:
                answer = (
                    "Riset tidak dapat diselesaikan: tidak ada fakta terverifikasi "
                    "yang berhasil diekstrak dari sumber yang ditemukan."
                )

            kg.save()

            log_event(
                "research_done",
                {
                    "goal": goal,
                    "pipeline": pipeline_type,
                    "iterations": iterations_completed,
                    "facts": 0,
                    "duration_ms": (time.time() - t0_total) * 1000,
                },
            )

            return {
                "goal": goal, "answer": answer,
                "facts_count": 0, "iterations": iterations_completed,
                "pipeline": pipeline_type, "graph_stats": kg.get_stats(),
                "token_profile": profiler.summary(), "latency_profile": latency.summary(),
                "api_cost": profiler.total_cost, "duration_ms": (time.time() - t0_total) * 1000,
            }

        # Facts already carry the primary evidence.  Keep a compact raw
        # excerpt only from sources that actually produced facts, so the
        # synthesis prompt is not inflated by duplicate search results.
        synthesis_evidence = [e for e in all_evidence if e.get("had_facts")]
        if not synthesis_evidence:
            synthesis_evidence = [
                {**e, "content": "[content withheld: no verified facts extracted from this source]"}
                for e in all_evidence
            ]
        evidence_text = "\n\n".join([
            f"[{e.get('doc_type','?')}] {e['url']}\n{e['content'][:400]}"
            for e in synthesis_evidence[:4]
        ])
        compact_facts = json.dumps(
            all_facts,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        logger.info(
            "[TOKEN OPTIMIZATION] synthesis facts_chars=%d evidence_sources=%d evidence_chars=%d",
            len(compact_facts),
            min(len(synthesis_evidence), 4),
            len(evidence_text),
        )

        completeness_context = (
            "RESEARCH STATUS: COMPLETE. "
            "All planned requirements have evidence and facts."
            if not research_incomplete
            else
            "RESEARCH STATUS: INCOMPLETE. "
            "One or more planned requirements lack sufficient evidence or facts. "
            "STRICT RULES: Do not present the research as complete. "
            "Explicitly report the missing requirements. "
            "Do not fabricate values. "
            "Do not make technical recommendations that depend on missing evidence. "
            "Do not introduce technical claims or inferences absent from EXTRACTED FACTS "
            "or SOURCE MATERIAL. "
            "Do not recommend an alternative that contradicts the user's requested "
            "configuration merely because the requested configuration is insufficiently researched. "
            "If the requested configuration cannot yet be determined safely from the available "
            "evidence, say so and identify the missing evidence."
        )

        # Stage 7 — Output Scaling.
        #
        # Research/evidence collection above remains unchanged.
        # The previous single synthesis LLM call is replaced by
        # deterministic section decomposition + execution + aggregation.
        manifest = self.manifest_builder.build(plan, goal=goal)
        scheduler = SectionScheduler(manifest)
        store = SectionStore()

        # Store owns execution/output state; scheduler owns lifecycle.
        for section in manifest.sections:
            store.create(section.section_id)

        engine = ContinuationEngine(
            worker=self.section_worker,
            store=store,
            outcome_classifier=self.outcome_classifier,
            coverage_evaluator=self.coverage_evaluator,
            continuation_policy=self.continuation_policy,
        )

        scheduler.initialize()

        section_context = {
            "all_facts": all_facts,
            "synthesis_evidence": synthesis_evidence,
            "completeness_context": completeness_context,
            "memory_context": memory_context,
            "requirement_audit": requirement_audit,
        }

        latency.start("output_scaling")

        while True:
            ready_sections = scheduler.ready_sections()

            if not ready_sections:
                break

            for section in ready_sections:
                scheduler.mark_in_flight(section.section_id)

                # Explicit scheduler -> store lifecycle synchronization.
                store_state = store.get(section.section_id)
                store_state.status = SectionStatus.IN_FLIGHT
                store.put(store_state)

                while True:
                    step = engine.step(
                        section,
                        goal=goal,
                        facts=all_facts,
                        evidence=synthesis_evidence,
                        context=section_context,
                        requirement_audit=requirement_audit,
                        memory=memory_context,
                        temperature=0.3,
                        max_tokens=section.budget_hint,
                    )

                    decision = step.policy.decision

                    if decision.value == "CONTINUE":
                        continue

                    store_state = store.get(section.section_id)

                    if decision.value == "FINALIZE":
                        scheduler.mark_complete(section.section_id)
                        store_state.status = SectionStatus.STORED_FINAL

                    elif decision.value == "DEGRADE":
                        scheduler.mark_degraded(section.section_id)
                        store_state.status = SectionStatus.DEGRADED

                    elif decision.value == "FAIL":
                        scheduler.mark_failed(section.section_id)
                        store_state.status = SectionStatus.FAILED

                    elif decision.value == "SPLIT":
                        # ------------------------------------------------
                        # In-section composite split.
                        #
                        # Children are execution units only.
                        # They are NOT inserted into the manifest or
                        # SectionScheduler.
                        #
                        # Their output is reconciled into the existing
                        # parent section state.
                        # ------------------------------------------------

                        remaining_items = list(
                            step.coverage.remaining_items
                            if step.coverage is not None
                            else store_state.remaining_items
                        )

                        children = self.section_splitter.partition(
                            section,
                            remaining_items,
                        )

                        if not children:
                            logger.warning(
                                "[OUTPUT SCALING] SPLIT produced no "
                                "children section=%s remaining=%s",
                                section.section_id,
                                remaining_items,
                            )

                            scheduler.mark_degraded(
                                section.section_id
                            )
                            store_state.status = (
                                SectionStatus.DEGRADED
                            )
                            store.put(store_state)
                            continue

                        child_results = []

                        for child in children:
                            try:
                                child_result = self.section_worker.execute(
                                    child.section,
                                    goal=goal,
                                    context=section_context,
                                    temperature=0.3,
                                    max_tokens=(
                                        child.section.budget_hint
                                    ),
                                )

                                content = child_result.get(
                                    "content",
                                    "",
                                )

                                tokens_output = int(
                                    child_result.get(
                                        "tokens_output",
                                        0,
                                    )
                                    or 0
                                )

                                child_results.append(
                                    {
                                        "child_section_id": (
                                            child.child_section_id
                                        ),
                                        "content": content,
                                        "tokens_output": (
                                            tokens_output
                                        ),
                                        "status": (
                                            SectionStatus.STORED_FINAL
                                        ),
                                        "covered_items": list(
                                            child.section.must_cover
                                        ),
                                    }
                                )

                                logger.info(
                                    "[OUTPUT SCALING] split child "
                                    "complete parent=%s child=%s "
                                    "tokens=%s",
                                    section.section_id,
                                    child.child_section_id,
                                    tokens_output,
                                )

                            except Exception as exc:
                                logger.warning(
                                    "[OUTPUT SCALING] child split "
                                    "execution failed parent=%s "
                                    "child=%s error=%s",
                                    section.section_id,
                                    child.child_section_id,
                                    exc,
                                )

                                child_results.append(
                                    {
                                        "child_section_id": (
                                            child.child_section_id
                                        ),
                                        "content": "",
                                        "tokens_output": 0,
                                        "status": (
                                            SectionStatus.FAILED
                                        ),
                                        "covered_items": [],
                                    }
                                )

                        reconciled = self.section_splitter.reconcile(
                            parent_section_id=section.section_id,
                            child_results=child_results,
                            remaining_items=remaining_items,
                        )

                        parent_state = store.get(
                            section.section_id
                        )

                        existing_text = (
                            parent_state.accumulated_text.strip()
                        )

                        child_text = (
                            reconciled[
                                "accumulated_text"
                            ].strip()
                        )

                        if existing_text and child_text:
                            parent_state.accumulated_text = (
                                f"{existing_text}\n\n{child_text}"
                            )
                        elif child_text:
                            parent_state.accumulated_text = (
                                child_text
                            )

                        if child_text:
                            parent_state.chunks.append(
                                child_text
                            )

                        child_tokens = int(
                            reconciled[
                                "tokens_output"
                            ]
                            or 0
                        )

                        parent_state.budget_used_tokens += (
                            child_tokens
                        )

                        parent_state.last_tokens_output = (
                            child_tokens
                        )

                        parent_state.last_outcome = (
                            step.outcome
                        )

                        coverage = (
                            self.coverage_evaluator.evaluate(
                                section,
                                parent_state.accumulated_text,
                                facts=all_facts,
                            )
                        )

                        parent_state.covered_items = list(
                            coverage.covered_items
                        )

                        parent_state.remaining_items = list(
                            coverage.remaining_items
                        )

                        if coverage.semantic_complete is True:
                            scheduler.mark_complete(
                                section.section_id
                            )

                            parent_state.status = (
                                SectionStatus.STORED_FINAL
                            )

                            logger.info(
                                "[OUTPUT SCALING] SPLIT "
                                "reconciled FINAL section=%s "
                                "covered=%s",
                                section.section_id,
                                parent_state.covered_items,
                            )
                        else:
                            scheduler.mark_degraded(
                                section.section_id
                            )

                            parent_state.status = (
                                SectionStatus.DEGRADED
                            )

                            logger.warning(
                                "[OUTPUT SCALING] SPLIT "
                                "reconciled DEGRADED section=%s "
                                "remaining=%s",
                                section.section_id,
                                parent_state.remaining_items,
                            )

                        store.put(parent_state)

                    else:
                        logger.error(
                            "[OUTPUT SCALING] unsupported decision=%s section=%s",
                            decision.value,
                            section.section_id,
                        )
                        scheduler.mark_failed(section.section_id)
                        store_state.status = SectionStatus.FAILED

                    if decision.value != "SPLIT":
                        store.put(store_state)
                    break

        aggregated = self.output_aggregator.aggregate(manifest, store)

        latency.stop("output_scaling")

        # Preserve the existing downstream result/profiler contract while
        # making the aggregated output the authoritative answer content.
        llm_result = {
            "content": aggregated.content,
            "model": "output_scaling",
            "requested_model": "output_scaling",
            "finish_reason": None,
            "tokens_input": 0,
            "tokens_output": aggregated.total_tokens_used,
            "api_cost": 0,
        }

        profiler.add("output_scaling", llm_result)
        profiler.add_facts("output_scaling", len(all_facts))

        logger.info(
            "[OUTPUT SCALING] manifest=%s sections=%d final=%d degraded=%d "
            "failed=%d tokens=%d status=%s",
            manifest.manifest_id,
            aggregated.sections_total,
            aggregated.sections_final,
            aggregated.sections_degraded,
            aggregated.sections_failed,
            aggregated.total_tokens_used,
            aggregated.scaler_status.value,
        )

        kg.save()

        log_event(
            "research_done",
            {
                "goal": goal,
                "pipeline": pipeline_type,
                "iterations": iterations_completed,
                "facts": len(all_facts),
                "duration_ms": (time.time() - t0_total) * 1000,
            },
        )

        return {
            "goal": goal, "answer": llm_result["content"],
            "facts_count": len(all_facts), "iterations": iterations_completed,
            "pipeline": pipeline_type, "graph_stats": kg.get_stats(),
            "token_profile": profiler.summary(), "latency_profile": latency.summary(),
            "api_cost": profiler.total_cost, "duration_ms": (time.time() - t0_total) * 1000,
        }
