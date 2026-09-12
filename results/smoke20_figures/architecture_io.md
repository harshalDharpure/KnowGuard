# Architecture & I/O (KnowGuard smoke20)

## Q1 — Architecture

Investigate-before-abstain loop:

1. **Patient agent** (`FactSelectPatient` in `patient.py`) — answers from `atomic_facts`.
2. **Doctor agent** (`KnowGuardExpert` in `expert.py`) — decide ask vs answer each turn.
3. **Evidence discovery** (`InvestigationEngine` in `graph_reason.py` + `ClinicalRAG` in `clinical_rag.py`)
   - Direct retrieval via FAISS KG triplets
   - Graph expansion (multi-hop beam)
   - Clinical textbook passages (phase-routed with KG)
4. **Evidence evaluation** (`EvidenceWeightingEngine`) — embed sim, LLM relevance, graph coherence, round decay, demographic/PPR-style weights.
5. **Abstention** (`knowguard_abstention_decision_open` in `expert_functions.py`) — Likert confidence vs `kg_threshold`; gates: `min_questions`, adjudicator, entropy.
6. **Final judge** (`LLM_judge.compare_answer_to_options`) — free-text → option letter.

## Q2 — Input / Output

### Case input (JSONL)
- `id`, `initial_info`, `context`, `atomic_facts`, `question`, `options`, `answer` / `answer_idx`

### Per-turn
- **In:** `{initial_info, interaction_history: [{question, answer}, ...]}`
- **Out (ask):** `{type: "question", question, confidence, ...}`
- **Out (answer):** `{type: "answer", free_text_answer, confidence, ...}`

### Run output (prediction JSONL)
- `interactive_system.questions[]` / `answers[]` / `num_questions`
- `free_text_answer`, `closest_option`, `correct`
- `temp_additional_info[]` (per-turn confidence and intermediates)

## Q3 — Flow to final answer

```
initial_info
  → InvestigationEngine + ClinicalRAG → evidence pool
  → abstention: enough info?
       no  → generate question → patient answer → update history → repeat
       yes → free-text answer → LLM judge → closest_option vs gold
```

Commit when confidence ≥ threshold and gates allow; at `max_questions` force answer (`max_round=True`).
