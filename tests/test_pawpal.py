from datetime import datetime, timedelta

from agent_scheduler import SchedulingAgent
from chatbot import apply_schedule_intent
from pawpal_system import PetCareTask, Pet, Owner, Scheduler, Priority


# ============================================================================
# SECTION 1: Core Task Management Tests
# ============================================================================


def test_task_completion():
    """DEMO: Verify tasks can be marked as complete."""
    t = PetCareTask(title="Test Task", duration_minutes=5)
    assert not t.completed  # Task starts incomplete
    t.mark_completed()
    assert t.completed  # Task is now marked complete


def test_task_addition():
    """DEMO: Verify tasks can be added to pets."""
    p = Pet(name="TestPet")
    initial = len(p.get_tasks())
    t = PetCareTask(title="Feed", duration_minutes=5)
    p.add_task(t)
    # Verify task was added and count increased
    assert len(p.get_tasks()) == initial + 1
    assert any(task.title == "Feed" for task in p.get_tasks())


# ============================================================================
# SECTION 2: Scheduling & Sorting Tests
# ============================================================================


def test_sorting_correctness():
    """DEMO: Verify tasks are sorted correctly by scheduled time (earliest first)."""
    owner = Owner(name="Tester")
    pet = Pet(name="Buddy")
    owner.add_pet(pet)

    # Create tasks out of order (09:00, 08:30, 08:45)
    t1 = PetCareTask(title="T1", duration_minutes=10)
    t2 = PetCareTask(title="T2", duration_minutes=10)
    t3 = PetCareTask(title="T3", duration_minutes=10)

    today = datetime.today()
    t1.scheduled_time = datetime.combine(today.date(), datetime.strptime("09:00", "%H:%M").time())
    t2.scheduled_time = datetime.combine(today.date(), datetime.strptime("08:30", "%H:%M").time())
    t3.scheduled_time = datetime.combine(today.date(), datetime.strptime("08:45", "%H:%M").time())

    pet.add_task(t1)
    pet.add_task(t2)
    pet.add_task(t3)

    sched = Scheduler()
    sorted_tasks = sched.sort_by_time(owner.get_all_tasks(include_completed=True))
    times = [t.scheduled_time for t in sorted_tasks]
    # Verify sorting: tasks should be in chronological order (08:30, 08:45, 09:00)
    assert times == sorted(times)


def test_recurring_task_generation():
    """DEMO: Verify recurring tasks auto-generate next occurrence when completed."""
    pet = Pet(name="Coco")
    t = PetCareTask(title="Daily Walk", duration_minutes=15, frequency="daily")
    today = datetime.today()
    t.scheduled_time = datetime.combine(today.date(), datetime.strptime("08:00", "%H:%M").time())
    pet.add_task(t)

    # When user marks the task complete, system auto-generates tomorrow's occurrence
    new_task = pet.complete_task(t.id)

    # Verify original task is marked completed
    assert any(task.id == t.id and task.completed for task in pet.get_tasks(include_completed=True))
    # Verify new daily task created for next day at same time
    assert new_task is not None
    assert new_task.frequency == "daily"
    assert new_task.scheduled_time.date() == (t.scheduled_time.date() + timedelta(days=1))



# ============================================================================
# SECTION 3: Conflict Prevention & Guardrails Tests
# ============================================================================


def test_conflict_detection_flags_duplicates():
    """DEMO: Verify scheduler prevents conflicts by auto-moving overlapping tasks."""
    owner = Owner(name="ConflictOwner")
    p1 = Pet(name="A")
    p2 = Pet(name="B")
    owner.add_pet(p1)
    owner.add_pet(p2)

    # Both tasks scheduled at same time (09:00) - will cause conflict
    t1 = PetCareTask(title="TaskA", duration_minutes=30)
    t2 = PetCareTask(title="TaskB", duration_minutes=20)
    today = datetime.today()
    scheduled = datetime.combine(today.date(), datetime.strptime("09:00", "%H:%M").time())
    t1.scheduled_time = scheduled
    t2.scheduled_time = scheduled

    p1.add_task(t1)
    p2.add_task(t2)

    sched = Scheduler()
    schedule = sched.schedule_for_owner(owner)

    # Scheduler prevents conflict by moving one task to next available slot
    assert len(schedule.time_slots) == 1, "Expected only one task to be scheduled (other moved to avoid conflict)"
    scheduled_task_id = schedule.time_slots[0].task_id
    assert scheduled_task_id in [t1.id, t2.id], "Expected one of the two tasks to be scheduled"
    # No warnings because conflicts are prevented proactively
    assert not schedule.warnings, "Expected no conflict warnings (conflicts are prevented)"


def test_task_guardrail_rejects_non_positive_duration():
    """DEMO: System rejects invalid task duration (guardrail check)."""
    try:
        # Try to create task with 0 minutes duration - should fail
        PetCareTask(title="Bad task", duration_minutes=0)
        assert False, "Expected ValueError for non-positive duration"
    except ValueError as exc:
        # Verify error message is clear
        assert "greater than 0" in str(exc)



def test_task_guardrail_rejects_empty_title():
    """DEMO: System rejects tasks with empty or whitespace-only titles."""
    try:
        # Try to create task with blank title - should fail
        PetCareTask(title="   ", duration_minutes=5)
        assert False, "Expected ValueError for empty title"
    except ValueError as exc:
        assert "cannot be empty" in str(exc)


# ============================================================================
# SECTION 4: AI Agent Tests (Plan-Act-Verify Loop)
# ============================================================================
# These test the agentic workflow: baseline schedule → LLM refinement → best schedule


class _FakeLLM:
    """Mock LLM for testing: returns pre-determined task ordering."""
    def __init__(self, ordered_task_ids):
        self._ordered = ordered_task_ids

    def enabled(self):
        return True

    def propose_task_order(self, tasks, schedule):
        return {"ordered_task_ids": self._ordered, "rationale": "Place provided order first"}


class _BrokenLLM:
    """Mock LLM for testing: simulates API failure."""
    def enabled(self):
        return True

    def propose_task_order(self, tasks, schedule):
        raise RuntimeError("provider unavailable")


def test_agent_falls_back_when_llm_fails():
    """DEMO: Agent gracefully falls back to deterministic schedule when LLM fails."""
    owner = Owner(name="Fallback")

    pet = Pet(name="Milo")
    owner.add_pet(pet)
    pet.add_task(PetCareTask(title="Walk", duration_minutes=20, priority=Priority.HIGH))
    pet.add_task(PetCareTask(title="Walk", duration_minutes=20, priority=Priority.HIGH))
    pet.add_task(PetCareTask(title="Groom", duration_minutes=30, priority=Priority.LOW))

    # Use broken LLM to test fallback behavior
    agent = SchedulingAgent(scheduler=Scheduler(), llm_client=_BrokenLLM(), max_iterations=1)
    result = agent.schedule_for_owner(owner)

    # Verify agent still produces valid schedule (doesn't crash)
    assert result.schedule.time_slots
    # Verify error is logged in rationale
    assert "LLM error" in result.rationale


def test_agent_uses_llm_reordering_when_available():
    """DEMO: Agent successfully uses LLM's proposed task reordering."""
    owner = Owner(name="Reorder")
    pet = Pet(name="Nova")
    owner.add_pet(pet)

    # Create 3 tasks with same priority (will be equal in deterministic order)
    t1 = PetCareTask(title="Task 1", duration_minutes=10, priority=Priority.MEDIUM)
    t2 = PetCareTask(title="Task 2", duration_minutes=10, priority=Priority.MEDIUM)
    t3 = PetCareTask(title="Task 3", duration_minutes=10, priority=Priority.MEDIUM)
    pet.add_task(t1)
    pet.add_task(t2)
    pet.add_task(t3)

    # Mock LLM proposes order: Task 3 → Task 1 → Task 2
    llm = _FakeLLM([t3.id, t1.id, t2.id])
    agent = SchedulingAgent(scheduler=Scheduler(), llm_client=llm, max_iterations=1)
    result = agent.schedule_for_owner(owner)

    # Verify LLM was used for reordering
    assert result.used_llm
    # Verify schedule follows LLM's proposed order (Task 3 scheduled first)
    assert result.schedule.time_slots[0].task_id == t3.id


# ============================================================================
# SECTION 5: Chat Intent Parsing Tests (Natural Language Understanding)
# ============================================================================


def test_follow_up_walk_is_scheduled_right_after_feeding_for_all_pets():
    """DEMO: Follow-up tasks are scheduled right after previous tasks (smart sequencing)."""
    owner = Owner(name="Jordan")
    mochi = Pet(name="Mochi")
    thor = Pet(name="Thor")
    owner.add_pet(mochi)
    owner.add_pet(thor)

    # Step 1: Both pets have feeding scheduled at 08:00
    feeding_mochi = PetCareTask(title="feeding", duration_minutes=10, priority=Priority.HIGH)
    feeding_thor = PetCareTask(title="feeding", duration_minutes=10, priority=Priority.HIGH)
    today = datetime.today()
    at_0800 = datetime.combine(today.date(), datetime.strptime("08:00", "%H:%M").time())
    feeding_mochi.scheduled_time = at_0800
    feeding_thor.scheduled_time = at_0800
    mochi.add_task(feeding_mochi)
    thor.add_task(feeding_thor)

    # Step 2: Follow-up request adds walks without explicit times
    # System should schedule walks right after feeding (08:10)
    walk_mochi = PetCareTask(title="walk", duration_minutes=30, priority=Priority.MEDIUM)
    walk_thor = PetCareTask(title="walk", duration_minutes=30, priority=Priority.MEDIUM)
    mochi.add_task(walk_mochi)
    thor.add_task(walk_thor)

    sched = Scheduler()
    schedule = sched.schedule_for_owner(owner)
    slots_by_task_id = {slot.task_id: slot for slot in schedule.time_slots}

    # Verify walks are scheduled at 08:10 (right after 08:00-08:10 feeding)
    assert slots_by_task_id[walk_mochi.id].start_time.strftime("%H:%M") == "08:10"
    assert slots_by_task_id[walk_thor.id].start_time.strftime("%H:%M") == "08:10"
    assert not schedule.warnings


def test_apply_intent_without_pet_names_targets_all_existing_pets():
    """DEMO: When pet names not specified, tasks apply to all pets (smart defaulting)."""
    owner = Owner(name="Jordan")
    mochi = Pet(name="Mochi")
    thor = Pet(name="Thor")
    owner.add_pet(mochi)
    owner.add_pet(thor)

    # User says "add walk" without specifying pets
    # System should add to both existing pets
    intent = {
        "action": "schedule",
        "pet_names": [],  # Empty - should default to all pets
        "tasks": [{"title": "walk", "duration_minutes": 30, "priority": "MEDIUM"}],
    }
    result = apply_schedule_intent(owner, intent)

    assert result["success"]
    assert len(result["added_tasks"]) == 2
    assert len(mochi.get_tasks()) == 1
    assert len(thor.get_tasks()) == 1


def test_per_pet_priority_parsing():
    """Test that chatbot correctly parses different priorities for different pets."""
    owner = Owner(name="Jordan")
    mochi = Pet(name="Mochi")
    thor = Pet(name="Thor")
    owner.add_pet(mochi)
    owner.add_pet(thor)

    # Simulate LLM returning per-pet priorities
    intent = {
        "action": "schedule",
        "pet_names": ["Mochi", "Thor"],
        "tasks": [
            {"title": "eat", "duration_minutes": 20, "priority": "MEDIUM", "pet_name": "Mochi"},
            {"title": "eat", "duration_minutes": 20, "priority": "LOW", "pet_name": "Thor"},
        ],
    }
    result = apply_schedule_intent(owner, intent)

    # Verify both pets got the task
    assert result["success"]
    assert len(result["added_tasks"]) == 2
    assert len(mochi.get_tasks()) == 1
    assert len(thor.get_tasks()) == 1


def test_per_pet_priority_parsing():
    """DEMO: Chat correctly assigns different priorities to same task type for different pets."""
    owner = Owner(name="Jordan")
    mochi = Pet(name="Mochi")
    thor = Pet(name="Thor")
    owner.add_pet(mochi)
    owner.add_pet(thor)

    # User says: "Add eating for Mochi (medium) and Thor (low)"
    # LLM parses and returns per-pet priorities
    intent = {
        "action": "schedule",
        "pet_names": ["Mochi", "Thor"],
        "tasks": [
            {"title": "eat", "duration_minutes": 20, "priority": "MEDIUM", "pet_name": "Mochi"},
            {"title": "eat", "duration_minutes": 20, "priority": "LOW", "pet_name": "Thor"},
        ],
    }
    result = apply_schedule_intent(owner, intent)

    assert result["success"]
    assert len(result["added_tasks"]) == 2

    # Verify Mochi's eat task has MEDIUM priority
    mochi_eat = next((t for t in mochi.get_tasks() if t.title == "eat"), None)
    assert mochi_eat is not None
    assert mochi_eat.priority == Priority.MEDIUM

    # Verify Thor's eat task has LOW priority (different from Mochi!)
    thor_eat = next((t for t in thor.get_tasks() if t.title == "eat"), None)
    assert thor_eat is not None
    assert thor_eat.priority == Priority.LOW


def test_no_duplicate_tasks_with_different_priorities():
    """DEMO: System allows same task type with different priorities (not a duplicate)."""
    owner = Owner(name="Jordan")
    mochi = Pet(name="Mochi")
    owner.add_pet(mochi)

    # Step 1: Add eating task with MEDIUM priority
    intent1 = {
        "action": "schedule",
        "pet_names": ["Mochi"],
        "tasks": [{"title": "eat", "duration_minutes": 20, "priority": "MEDIUM"}],
    }
    result1 = apply_schedule_intent(owner, intent1)
    assert len(result1["added_tasks"]) == 1

    # Step 2: Add eating task with LOW priority
    # These are DIFFERENT tasks (different priorities), not duplicates
    intent2 = {
        "action": "schedule",
        "pet_names": ["Mochi"],
        "tasks": [{"title": "eat", "duration_minutes": 20, "priority": "LOW"}],
    }
    result2 = apply_schedule_intent(owner, intent2)
    assert len(result2["added_tasks"]) == 1

    # Verify Mochi has 2 separate eat tasks (one MEDIUM, one LOW)
    eat_tasks = [t for t in mochi.get_tasks() if t.title == "eat"]
    assert len(eat_tasks) == 2
    priorities = {t.priority for t in eat_tasks}
    assert Priority.MEDIUM in priorities
    assert Priority.LOW in priorities

