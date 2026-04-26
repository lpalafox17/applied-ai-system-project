from datetime import datetime, timedelta

from agent_scheduler import SchedulingAgent
from chatbot import apply_schedule_intent
from pawpal_system import PetCareTask, Pet, Owner, Scheduler, Priority


def test_task_completion():
    t = PetCareTask(title="Test Task", duration_minutes=5)
    assert not t.completed
    t.mark_completed()
    assert t.completed


def test_task_addition():
    p = Pet(name="TestPet")
    initial = len(p.get_tasks())
    t = PetCareTask(title="Feed", duration_minutes=5)
    p.add_task(t)
    assert len(p.get_tasks()) == initial + 1
    # ensure the task is the one we added
    assert any(task.title == "Feed" for task in p.get_tasks())


def test_sorting_correctness():
    """Tasks with scheduled_time should be returned in chronological order."""
    owner = Owner(name="Tester")
    pet = Pet(name="Buddy")
    owner.add_pet(pet)

    # create tasks out of order
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
    assert times == sorted(times)


def test_recurring_task_generation():
    """Completing a daily task creates the next day's occurrence."""
    pet = Pet(name="Coco")
    t = PetCareTask(title="Daily Walk", duration_minutes=15, frequency="daily")
    today = datetime.today()
    t.scheduled_time = datetime.combine(today.date(), datetime.strptime("08:00", "%H:%M").time())
    pet.add_task(t)

    # complete the task
    new_task = pet.complete_task(t.id)

    # original task marked completed
    assert any(task.id == t.id and task.completed for task in pet.get_tasks(include_completed=True))
    # new recurring instance created
    assert new_task is not None
    assert new_task.frequency == "daily"
    assert new_task.scheduled_time.date() == (t.scheduled_time.date() + timedelta(days=1))


def test_conflict_detection_flags_duplicates():
    """Scheduler should prevent conflicts by skipping conflicting tasks."""
    owner = Owner(name="ConflictOwner")
    p1 = Pet(name="A")
    p2 = Pet(name="B")
    owner.add_pet(p1)
    owner.add_pet(p2)

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

    # With conflict prevention, only one task should be scheduled (the other is skipped due to conflict)
    assert len(schedule.time_slots) == 1, "Expected only one task to be scheduled (other skipped due to conflict)"
    scheduled_task_id = schedule.time_slots[0].task_id
    # One of the two tasks should be scheduled
    assert scheduled_task_id in [t1.id, t2.id], "Expected one of the two tasks to be scheduled"
    # No warnings should be generated since conflicts are prevented
    assert not schedule.warnings, "Expected no conflict warnings (conflicts are prevented)"


def test_task_guardrail_rejects_non_positive_duration():
    try:
        PetCareTask(title="Bad task", duration_minutes=0)
        assert False, "Expected ValueError for non-positive duration"
    except ValueError as exc:
        assert "greater than 0" in str(exc)


def test_task_guardrail_rejects_empty_title():
    try:
        PetCareTask(title="   ", duration_minutes=5)
        assert False, "Expected ValueError for empty title"
    except ValueError as exc:
        assert "cannot be empty" in str(exc)


class _FakeLLM:
    def __init__(self, ordered_task_ids):
        self._ordered = ordered_task_ids

    def enabled(self):
        return True

    def propose_task_order(self, tasks, schedule):
        return {"ordered_task_ids": self._ordered, "rationale": "Place provided order first"}


class _BrokenLLM:
    def enabled(self):
        return True

    def propose_task_order(self, tasks, schedule):
        raise RuntimeError("provider unavailable")


def test_agent_falls_back_when_llm_fails():
    owner = Owner(name="Fallback")
    pet = Pet(name="Milo")
    owner.add_pet(pet)
    pet.add_task(PetCareTask(title="Walk", duration_minutes=20, priority=Priority.HIGH))
    pet.add_task(PetCareTask(title="Groom", duration_minutes=30, priority=Priority.LOW))

    agent = SchedulingAgent(scheduler=Scheduler(), llm_client=_BrokenLLM(), max_iterations=1)
    result = agent.schedule_for_owner(owner)

    assert result.schedule.time_slots
    assert "LLM error" in result.rationale


def test_agent_uses_llm_reordering_when_available():
    owner = Owner(name="Reorder")
    pet = Pet(name="Nova")
    owner.add_pet(pet)

    t1 = PetCareTask(title="Task 1", duration_minutes=10, priority=Priority.MEDIUM)
    t2 = PetCareTask(title="Task 2", duration_minutes=10, priority=Priority.MEDIUM)
    t3 = PetCareTask(title="Task 3", duration_minutes=10, priority=Priority.MEDIUM)
    pet.add_task(t1)
    pet.add_task(t2)
    pet.add_task(t3)

    llm = _FakeLLM([t3.id, t1.id, t2.id])
    agent = SchedulingAgent(scheduler=Scheduler(), llm_client=llm, max_iterations=1)
    result = agent.schedule_for_owner(owner)

    assert result.used_llm
    assert result.schedule.time_slots[0].task_id == t3.id


def test_follow_up_walk_is_scheduled_right_after_feeding_for_all_pets():
    owner = Owner(name="Jordan")
    mochi = Pet(name="Mochi")
    thor = Pet(name="Thor")
    owner.add_pet(mochi)
    owner.add_pet(thor)

    # Existing feeding block at 08:00 for both pets.
    feeding_mochi = PetCareTask(title="feeding", duration_minutes=10, priority=Priority.HIGH)
    feeding_thor = PetCareTask(title="feeding", duration_minutes=10, priority=Priority.HIGH)
    today = datetime.today()
    at_0800 = datetime.combine(today.date(), datetime.strptime("08:00", "%H:%M").time())
    feeding_mochi.scheduled_time = at_0800
    feeding_thor.scheduled_time = at_0800
    mochi.add_task(feeding_mochi)
    thor.add_task(feeding_thor)

    # Follow-up request adds walks without explicit pet names.
    walk_mochi = PetCareTask(title="walk", duration_minutes=30, priority=Priority.MEDIUM)
    walk_thor = PetCareTask(title="walk", duration_minutes=30, priority=Priority.MEDIUM)
    mochi.add_task(walk_mochi)
    thor.add_task(walk_thor)

    sched = Scheduler()
    schedule = sched.schedule_for_owner(owner)
    slots_by_task_id = {slot.task_id: slot for slot in schedule.time_slots}

    assert slots_by_task_id[walk_mochi.id].start_time.strftime("%H:%M") == "08:10"
    assert slots_by_task_id[walk_thor.id].start_time.strftime("%H:%M") == "08:10"
    assert not schedule.warnings


def test_apply_intent_without_pet_names_targets_all_existing_pets():
    owner = Owner(name="Jordan")
    mochi = Pet(name="Mochi")
    thor = Pet(name="Thor")
    owner.add_pet(mochi)
    owner.add_pet(thor)

    intent = {
        "action": "schedule",
        "pet_names": [],
        "tasks": [{"title": "walk", "duration_minutes": 30, "priority": "MEDIUM"}],
    }
    result = apply_schedule_intent(owner, intent)

    assert result["success"]
    assert len(result["added_tasks"]) == 2
    assert len(mochi.get_tasks()) == 1
    assert len(thor.get_tasks()) == 1
