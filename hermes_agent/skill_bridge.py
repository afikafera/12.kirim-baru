import logging

logger = logging.getLogger(__name__)


class SkillBridge:
    """
    Bridge antara Hermes capability selection dan skill/tool executors.

    Tidak mengubah orchestrator.
    Tidak mengubah SkillRouter.
    Executor didaftarkan dari luar.
    """

    def __init__(self, skill_router):
        self.skill_router = skill_router
        self._executors = {}

    def register(self, skill_name, executor):
        if not callable(executor):
            raise TypeError(f"executor for {skill_name!r} must be callable")

        self._executors[skill_name] = executor

    def resolve(self, query):
        selected = self.skill_router.select(query)

        if not selected:
            return None

        skill_name = selected["name"]
        executor = self._executors.get(skill_name)

        return {
            "skill": selected,
            "executor": executor,
            "executable": executor is not None,
        }

    def execute_skill(self, skill_name, query, **kwargs):
        """
        Execute an explicitly selected skill.

        Digunakan core setelah capability sudah dipilih.
        Tidak melakukan routing ulang terhadap query internal.
        """
        executor = self._executors.get(skill_name)

        if executor is None:
            raise RuntimeError(
                f"Skill {skill_name!r} selected "
                "but no executor is registered"
            )

        return executor(query, **kwargs)

    def execute_selected(self, selected_skill, query, **kwargs):
        """
        Execute a capability already selected by the core.

        Tidak melakukan routing ulang terhadap query internal.
        Core menentukan capability; bridge hanya mencari executor
        yang terdaftar dan menjalankannya.
        """
        if not selected_skill:
            return None

        skill_name = selected_skill["name"]
        executor = self._executors.get(skill_name)

        logger.info(
            "[AUDIT SKILL EXEC] skill=%s category=%s reference=%s "
            "executable=%s query=%r kwargs=%s",
            skill_name,
            selected_skill.get("category"),
            selected_skill.get("reference"),
            executor is not None,
            query,
            sorted(kwargs.keys()),
        )

        if executor is None:
            raise RuntimeError(
                f"Skill {skill_name!r} selected "
                "but no executor is registered"
            )

        result = executor(query, **kwargs)

        logger.info(
            "[AUDIT SKILL EXEC RESULT] skill=%s result_type=%s result_len=%d",
            skill_name,
            type(result).__name__,
            len(result) if hasattr(result, "__len__") else -1,
        )

        return {
            "skill": selected_skill,
            "result": result,
        }

    def execute(self, query, **kwargs):
        resolved = self.resolve(query)

        if not resolved:
            return None

        return self.execute_selected(
            resolved["skill"],
            query,
            **kwargs,
        )
