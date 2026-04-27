

https://github.com/user-attachments/assets/91e5f776-e423-40c2-bf2d-387445343ae3

# PawPal+ AI Pet Care Scheduler

## 1. Original Project Context

**Original Project Name:** PawPal+ (Modules 1-3)

PawPal+ began as a rule-based pet care planning assistant built with Python and Streamlit. Its original goals were to help busy pet owners organize daily care tasks, prioritize activities by importance and duration, and generate a conflict-free daily schedule. The system supported recurring tasks (daily/weekly), filtering by pet and completion status, and lightweight conflict detection to warn users about scheduling overlaps.

## 2. Title and Summary

**PawPal+ AI Pet Care Scheduler** is an intelligent planning system that transforms a pet owner's task list into an optimized daily schedule using both deterministic scheduling and AI-driven reasoning.

**Why it matters:** Pet care requires consistency, but owners juggle multiple pets, time constraints, and competing priorities. This system removes manual planning friction by automating task ordering, detecting conflicts, and providing transparent reasoning for why tasks are scheduled the way they are. By combining rule-based logic with agentic AI refinement, the system delivers both reliability and intelligence.

## 3. Architecture Overview

The system is organized in five layers:

```
Human User → Streamlit UI → Input Validation → Scheduling Agent → Deterministic Scheduler
                                ↓                     ↓
                          Guardrails Check      LLM Provider (for critique/refinement)
                                ↓
                         Conflict Validator → Final Schedule + Rationale → User
                         
Parallel: Tester/Evaluator → pytest + Reliability Checks → Test Report
```

**Key Components:**

1. **Streamlit UI** (`app.py`): Collects owner, pet, and task inputs; displays schedules and reasoning. Includes both form-based and conversational chat interfaces.
2. **Chatbot Module** (`chatbot.py`): Parses natural language intent using Claude, extracts tasks/pets from user messages, and routes to the scheduler.
3. **Input Validation and Guardrails**: Ensures tasks have valid durations, reasonable bounds, and safe text encoding.
4. **Scheduling Agent**: Executes a plan-critique-refine loop where an LLM evaluates and improves the initial schedule.
5. **Deterministic Scheduler** (`pawpal_system.py`): Creates initial schedule using priority-based greedy packing (08:00–20:00 window). **Now includes conflict prevention**: tasks that would overlap with existing slots are skipped and placed in later time windows.
6. **Conflict and Safety Validator**: Detects overlapping time slots and validates that AI outputs respect constraints.
7. **Tester/Evaluator** (`tests/test_pawpal.py`): Runs unit tests and reliability scenario checks.

**Data Flow:**
Input (owner/pets/tasks) → Validation → Initial schedule generation → Critique and refinement (if AI enabled) → Safety validation → Output (schedule table, warnings, rationale) → Human review → Potential re-run with adjusted inputs.

**Human and Testing Checkpoints:**
- Human can review the generated schedule and adjust tasks/preferences to rerun generation.
- Automated tests verify convergence, fallback behavior, and output validity.
- Invalid AI outputs trigger fallback to deterministic scheduler path.

See `diagrams/pawpal_system_flow.mmd` for the full system flow diagram.

## 4. Setup Instructions

### Prerequisites
- Python 3.8+
- Virtual environment tool (venv or conda)

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/lpalafox17/applied-ai-system-project.git
   cd applied-ai-system-project
   ```

2. Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Configure your local `.env` file:
   ```bash
   ```

The app auto-loads `.env` values from the project root when creating the LLM client.
The model is selected internally by provider defaults, so no model variable is required.

### Running the App

**Launch the Streamlit UI:**
```bash
streamlit run app.py
```


**Two Interfaces:**
1. **Form-Based UI**: Click through owner/pet/task creation, then "Generate schedule"
2. **Chat Interface**: Ask the assistant in natural language at the bottom of the page (e.g., "Schedule morning walk for Mochi and Thor, 20 minutes, high priority")

**Run Tests:**
```bash
python -m pytest tests/test_pawpal.py -v
```

**Run Deterministic Scheduler Demo (CLI):**
```bash
python main.py
```

## 5. Sample Interactions

### Example 1: Per-Pet Priority Handling

**User Input (Chat):**
```
💬 User: "Add walk for Mochi (low) and Thor (high priority)"
```

**System Output:**
```
🤖 Assistant: ✅ Added 2 tasks to 2 pets.

- Added pet: Mochi
- Added pet: Thor
- Added walk for Mochi (20m, LOW)
- Added walk for Thor (20m, HIGH)

📅 Schedule for Sunday, April 26:
| Time       | Pet   | Task | Duration |
|------------|-------|------|----------|
| 08:00–08:20 | Thor  | walk | 20m      |
| 08:00–08:20 | Mochi | walk | 20m      |

✓ Baseline schedule created using priority-based ordering (HIGH → MEDIUM → LOW, shortest duration first).
✓ Refinement 1: Both walk tasks are batched together at 08:00–08:20 since they're the same task type and duration (pets can walk together). HIGH priority (Thor) and LOW priority (Mochi) are scheduled simultaneously to maximize efficiency.
```

---

### Example 2: Conflict Prevention

**Scenario:** User tries to schedule two different high-priority tasks at the same time.

**User Input (Chat):**
```
💬 User: "Schedule morning walk at 08:00 for Mochi, and breakfast at 08:00 for Thor"
```

**System Output:**
```
🤖 Assistant: ✅ Added 2 tasks to 2 pets.

- Added morning walk for Mochi (20m, HIGH, at 08:00)
- Added breakfast for Thor (20m, HIGH, at 08:00)

📅 Schedule with Conflict Prevention:
| Time       | Pet   | Task        | Duration |
|------------|-------|-------------|----------|
| 08:00–08:20 | Mochi | morning walk | 20m      |
| 08:20–08:40 | Thor  | breakfast    | 20m      |

✓ Conflict prevented: Thor's breakfast automatically moved to 08:20 (next available slot) to avoid overlap.
```

---

### Example 3: Marking Tasks Complete via Chat

**User Input (Chat):**
```
💬 User: "Mark all tasks as complete for Mochi and Thor"
```

**System Output:**
```
🤖 Assistant: ✅ Marked 4 task(s) as complete.

Tasks completed:
- Mochi: eat ✅
- Mochi: walk ✅
- Thor: eat ✅
- Thor: walk ✅

📋 Next occurrences auto-generated (if recurring):
- Mochi: eat (Monday 08:00, daily recurrence)
- Thor: eat (Monday 08:00, daily recurrence)
```

---

### Example 4: Conflict Prevention

**Scenario:** User tries to schedule two different high-priority tasks at the same time.

**User Input (Chat):**
```
💬 User: "Schedule morning walk at 08:00 for Mochi, and breakfast at 08:00 for Thor"
```

**System Output:**
```
🤖 Assistant: ✅ Added 2 tasks to 2 pets.

- Added morning walk for Mochi (20m, HIGH, at 08:00)
- Added breakfast for Thor (20m, HIGH, at 08:00)

📅 Schedule with Conflict Prevention:
| Time       | Pet   | Task        | Duration |
|------------|-------|-------------|----------|
| 08:00–08:20 | Mochi | morning walk | 20m      |
| 08:20–08:40 | Thor  | breakfast    | 20m      |

✓ Conflict prevented: Thor's breakfast automatically moved to 08:20 (next available slot) to avoid overlap.
```

---

### Chat Features in Action

**Clear Chat:**
```
💬 User clicks the 🗑️ "Clear Chat" button

✅ Chat and schedule cleared! Start fresh with a new session.
```

**Why This Matters:**
The system combines three key capabilities:
1. **Natural Language Scheduling** — Add tasks by just asking
2. **Intelligent Rescheduling** — Follow-up tasks automatically integrate into the existing schedule
3. **Task Management** — Mark tasks complete and let the system handle recurring task generation
4. **Conflict Prevention** — No more manual slot hunting; the scheduler handles overlaps automatically
5. **Clean UI** — Clear chat history and start fresh anytime



---

### Why This Architecture

**Separation of Concerns:**
Domain objects (`Owner`, `Pet`, `PetCareTask`) are kept lightweight and focused on data representation, while scheduling logic lives in the `Scheduler` service class. This makes testing, reasoning about behavior, and extending features much easier.

**Deterministic Baseline First:**
The system starts with a simple, predictable greedy scheduler that always produces the same output for the same input. This stability is essential for a production system and provides a fallback when AI features fail.

**Agentic Refinement Layer:**
Adding an LLM-driven critique-and-refine loop on top of the deterministic base allows the system to improve schedule quality and generate human-readable explanations without depending entirely on the LLM for correctness.

**Natural Language Interface (Chat):**
The chatbot layer (`chatbot.py`) makes the agentic workflow accessible without requiring users to manually fill out forms. Claude parses user intent (e.g., "Schedule morning walk for Mochi and Thor"), extracts structured data, and triggers the scheduling agent. This combines NLU (natural language understanding) with agentic reasoning for a seamless user experience.

**Chat Features:**
- **Add tasks via natural language:** "Add eating task for Mochi (medium) and Thor (low priority)"
- **Mark tasks complete via chat:** "Mark tasks as complete for Mochi and Thor"
- **Clear chat history:** Click the 🗑️ button to reset the chat and start fresh
- **Per-pet priorities:** The chatbot correctly assigns different priorities to different pets for the same task type

**Conflict Prevention (Not Just Detection):**
The updated scheduler now actively prevents conflicts by checking if a task overlaps with existing scheduled slots before placement. If it would conflict, the task is placed in the next available time window. This eliminates the need to warn users and manually resolve conflicts—the system handles it transparently.

### Key Trade-offs

| Trade-off | Choice | Reason |
|-----------|--------|--------|
| **Conflict Detection Algorithm** | Simple O(n²) pairwise checks | Small daily task counts make complex algorithms unnecessary; simpler code is easier to understand and verify. |
| **Conflict Resolution** | Prevent (skip conflicting tasks) instead of detect (warn) | Proactive prevention improves user experience; system auto-sequences tasks without requiring manual adjustment. |
| **Scheduling Window** | Fixed 08:00–20:00 | Matches typical pet owner availability; can be made configurable in future iterations. |
| **User Interface** | Both form-based and chat-based | Forms provide explicit control; chat provides accessibility. Both route to the same scheduling logic, ensuring consistency. |
| **Chatbot Intent Parsing** | Claude-powered NLU | Flexible enough to handle varied user phrasing; falls back gracefully if LLM is unavailable. |
| **Agentic Loop Iterations** | Max 1 refinement cycle | Optimized for fast response time (2–3s per schedule) while still allowing LLM improvement over baseline. |
| **Fallback Behavior** | Deterministic scheduler when AI fails | Ensures app remains usable even when LLM provider is unavailable or API key is invalid. |
| **Priority Sorting** | HIGH → MEDIUM → LOW, then by duration | Simple heuristic that works well for daily planning; could be replaced with learned weights in future. |

## 7. Testing Summary

### What Worked

- **Unit Tests (`tests/test_pawpal.py`):** All 9 tests pass locally. Coverage includes:
  - Task completion and recurring task generation (daily/weekly)
  - Task sorting by scheduled time
  - Conflict prevention (tasks that overlap are skipped)
  - Guardrails: invalid task durations and empty titles rejected
  - Agentic fallback: system gracefully uses deterministic scheduler if LLM fails
  - Agentic application: LLM-suggested task ordering is applied and improves schedule

- **Scheduler Reliability:** The deterministic scheduler consistently produces valid, conflict-free schedules for small daily workloads (up to ~20 tasks). Conflict prevention ensures tasks never overlap.

- **UI Integration:** Streamlit session state management works well for persisting owner/pet/task objects across interactions. Both form-based and chat-based interfaces route to the same scheduling logic, ensuring consistency.

- **Chatbot Parsing:** Claude successfully parses varied user phrasings (e.g., "Schedule morning walk for Mochi and Thor, 20 minutes, high priority") and extracts structured scheduling intent (pet names, task titles, durations, priorities).

### What Didn't Work or Remains Limited

- **Large-Scale Performance:** No benchmarks for 100+ tasks per day or multi-owner scenarios.
- **Chatbot Limitations:** Intent parsing relies on Claude API availability; if the LLM is unreachable, the chatbot falls back to a generic error message. Complex intents (e.g., "Schedule walks for all my dogs at different times") may require clarification.
- **AI Output Consistency:** LLM-generated explanations can vary based on model temperature and phrasing; needs stricter prompting or output validation for production use.
- **Advanced Constraints:** Current system doesn't support time windows ("walk only before noon"), cost-based optimization, or complex inter-task dependencies.

### Key Learnings from Testing

1. **Separation of Logic is Crucial:** Keeping scheduling logic in a separate `Scheduler` class made unit tests focused and fast. Testing `Pet` and `Owner` separately from `Scheduler` prevented large, brittle integration tests.

2. **Fallback Paths Save the Day:** Designing for LLM failures (missing API key, rate limit, network error) from the start meant the app gracefully degrades to deterministic scheduling instead of crashing.

3. **Small Tests, Big Impact:** Targeted tests for sorting, recurrence, and conflict detection caught most user-visible bugs early. This is why confidence is high for core behaviors.

## 8. Reflection: What This Project Taught Me About AI and Problem-Solving

### The Core Insight: Intelligence Without Reliability Is Fragile

Building PawPal+ reinforced that AI features are only valuable when paired with guardrails, testing, and transparent decision-making. A beautiful schedule explanation means nothing if the schedule is invalid or if the system crashes when the LLM is unavailable. This project forced me to think about reliability as a first-class feature, not an afterthought.

### Key Problem-Solving Lessons

1. **Determinism as a Foundation:** Starting with a simple, deterministic scheduler before adding AI was the right call. It gave me a stable baseline to measure improvements against and a fallback path when things went wrong.

2. **Tradeoffs Are Everywhere:** Every design choice (conflict detection algorithm, iteration budget, priority weights) involved tradeoffs. Learning to articulate and defend these tradeoffs made me a better engineer.

3. **Testing Validates Assumptions:** I assumed priority-based ordering would work well, but only unit tests confirmed it handles edge cases (tied priorities, zero-duration tasks). Testing made implicit assumptions explicit.

4. **Humans Must Stay in the Loop:** Even with AI generating schedules, users need to see warnings, understand reasoning, and be able to adjust and retry. This "human-in-the-loop" design pattern is more robust and trustworthy than full automation.

### Looking Forward

The biggest lesson is that production AI systems require the same rigor as traditional software: clear requirements, comprehensive testing, documented tradeoffs, and graceful degradation. 

---

## Repository Structure

```
applied-ai-system-project/
├── app.py                          # Streamlit UI (form and chat interfaces)
├── agent_scheduler.py              # Agentic scheduling orchestration (plan-critique-refine)
├── pawpal_system.py                # Core domain objects and Scheduler (with conflict prevention)
├── llm_client.py                   # Provider-aware LLM abstraction (Anthropic/OpenAI)
├── chatbot.py                      # Natural language intent parsing and routing
├── main.py                         # CLI demonstration
├── requirements.txt                # Python dependencies
├── .env.example                    # Environment template (ANTHROPIC_API_KEY, etc.)
├── .vscode/settings.json           # VS Code config for .env auto-loading
├── tests/
│   └── test_pawpal.py             # Unit and reliability tests (9 tests)
├── diagrams/
│   ├── pawpal_classes.mmd         # Class diagram (UML)
│   └── pawpal_system_flow.mmd     # System flow diagram
├── assets/                         # Screenshots and visuals
└── reflection.md                   # Original project reflection
```

