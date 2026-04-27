from __future__ import annotations

import json
import os
import urllib.request
from typing import Any, Dict, List

from pawpal_system import PetCareTask, Schedule


class LLMClient:
    """Provider-aware client for proposing task order refinements.

    Supported providers:
    - anthropic (Claude API)
    - openai (OpenAI-compatible chat completions API)
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        provider: str | None = None,
        timeout_seconds: int = 20,
    ) -> None:
        self._load_env_file()
        self.provider = (provider or os.getenv("LLM_PROVIDER", "anthropic")).strip().lower()

        if self.provider == "anthropic":
            self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
            self.base_url = (base_url or os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")).rstrip("/")
        else:
            self.api_key = api_key or os.getenv("LLM_API_KEY", "")
            self.base_url = (base_url or os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")).rstrip("/")

        self.timeout_seconds = timeout_seconds

    def enabled(self) -> bool:
        return bool(self.api_key)

    def propose_task_order(self, tasks: List[PetCareTask], schedule: Schedule) -> Dict[str, Any]:
        if not self.enabled():
            raise RuntimeError("LLM is not configured")

        if self.provider == "anthropic":
            return self._propose_with_anthropic(tasks, schedule)
        return self._propose_with_openai_compatible(tasks, schedule)

    def _propose_with_openai_compatible(self, tasks: List[PetCareTask], schedule: Schedule) -> Dict[str, Any]:
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a pet care scheduling expert. Your job is to review the current schedule and suggest "
                    "a better task ordering if possible. Respond ONLY with valid JSON (no markdown, no explanation outside JSON). "
                    "Return ordered_task_ids (array of task IDs in proposed order) and rationale (a brief, human-friendly explanation "
                    "of why this order is better, mentioning pet names and task types, not IDs)."
                ),
            },
            {
                "role": "user",
                "content": self._build_prompt(tasks, schedule),
            },
        ]

        payload = {
            "model": "gpt-4o-mini",
            "messages": messages,
            "temperature": 0,
            "max_tokens": 350,
        }

        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
            body = resp.read().decode("utf-8")
            raw = json.loads(body)

        text = raw["choices"][0]["message"]["content"]
        return self._parse_model_result(text)

    def _propose_with_anthropic(self, tasks: List[PetCareTask], schedule: Schedule) -> Dict[str, Any]:
        system_prompt = (
            "You are a pet care scheduling expert. Your job is to review the current schedule and suggest "
            "a better task ordering if possible. Respond ONLY with valid JSON (no markdown, no explanation outside JSON). "
            "Return ordered_task_ids (array of task IDs in proposed order) and rationale (a brief, human-friendly explanation "
            "of why this order is better, mentioning pet names and task types, not IDs)."
        )

        payload = {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 350,
            "temperature": 0,
            "system": system_prompt,
            "messages": [
                {
                    "role": "user",
                    "content": self._build_prompt(tasks, schedule),
                }
            ],
        }

        req = urllib.request.Request(
            f"{self.base_url}/v1/messages",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
            body = resp.read().decode("utf-8")
            raw = json.loads(body)

        content = raw.get("content", [])
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        text = "\n".join(parts).strip()
        return self._parse_model_result(text)

    def _parse_model_result(self, text: str) -> Dict[str, Any]:
        result = self._extract_json(text)
        ordered = result.get("ordered_task_ids", [])
        if not isinstance(ordered, list):
            ordered = []
        rationale = result.get("rationale", "")
        if not isinstance(rationale, str):
            rationale = ""
        return {"ordered_task_ids": ordered, "rationale": rationale}

    def _build_prompt(self, tasks: List[PetCareTask], schedule: Schedule) -> str:
        task_lines = []
        for t in tasks:
            task_lines.append(
                {
                    "id": t.id,
                    "title": t.title,
                    "priority": t.priority.name,
                    "duration_minutes": t.duration_minutes,
                    "scheduled_time": t.scheduled_time.isoformat() if t.scheduled_time else None,
                }
            )

        sched_lines = []
        for slot in schedule.time_slots:
            sched_lines.append(
                {
                    "task_id": slot.task_id,
                    "start": slot.start_time.strftime("%H:%M"),
                    "end": slot.end_time.strftime("%H:%M"),
                }
            )

        return json.dumps(
            {
                "tasks": task_lines,
                "current_schedule": sched_lines,
                "warnings": schedule.warnings,
                "goal": "Suggest a better order of task IDs. Keep all IDs unique and include only known task IDs.",
            }
        )

    def _extract_json(self, text: str) -> Dict[str, Any]:
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start == -1 or end == -1 or end <= start:
                raise
            return json.loads(text[start : end + 1])

    def _load_env_file(self) -> None:
        """Load key=value pairs from local .env if present.

        Existing OS env vars take precedence over values in .env.
        """
        env_path = os.path.join(os.getcwd(), ".env")
        if not os.path.exists(env_path):
            return

        with open(env_path, "r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
