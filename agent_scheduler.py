from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional
import uuid

from llm_client import LLMClient
from pawpal_system import Constraint, Owner, PetCareTask, Preference, Schedule, Scheduler


@dataclass
class AgentScheduleResult:
    schedule: Schedule
    rationale: str
    used_llm: bool
    trace_id: str
    iterations: int


class SchedulingAgent:
    """Agentic wrapper around the deterministic scheduler.

    The flow is: baseline schedule -> optional LLM reordering -> score and keep best.
    If LLM is unavailable or fails, the baseline deterministic schedule is returned.
    """

    def __init__(
        self,
        scheduler: Optional[Scheduler] = None,
        llm_client: Optional[LLMClient] = None,
        max_iterations: int = 2,
    ) -> None:
        self.scheduler = scheduler or Scheduler()
        self.llm_client = llm_client or LLMClient()
        self.max_iterations = max(1, max_iterations)

    def schedule_for_owner(
        self,
        owner: Owner,
        preferences: Optional[List[Preference]] = None,
        constraints: Optional[List[Constraint]] = None,
    ) -> AgentScheduleResult:
        trace_id = str(uuid.uuid4())
        pending = owner.get_all_tasks(include_completed=False)
        if not pending:
            return AgentScheduleResult(
                schedule=Schedule(date=datetime.today().date(), time_slots=[]),
                rationale="No pending tasks available for scheduling.",
                used_llm=False,
                trace_id=trace_id,
                iterations=0,
            )

        working_baseline = deepcopy(pending)
        baseline = self.scheduler.schedule_tasks(working_baseline, preferences=preferences, constraints=constraints)
        best_schedule = baseline
        best_score = self._score_schedule(baseline, working_baseline)
        rationale_lines = [
            "Baseline schedule created by deterministic priority and duration logic.",
            f"trace_id={trace_id}",
        ]

        if not self.llm_client.enabled():
            self._apply_schedule_to_owner(owner, baseline)
            rationale_lines.append("LLM not configured; using deterministic fallback schedule.")
            return AgentScheduleResult(
                schedule=baseline,
                rationale="\n".join(rationale_lines),
                used_llm=False,
                trace_id=trace_id,
                iterations=0,
            )

        used_llm = False
        explicit_times = {t.id: t.scheduled_time for t in pending if t.scheduled_time is not None}

        for i in range(1, self.max_iterations + 1):
            try:
                proposal = self.llm_client.propose_task_order(working_baseline, best_schedule)
                reordered = self._build_reordered_tasks(pending, proposal.get("ordered_task_ids", []), explicit_times)
                candidate = self.scheduler.schedule_tasks(
                    reordered,
                    preferences=preferences,
                    constraints=constraints,
                    preserve_order=True,
                )
                candidate_score = self._score_schedule(candidate, reordered)
                used_llm = True

                llm_rationale = proposal.get("rationale", "").strip()
                if llm_rationale:
                    rationale_lines.append(f"Iteration {i}: {llm_rationale}")
                rationale_lines.append(
                    f"Iteration {i} score: {candidate_score} (best so far: {best_score})"
                )

                if candidate_score >= best_score:
                    best_schedule = candidate
                    best_score = candidate_score
                    working_baseline = reordered
            except Exception as exc:
                rationale_lines.append(f"Iteration {i} skipped due to LLM error: {exc}")

        self._apply_schedule_to_owner(owner, best_schedule)
        return AgentScheduleResult(
            schedule=best_schedule,
            rationale="\n".join(rationale_lines),
            used_llm=used_llm,
            trace_id=trace_id,
            iterations=self.max_iterations if used_llm else 0,
        )

    def _build_reordered_tasks(
        self,
        original_tasks: List[PetCareTask],
        ordered_task_ids: List[str],
        explicit_times: Dict[str, datetime],
    ) -> List[PetCareTask]:
        tasks_by_id = {t.id: deepcopy(t) for t in original_tasks}
        ordered: List[PetCareTask] = []

        for task_id in ordered_task_ids:
            task = tasks_by_id.get(task_id)
            if task is None:
                continue
            if task.scheduled_time is None:
                task.scheduled_time = explicit_times.get(task.id)
            ordered.append(task)

        for task in tasks_by_id.values():
            if task.id not in {t.id for t in ordered}:
                if task.scheduled_time is None:
                    task.scheduled_time = explicit_times.get(task.id)
                ordered.append(task)

        return ordered

    def _score_schedule(self, schedule: Schedule, tasks: List[PetCareTask]) -> int:
        scheduled_task_ids = {slot.task_id for slot in schedule.time_slots if slot.task_id}
        unscheduled = [t for t in tasks if t.id not in scheduled_task_ids and not t.completed]
        unscheduled_high = [t for t in unscheduled if t.priority.name == "HIGH"]

        return (
            (len(schedule.time_slots) * 3)
            - (len(schedule.warnings) * 5)
            - (len(unscheduled_high) * 4)
            - len(unscheduled)
        )

    def _apply_schedule_to_owner(self, owner: Owner, schedule: Schedule) -> None:
        pending = owner.get_all_tasks(include_completed=False)
        for t in pending:
            if t.scheduled_time is not None:
                t.scheduled_time = None

        slot_by_task_id = {slot.task_id: slot for slot in schedule.time_slots if slot.task_id}
        for t in pending:
            slot = slot_by_task_id.get(t.id)
            if slot:
                t.scheduled_time = slot.start_time
