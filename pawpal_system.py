from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta, time
from enum import Enum
from typing import List, Optional, Dict, Any
import uuid


MAX_TASKS_PER_RUN = 200


def _new_id() -> str:
    return str(uuid.uuid4())


class Priority(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class TimeWindow:
    start: datetime
    end: datetime


@dataclass
class Constraint:
    id: str = field(default_factory=_new_id)
    constraint_type: str = ""  # e.g. "time_budget", "unavailable_window", "must_after"
    parameters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Preference:
    id: str = field(default_factory=_new_id)
    applies_to: str = "owner"  # "owner" or "pet"
    entity_id: Optional[str] = None
    preferred_time_windows: List[TimeWindow] = field(default_factory=list)
    max_daily_time_minutes: Optional[int] = None


@dataclass
class PetCareTask:
    id: str = field(default_factory=_new_id)
    title: str = ""
    duration_minutes: int = 0
    priority: Priority = Priority.MEDIUM
    pet_id: Optional[str] = None
    notes: Optional[str] = None
    scheduled_time: Optional[datetime] = None
    frequency: Optional[str] = None  # free-form (e.g., "daily", "weekly")
    completed: bool = False

    def __post_init__(self) -> None:
        self.title = self.title.strip()
        if not self.title:
            raise ValueError("Task title cannot be empty")
        if self.duration_minutes <= 0:
            raise ValueError("Task duration must be greater than 0 minutes")
        if self.duration_minutes > 24 * 60:
            raise ValueError("Task duration cannot exceed 1440 minutes")

    def is_high_priority(self) -> bool:
        """Return True when this task has high priority."""
        return self.priority == Priority.HIGH

    def mark_completed(self) -> None:
        """Mark the task as completed."""
        self.completed = True

    def is_pending(self) -> bool:
        """Return True when the task has not been completed yet."""
        return not self.completed


@dataclass
class TimeSlot:
    start_time: datetime
    end_time: datetime
    task_id: Optional[str] = None
    status: str = "planned"  # "planned" | "completed" | "skipped"


@dataclass
class Schedule:
    date: date
    time_slots: List[TimeSlot] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def generate(self) -> "Schedule":
        raise NotImplementedError()

    def explain(self) -> str:
        raise NotImplementedError()


@dataclass
class Pet:
    id: str = field(default_factory=_new_id)
    name: str = ""
    species: Optional[str] = None
    age: Optional[int] = None
    owner_id: Optional[str] = None
    tasks: List[PetCareTask] = field(default_factory=list)

    def add_task(self, task: PetCareTask) -> None:
        """Attach a PetCareTask to this pet."""
        task.pet_id = self.id
        self.tasks.append(task)

    def remove_task(self, task_id: str) -> None:
        """Remove a task from this pet by id."""
        self.tasks = [t for t in self.tasks if t.id != task_id]

    def get_tasks(self, include_completed: bool = False) -> List[PetCareTask]:
        """Return this pet's tasks; optionally include completed ones."""
        if include_completed:
            return list(self.tasks)
        return [t for t in self.tasks if not t.completed]

    def complete_task(self, task_id: str) -> Optional[PetCareTask]:
        """Mark a task as completed. If the task is recurring ('daily' or 'weekly'),
        create and append the next occurrence and return it; otherwise return None.
        """
        for t in self.tasks:
            if t.id == task_id:
                t.mark_completed()
                freq = (t.frequency or "").lower()
                if freq in ("daily", "weekly"):
                    # compute next scheduled_time using timedelta
                    offset = timedelta(days=1) if freq == "daily" else timedelta(weeks=1)
                    if t.scheduled_time:
                        next_time = t.scheduled_time + offset
                    else:
                        next_time = datetime.now() + offset
                    new_task = PetCareTask(
                        title=t.title,
                        duration_minutes=t.duration_minutes,
                        priority=t.priority,
                        pet_id=self.id,
                        notes=t.notes,
                        frequency=t.frequency,
                        scheduled_time=next_time,
                    )
                    self.tasks.append(new_task)
                    return new_task
                return None
        return None


@dataclass
class Owner:
    id: str = field(default_factory=_new_id)
    name: str = ""
    contact_info: Optional[str] = None
    preferences: List[Preference] = field(default_factory=list)
    pets: List[Pet] = field(default_factory=list)

    def add_pet(self, pet: Pet) -> None:
        """Add a Pet to this owner and set ownership."""
        pet.owner_id = self.id
        self.pets.append(pet)

    def remove_pet(self, pet_id: str) -> None:
        """Remove a Pet from this owner by id."""
        self.pets = [p for p in self.pets if p.id != pet_id]

    def get_all_pets(self) -> List[Pet]:
        """Return a list of this owner's pets."""
        return list(self.pets)

    def get_all_tasks(self, include_completed: bool = False) -> List[PetCareTask]:
        """Aggregate tasks from all pets owned by this owner."""
        tasks: List[PetCareTask] = []
        for p in self.pets:
            tasks.extend(p.get_tasks(include_completed=include_completed))
        return tasks


class Scheduler:
    @staticmethod
    def _infer_task_type(task_title: str) -> str:
        """Infer task type from title (walk, feeding, play, grooming, vet, training)."""
        title_lower = task_title.lower()
        
        if any(word in title_lower for word in ["walk", "walking"]):
            return "walk"
        elif any(word in title_lower for word in ["feed", "feeding", "meal", "eating"]):
            return "feeding"
        elif any(word in title_lower for word in ["play", "playing", "game"]):
            return "play"
        elif any(word in title_lower for word in ["groom", "grooming", "bath"]):
            return "grooming"
        elif any(word in title_lower for word in ["vet", "checkup", "visit"]):
            return "vet"
        elif any(word in title_lower for word in ["train", "training"]):
            return "training"
        else:
            return "other"

    @staticmethod
    def _group_tasks_by_owner_and_type(
        tasks: List[PetCareTask], pets_by_id: Dict[str, Pet]
    ) -> Dict[tuple, List[PetCareTask]]:
        """Group tasks by (owner_id, task_type).
        
        Returns a dict where keys are (owner_id, task_type) tuples and values
        are lists of tasks with that owner and type.
        """
        groups: Dict[tuple, List[PetCareTask]] = {}
        for task in tasks:
            pet = pets_by_id.get(task.pet_id)
            if pet:
                owner_id = pet.owner_id
                task_type = Scheduler._infer_task_type(task.title)
                key = (owner_id, task_type)
                if key not in groups:
                    groups[key] = []
                groups[key].append(task)
        return groups

    @staticmethod
    def _overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
        return a_start < b_end and b_start < a_end

    def _same_type(self, task_a: Optional[PetCareTask], task_b: Optional[PetCareTask]) -> bool:
        if not task_a or not task_b:
            return False
        type_a = self._infer_task_type(task_a.title)
        type_b = self._infer_task_type(task_b.title)
        if type_a == "other" or type_b == "other":
            return False
        return type_a == type_b

    def _next_non_conflicting_start(
        self,
        start: datetime,
        duration: timedelta,
        existing_slots: List[TimeSlot],
        tasks_by_id: Dict[str, PetCareTask],
        candidate_task: PetCareTask,
        end_dt: datetime,
    ) -> Optional[datetime]:
        """Find earliest valid start, allowing overlaps only with same task type."""
        probe = start
        while probe + duration <= end_dt:
            blocking_end: Optional[datetime] = None
            for existing in existing_slots:
                if not self._overlaps(probe, probe + duration, existing.start_time, existing.end_time):
                    continue
                existing_task = tasks_by_id.get(existing.task_id)
                if self._same_type(existing_task, candidate_task):
                    # Same-type tasks are allowed to run in parallel for same owner context.
                    continue
                if blocking_end is None or existing.end_time > blocking_end:
                    blocking_end = existing.end_time

            if blocking_end is None:
                return probe
            probe = blocking_end
        return None

    def schedule_tasks(
        self,
        tasks: List[PetCareTask],
        preferences: Optional[List[Preference]] = None,
        constraints: Optional[List[Constraint]] = None,
        preserve_order: bool = False,
    ) -> Schedule:
        """Produce a Schedule by placing tasks into the day.

        Behavior:
        - If a task has `scheduled_time`, the scheduler will place it at that time.
        - Otherwise tasks are placed greedily after the running cursor.
        - Tasks of the same type for the same owner are batched together (same time slot).
        - Conflicts are prevented: tasks that would overlap with already-scheduled tasks are skipped.
        - Tasks with explicit scheduled_time that conflict are also skipped.
        """
        # Simple scheduler with support for user-provided scheduled_time
        if not tasks:
            return Schedule(date=date.today(), time_slots=[])

        if len(tasks) > MAX_TASKS_PER_RUN:
            raise ValueError(f"Too many tasks ({len(tasks)}). Max supported per run: {MAX_TASKS_PER_RUN}")

        # Filter pending tasks
        pending = [t for t in tasks if not t.completed and t.duration_minutes > 0]
        # Order by priority (HIGH first) then shorter duration first
        if not preserve_order:
            pending = self.optimize_by_priority(pending)

        day = date.today()
        start_dt = datetime.combine(day, time(hour=8, minute=0))
        end_dt = datetime.combine(day, time(hour=20, minute=0))

        slots: List[TimeSlot] = []
        cursor = start_dt

        tasks_by_id: Dict[str, PetCareTask] = {t.id: t for t in tasks}

        # Separate tasks: those with scheduled_time and those without
        explicit_tasks = [t for t in pending if t.scheduled_time is not None]
        implicit_tasks = [t for t in pending if t.scheduled_time is None]

        # Process explicit scheduled_time tasks first
        for task in explicit_tasks:
            needed = timedelta(minutes=task.duration_minutes)
            start = task.scheduled_time
            end = start + needed
            # drop tasks outside the scheduling window
            if start < start_dt or end > end_dt:
                continue
            slot = TimeSlot(start_time=start, end_time=end, task_id=task.id)
            # Allow overlap only if all overlaps are same task type (e.g., feed multiple pets together).
            incompatible = False
            for existing in slots:
                if not self._overlaps(slot.start_time, slot.end_time, existing.start_time, existing.end_time):
                    continue
                existing_task = tasks_by_id.get(existing.task_id)
                if not self._same_type(existing_task, task):
                    incompatible = True
                    break
            if incompatible:
                continue
            slots.append(slot)

        # Process implicit tasks with batching by inferred task type.
        processed = set()
        for task in implicit_tasks:
            if task.id in processed:
                continue

            # Batch same-type + same-duration tasks so pets can do it at the same time.
            task_type = self._infer_task_type(task.title)
            same_type_tasks = [
                t for t in implicit_tasks
                if t.id not in processed
                and self._infer_task_type(t.title) == task_type
                and t.duration_minutes == task.duration_minutes
            ]

            needed = timedelta(minutes=task.duration_minutes)

            chosen_start = self._next_non_conflicting_start(
                start=cursor,
                duration=needed,
                existing_slots=slots,
                tasks_by_id=tasks_by_id,
                candidate_task=task,
                end_dt=end_dt,
            )
            if chosen_start is None:
                for t in same_type_tasks:
                    processed.add(t.id)
                continue

            for t in same_type_tasks:
                slots.append(
                    TimeSlot(
                        start_time=chosen_start,
                        end_time=chosen_start + needed,
                        task_id=t.id,
                    )
                )
                t.scheduled_time = chosen_start
                processed.add(t.id)
            cursor = chosen_start + needed

        schedule = Schedule(date=day, time_slots=slots)

        # Detect any remaining conflicts (same-type overlaps are treated as allowed).
        schedule.warnings = self.detect_conflicts(schedule.time_slots, tasks_by_id)
        return schedule

    def _has_overlap(self, slot: TimeSlot, existing_slots: List[TimeSlot]) -> bool:
        """Check if a time slot overlaps with any existing slots."""
        for existing in existing_slots:
            if slot.start_time < existing.end_time and existing.start_time < slot.end_time:
                return True
        return False

    def optimize_by_priority(self, tasks: List[PetCareTask]) -> List[PetCareTask]:
        """Return tasks ordered by priority and duration (high/short first)."""
        # Sort by priority (HIGH first), then by duration (shorter first)
        priority_value = {Priority.HIGH: 0, Priority.MEDIUM: 1, Priority.LOW: 2}
        return sorted(tasks, key=lambda t: (priority_value.get(t.priority, 1), t.duration_minutes))

    def sort_by_time(self, tasks: List[PetCareTask]) -> List[PetCareTask]:
        """Sort tasks by their scheduled_time (earliest first).

        Tasks without a `scheduled_time` are ordered last by treating their
        key as `datetime.max` so explicit times are prioritized.
        """
        def key_fn(t: PetCareTask):
            # Use scheduled_time (datetime) when present, otherwise a far-future datetime
            return t.scheduled_time if t.scheduled_time is not None else datetime.max

        return sorted(tasks, key=key_fn)

    def filter_tasks(self, owner: Owner, pet_name: Optional[str] = None, completed: Optional[bool] = None) -> List[PetCareTask]:
        """Return tasks optionally filtered by `pet_name` and/or completion status.

        Parameters
        - owner: Owner whose pets/tasks will be searched
        - pet_name: when provided, only tasks for that pet name are returned
        - completed: when True/False, filter by completion status; when None, include both

        Returns a list of matching `PetCareTask` objects.
        """
        results: List[PetCareTask] = []
        for p in owner.get_all_pets():
            if pet_name and p.name != pet_name:
                continue
            for t in p.get_tasks(include_completed=True):
                if completed is None or t.completed == completed:
                    results.append(t)
        return results

    def schedule_for_owner(
        self,
        owner: Owner,
        for_date: Optional[date] = None,
        preferences: Optional[List[Preference]] = None,
        constraints: Optional[List[Constraint]] = None,
    ) -> Schedule:
        """Gather tasks from an Owner and produce a Schedule for them."""
        # Gather tasks from owner and schedule them
        tasks = owner.get_all_tasks(include_completed=False)
        if for_date:
            # for now we ignore recurrence and date filtering
            pass
        return self.schedule_tasks(tasks, preferences=preferences, constraints=constraints)

    def detect_conflicts(self, slots: List[TimeSlot], tasks_by_id: Dict[str, PetCareTask]) -> List[str]:
        """Lightweight conflict detection using pairwise interval checks.

        This function returns a list of human-readable warning strings for any
        overlapping `TimeSlot` pairs. It is intentionally simple (O(n^2)) for
        readability and because the expected number of daily tasks is small.
        """
        warnings: List[str] = []
        n = len(slots)
        for i in range(n):
            a = slots[i]
            for j in range(i + 1, n):
                b = slots[j]
                # overlap if a.start < b.end and b.start < a.end
                if a.start_time < b.end_time and b.start_time < a.end_time:
                    ta = tasks_by_id.get(a.task_id)
                    tb = tasks_by_id.get(b.task_id)
                    if self._same_type(ta, tb):
                        # Same-type overlaps are intentional for multi-pet same-owner batching.
                        continue
                    a_title = ta.title if ta else a.task_id
                    b_title = tb.title if tb else b.task_id
                    a_pet = ta.pet_id if ta else "?"
                    b_pet = tb.pet_id if tb else "?"
                    msg = f"Conflict: '{a_title}' (pet_id={a_pet}) overlaps with '{b_title}' (pet_id={b_pet})"
                    warnings.append(msg)
        # deduplicate
        unique = []
        for w in warnings:
            if w not in unique:
                unique.append(w)
        return unique
