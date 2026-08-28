import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


class SkillRouter:
    """
    Discovers external skills from ~/.agents/skills.

    This layer only discovers and matches capabilities.
    It does not execute skills.
    """

    def __init__(self, skills_dir=None):
        self.skills_dir = Path(
            skills_dir or Path.home() / ".agents" / "skills"
        )
        self.skills = self._discover()

    def _discover(self):
        skills = []

        if not self.skills_dir.exists():
            logger.info("[skill-router] skills dir not found: %s", self.skills_dir)
            return skills

        for skill_file in sorted(self.skills_dir.glob("*/SKILL.md")):
            try:
                skill = self._load(skill_file)
                if skill:
                    skills.append(skill)
            except Exception:
                logger.exception(
                    "[skill-router] failed loading %s", skill_file
                )

        logger.info(
            "[skill-router] discovered=%d dir=%s",
            len(skills),
            self.skills_dir,
        )
        return skills

    @staticmethod
    def _load(path):
        text = path.read_text(encoding="utf-8")

        if not text.startswith("---"):
            return None

        parts = text.split("---", 2)
        if len(parts) < 3:
            return None

        metadata = yaml.safe_load(parts[1]) or {}

        name = metadata.get("name")
        description = metadata.get("description", "")

        if not name:
            return None

        return {
            "name": name,
            "description": description.strip() if isinstance(description, str) else str(description),
            "path": str(path),
        }

    def list_skills(self):
        return list(self.skills)

    def match(self, query):
        """
        Match external skills only when the query explicitly requires
        internet/platform access.

        General knowledge questions must not activate agent-reach.
        """
        query = (query or "").lower().strip()

        if not query:
            return []

        internet_terms = {
            "cari", "search", "telusuri", "riset", "research",
            "lookup", "temukan", "lihat", "cek", "periksa",
            "internet", "online", "web", "website", "url",
            "github", "twitter", "x.com", "reddit",
            "youtube", "facebook", "instagram", "bilibili",
            "linkedin", "v2ex", "rss",
        }

        platform_terms = {
            "repository", "repo", "tweet", "postingan",
            "video", "channel", "subreddit", "thread",
            "website", "artikel", "lowongan",
        }

        words = {
            word.strip(".,:;!?()[]{}\"'`")
            for word in query.split()
        }

        intent_hits = (
            words & internet_terms
        ) | (
            words & platform_terms
        )

        if not intent_hits:
            return []

        matches = []

        for skill in self.skills:
            haystack = (
                skill["name"] + " " + skill["description"]
            ).lower()

            score = sum(
                1 for word in intent_hits
                if word in haystack
            )

            if score:
                matches.append({
                    **skill,
                    "score": score,
                })

        matches.sort(
            key=lambda item: item["score"],
            reverse=True,
        )

        return matches

    def _agent_reach_route(self, query):
        """
        Route Agent Reach requests to the reference category that best
        matches the explicit internet/platform intent.

        This is routing only; execution remains outside SkillRouter.
        """
        query = (query or "").lower().strip()

        if not query:
            return None

        routes = [
            (
                "dev",
                "references/dev.md",
                {
                    "github", "repository", "repo", "issue", "issues",
                    "pull", "request", "pull-request", "code",
                },
            ),
            (
                "video",
                "references/video.md",
                {
                    "youtube", "video", "subtitle", "transkrip",
                    "transcribe", "bilibili",
                },
            ),
            (
                "social",
                "references/social.md",
                {
                    "twitter", "x.com", "tweet", "reddit", "subreddit",
                    "facebook", "instagram", "linkedin", "v2ex",
                    "xiaohongshu", "bilibili", "sosmed", "medsos",
                },
            ),
            (
                "search",
                "references/search.md",
                {
                    "search", "cari", "telusuri", "riset", "research",
                    "internet", "web", "online", "exa",
                },
            ),
            (
                "web",
                "references/web.md",
                {
                    "url", "website", "artikel", "article", "halaman",
                    "webpage", "link",
                },
            ),
            (
                "career",
                "references/career.md",
                {
                    "linkedin", "lowongan", "pekerjaan", "job", "career",
                },
            ),
            (
                "finance",
                "references/finance.md",
                {
                    "saham", "stock", "stocks", "harga", "market",
                    "finance", "finansial",
                },
            ),
        ]

        words = {
            word.strip(".,:;!?()[]{}\"'`")
            for word in query.split()
        }

        best = None

        for category, reference, terms in routes:
            hits = words & terms

            if not hits:
                continue

            score = len(hits)

            candidate = {
                "category": category,
                "reference": reference,
                "score": score,
            }

            if best is None or candidate["score"] > best["score"]:
                best = candidate

        return best

    def select(self, query, min_score=1):
        """
        Select the best matching capability.

        Agent Reach gets an additional category/reference route based on
        upstream SKILL_en.md. Existing skill matching remains unchanged.
        """
        matches = self.match(query)

        best = matches[0] if matches else None
        route = self._agent_reach_route(query)

        if best and best["score"] >= min_score:
            selected = dict(best)
        elif route:
            selected = {
                "name": "agent-reach",
                "description": "Agent Reach internet capability router",
                "path": str(
                    self.skills_dir / "agent-reach" / "SKILL.md"
                ),
                "score": route["score"],
            }
        else:
            return None

        if route and selected["name"] == "agent-reach":
            selected["category"] = route["category"]
            selected["reference"] = route["reference"]

        return selected
