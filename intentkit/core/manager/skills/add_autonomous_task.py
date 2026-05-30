from typing import Any, override

from langchain_core.tools import ArgsSchema
from pydantic import BaseModel, Field

from intentkit.core.autonomous import add_autonomous_task
from intentkit.core.manager.skills.base import ManagerSkill
from intentkit.models.agent import AgentAutonomous
from intentkit.models.agent.autonomous import AutonomousCreateRequest


class AddAutonomousTaskInput(AutonomousCreateRequest):
    """Input model for add_autonomous_task skill."""

    pass


class AddAutonomousTaskOutput(BaseModel):
    """Output model for add_autonomous_task skill."""

    task: AgentAutonomous = Field(description="The created autonomous task configuration")


class AddAutonomousTask(ManagerSkill):
    """Skill to add a new autonomous task to an agent."""

    name: str = "system_add_autonomous_task"
    description: str = (
        "Add a new autonomous task configuration to the agent. "
        "Allows setting up either scheduled operations with cron or Xian "
        "event-triggered operations. "
        "For Xian event triggers, provide trigger_type='xian_event' and "
        "xian_event={contract,event,filters?,cooldown_seconds?}. "
        "If the user wants a periodic condition check instead of an event "
        "trigger, add a 5 minute cron task to check the condition. "
    )
    args_schema: ArgsSchema | None = AddAutonomousTaskInput

    @override
    async def _arun(
        self,
        prompt: str,
        cron: str | None = None,
        name: str | None = None,
        description: str | None = None,
        enabled: bool = True,
        has_memory: bool = False,
        **kwargs: Any,
    ) -> AddAutonomousTaskOutput:
        """Add an autonomous task to the agent.

        Args:
            cron: Cron expression
            prompt: Special prompt for autonomous operation
            name: Display name of the task
            description: Description of the task
            enabled: Whether the task is enabled
            has_memory: Whether to retain memory between runs
            config: Runtime configuration containing agent context

        Returns:
            AddAutonomousTaskOutput: The created task
        """
        context = self.get_context()
        agent = context.agent

        task_request = AutonomousCreateRequest(
            name=name,
            description=description,
            cron=cron,
            trigger_type=kwargs.get("trigger_type"),
            xian_event=kwargs.get("xian_event"),
            prompt=prompt,
            enabled=enabled,
            has_memory=has_memory,
        )

        created_task = await add_autonomous_task(agent.id, task_request)

        return AddAutonomousTaskOutput(task=created_task)


# Shared skill instances
add_autonomous_task_skill = AddAutonomousTask()
