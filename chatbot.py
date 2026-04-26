"""Chatbot interface for PawPal+ scheduling via natural language."""

import json
from typing import Any, Dict, List, Optional

from llm_client import LLMClient
from pawpal_system import Owner, Pet, PetCareTask, Priority


def _extract_json(text: str) -> Dict[str, Any]:
    """Extract JSON from text, handling markdown code blocks."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        text = text[start:end]
    return json.loads(text)


def parse_scheduling_intent(
    user_message: str,
    owner: Optional[Owner] = None,
    llm_client: Optional[LLMClient] = None,
) -> Dict[str, Any]:
    """Parse user message to extract scheduling intent.
    
    Returns a dict with:
    - action: "schedule", "show_tasks", "add_pet", etc.
    - pets: list of pet names mentioned
    - tasks: list of task dicts with title, duration, priority
    - response: natural language confirmation
    """
    if not llm_client or not llm_client.enabled():
        return {"action": "error", "response": "LLM not configured"}

    prompt = f"""You are a pet care scheduling assistant. Parse this user message and extract their intent.

User message: "{user_message}"

Current owner: {owner.name if owner else "unknown"}
Current pets: {', '.join([p.name for p in owner.get_all_pets()]) if owner else "none"}

Extract the following as JSON (no markdown, just pure JSON):
{{
  "action": "schedule",
  "pet_names": ["list of pet names mentioned"],
  "tasks": [
    {{"title": "task name", "duration_minutes": 20, "priority": "HIGH"}}
  ],
  "interpretation": "brief summary"
}}

Be helpful and infer reasonable defaults:
- If duration not specified, assume 20-30 minutes
- If priority not specified, assume MEDIUM
- If multiple pets mentioned, create tasks for each
- Recognize common pet care tasks: walk, feeding, play, grooming, vet, training, etc.

If the user wants to mark tasks as done/complete/finished, return:
{{
  "action": "complete_tasks",
  "pet_names": ["list of pet names, or empty for all pets"],
  "interpretation": "brief summary"
}}
"""

    payload = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 500,
        "messages": [{"role": "user", "content": prompt}],
    }

    headers = {
        "x-api-key": llm_client.api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    import urllib.request
    import urllib.error

    try:
        req = urllib.request.Request(
            f"{llm_client.base_url}/v1/messages",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=llm_client.timeout_seconds) as resp:
            response_data = json.loads(resp.read().decode("utf-8"))

        content = response_data.get("content", [{}])[0].get("text", "{}")
        result = _extract_json(content)
        return result
    except Exception as e:
        return {"action": "error", "response": f"Failed to parse intent: {str(e)}"}


def apply_schedule_intent(
    owner: Owner,
    intent: Dict[str, Any],
    llm_client: Optional[LLMClient] = None,
) -> Dict[str, Any]:
    """Apply the parsed intent to the owner's pets and tasks.
    
    Returns a dict with:
    - success: bool
    - added_tasks: list of task dicts
    - added_pets: list of pet names
    - message: confirmation message
    """
    added_tasks = []
    added_pets = []

    # Add any mentioned pets that don't exist
    pet_names = intent.get("pet_names", [])
    existing_pet_names = {p.name for p in owner.get_all_pets()}

    for pet_name in pet_names:
        if pet_name not in existing_pet_names:
            new_pet = Pet(name=pet_name, species="dog")  # default to dog
            owner.add_pet(new_pet)
            added_pets.append(pet_name)

    # If the user asks a follow-up like "right after feeding, go for a walk"
    # and omits names, apply tasks to all current pets for this owner.
    if not pet_names:
        pet_names = [p.name for p in owner.get_all_pets()]

    # Add tasks to pets
    tasks_data = intent.get("tasks", [])
    if pet_names and tasks_data:
        # If the model already attached pet names at task-level, use that mapping.
        per_task_pet_mapping = any(isinstance(t, dict) and t.get("pet_name") for t in tasks_data)
        dedupe_keys = set()

        for task_data in tasks_data:
            mapped_pet_names = [task_data.get("pet_name")] if per_task_pet_mapping and task_data.get("pet_name") else pet_names
            for pet_name in mapped_pet_names:
                pet = next((p for p in owner.get_all_pets() if p.name == pet_name), None)
                if not pet:
                    continue

                try:
                    title = str(task_data.get("title", "Unnamed task"))
                    duration = int(task_data.get("duration_minutes", 20))
                    priority_name = str(task_data.get("priority", "MEDIUM")).upper()
                    key = (pet_name, title.strip().lower(), duration, priority_name)
                    if key in dedupe_keys:
                        continue

                    task = PetCareTask(
                        title=title,
                        duration_minutes=duration,
                        priority=Priority[priority_name],
                    )
                    pet.add_task(task)
                    dedupe_keys.add(key)
                    added_tasks.append(
                        {
                            "pet": pet_name,
                            "title": task.title,
                            "duration": task.duration_minutes,
                            "priority": task.priority.name,
                        }
                    )
                except Exception:
                    pass  # Skip invalid tasks

    message = f"Added {len(added_tasks)} tasks to {len(added_pets) or len(pet_names)} pets."
    return {
        "success": True,
        "added_tasks": added_tasks,
        "added_pets": added_pets,
        "message": message,
    }


def format_schedule_response(
    schedule,
    owner: Owner,
    rationale: str,
) -> str:
    """Format a generated schedule as a conversational response with a detailed table."""
    if not schedule.time_slots:
        return "No tasks could be scheduled for today."

    pets_by_id = {p.id: p for p in owner.get_all_pets()}
    tasks_by_id = {t.id: t for t in owner.get_all_tasks(include_completed=True)}

    lines = [f"**📅 Schedule for {schedule.date.strftime('%A, %B %d')}:**\n"]
    
    # Create a formatted table
    lines.append("| Time | Pet | Task | Duration |")
    lines.append("|------|-----|------|----------|")

    for slot in sorted(schedule.time_slots, key=lambda s: s.start_time):
        start = slot.start_time.strftime("%H:%M")
        end = slot.end_time.strftime("%H:%M")
        task = tasks_by_id.get(slot.task_id)
        pet = pets_by_id.get(task.pet_id) if task else None
        duration = f"{task.duration_minutes}m" if task else "?"

        pet_name = pet.name if pet else "Unknown"
        task_title = task.title if task else "Unknown task"
        
        lines.append(f"| {start}–{end} | {pet_name} | {task_title} | {duration} |")

    lines.append(f"\n**✨ Reasoning:** {rationale[:250]}...")
    return "\n".join(lines)
