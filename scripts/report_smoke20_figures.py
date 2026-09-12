#!/usr/bin/env python3
"""Figure-aligned smoke20 reporter: metrics, round QA maps, case study, charts."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _norm_conf(conf: Any) -> float | None:
    if conf is None:
        return None
    try:
        c = float(conf)
    except (TypeError, ValueError):
        return None
    if c > 1.0:
        c = c / 5.0
    return max(0.0, min(1.0, c))


def compute_metrics(rows: list[dict]) -> dict:
    if not rows:
        return {"acc": 0.0, "turns": 0.0, "n": 0, "acc_pct": 0.0}
    correct = []
    turns = []
    for row in rows:
        system = row["interactive_system"]
        info = row["info"]
        is_correct = system.get("closest_option") == info.get("correct_answer_idx")
        correct.append(1.0 if is_correct else 0.0)
        turns.append(float(system.get("num_questions", 0)))
    acc = sum(correct) / len(correct)
    return {
        "acc": acc,
        "acc_pct": round(100.0 * acc, 2),
        "turns": sum(turns) / len(turns),
        "n": len(rows),
        "n_correct": int(sum(correct)),
    }


def write_architecture_io(out: Path) -> None:
    text = """# Architecture & I/O (KnowGuard smoke20)

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
"""
    out.write_text(text, encoding="utf-8")


def write_round_qa_maps(rows: list[dict], out: Path) -> None:
    lines = ["# Multi-round QA maps (smoke20)", ""]
    for row in rows:
        system = row["interactive_system"]
        info = row["info"]
        cid = row.get("id", "?")
        correct = system.get("closest_option") == info.get("correct_answer_idx")
        lines.append(f"## Case `{cid}` — {'CORRECT' if correct else 'WRONG'}")
        lines.append("")
        lines.append(f"**Initial input:** {info.get('initial_info', '')}")
        lines.append("")
        qs = system.get("questions") or []
        ans = system.get("answers") or []
        extras = system.get("temp_additional_info") or []
        n = max(len(qs), len(ans), 1)
        for i in range(n):
            q = qs[i] if i < len(qs) else ""
            a = ans[i] if i < len(ans) else ""
            conf = None
            if i < len(extras) and isinstance(extras[i], dict):
                conf = _norm_conf(extras[i].get("confidence"))
            conf_s = f"{conf:.2f}" if conf is not None else "n/a"
            if q:
                lines.append(f"### Round {i + 1}")
                lines.append(f"- **Doctor Q:** {q}")
                lines.append(f"- **Patient A:** {a if a else '(no answer / commit this turn)'}")
                lines.append(f"- **Confidence:** {conf_s}")
                lines.append("")
        lines.append(f"**Final free-text:** {system.get('free_text_answer', '')}")
        lines.append(
            f"**Mapped option:** {system.get('closest_option')} "
            f"(gold `{info.get('correct_answer_idx')}`: {info.get('correct_answer', '')})"
        )
        lines.append(f"**Turns:** {system.get('num_questions', 0)}")
        lines.append("")
        lines.append("---")
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")


def pick_case_study(rows: list[dict]) -> dict | None:
    """Prefer correct multi-round (≥2 questions); else longest correct; else longest."""
    scored = []
    for row in rows:
        system = row["interactive_system"]
        info = row["info"]
        nq = int(system.get("num_questions") or 0)
        ok = system.get("closest_option") == info.get("correct_answer_idx")
        score = (2 if ok else 0) + (1 if nq >= 2 else 0) + min(nq, 12) * 0.01
        scored.append((score, nq, row))
    if not scored:
        return None
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return scored[0][2]


def write_case_study(row: dict | None, out: Path) -> None:
    if row is None:
        out.write_text("# Case study\n\nNo cases available.\n", encoding="utf-8")
        return
    system = row["interactive_system"]
    info = row["info"]
    cid = row.get("id", "?")
    ok = system.get("closest_option") == info.get("correct_answer_idx")
    qs = system.get("questions") or []
    ans = system.get("answers") or []
    extras = system.get("temp_additional_info") or []
    lines = [
        "# Case study (Fig. 4 style) — investigate-before-abstain",
        "",
        f"**Case id:** `{cid}`",
        f"**Outcome:** {'Confident correct answer' if ok else 'Answered (incorrect vs gold)'}",
        "",
        "## Initial input",
        "",
        info.get("initial_info", ""),
        "",
        "## Multi-round interaction",
        "",
    ]
    for i, q in enumerate(qs):
        a = ans[i] if i < len(ans) else ""
        conf = None
        if i < len(extras) and isinstance(extras[i], dict):
            conf = _norm_conf(extras[i].get("confidence"))
        status = "Unconfident for answer (continue investigation)"
        if conf is not None and conf >= 0.8 and i == len(qs) - 1 and not a:
            status = "Confident for answer"
        lines.append(f"### Round {i + 1}")
        lines.append(f"- **Question:** {q}")
        lines.append(f"- **Patient answer:** {a or '(commit / no further patient reply)'}")
        if conf is not None:
            lines.append(f"- **Normalized confidence:** {conf:.2f}")
        lines.append(f"- **Status:** {status}")
        lines.append("")
    # Final commit turn may only appear as answer without a trailing empty patient reply
    if not qs:
        lines.append("_No clarifying questions; answered from initial info._")
        lines.append("")
    lines.extend(
        [
            "## Final output",
            "",
            f"- **Diagnosis / free-text answer:** {system.get('free_text_answer', '')}",
            f"- **Mapped option:** {system.get('closest_option')}",
            f"- **Gold:** {info.get('correct_answer_idx')} — {info.get('correct_answer', '')}",
            f"- **Options:** {json.dumps(info.get('options', {}), ensure_ascii=False)}",
            "",
        ]
    )
    out.write_text("\n".join(lines), encoding="utf-8")


def acc_vs_length(rows: list[dict]) -> list[dict]:
    buckets: dict[int, list[float]] = defaultdict(list)
    for row in rows:
        system = row["interactive_system"]
        info = row["info"]
        nq = int(system.get("num_questions") or 0)
        ok = 1.0 if system.get("closest_option") == info.get("correct_answer_idx") else 0.0
        buckets[nq].append(ok)
    out = []
    for length in sorted(buckets):
        vals = buckets[length]
        out.append(
            {
                "conversation_length": length,
                "acc": sum(vals) / len(vals),
                "acc_pct": round(100.0 * sum(vals) / len(vals), 2),
                "n": len(vals),
            }
        )
    return out


def confidence_vs_progress(rows: list[dict]) -> list[dict]:
    """Average normalized confidence at normalized progress bins."""
    # Collect (progress, conf) points
    points: list[tuple[float, float]] = []
    for row in rows:
        extras = row["interactive_system"].get("temp_additional_info") or []
        confs = []
        for extra in extras:
            if isinstance(extra, dict) and "confidence" in extra:
                c = _norm_conf(extra.get("confidence"))
                if c is not None:
                    confs.append(c)
        if not confs:
            continue
        n = len(confs)
        for i, c in enumerate(confs):
            prog = (i + 1) / n  # 0..1 conversation progress
            points.append((prog, c))
    # Bin into 10% progress steps
    bins = {round(p, 1): [] for p in [i / 10 for i in range(1, 11)]}
    for prog, c in points:
        key = round(min(1.0, max(0.1, prog)), 1)
        # snap to nearest 0.1
        key = round(key * 10) / 10.0
        if key not in bins:
            bins[key] = []
        bins[key].append(c)
    rows_out = []
    for prog in sorted(bins):
        vals = bins[prog]
        if not vals:
            continue
        rows_out.append(
            {
                "progress": prog,
                "progress_pct": int(prog * 100),
                "mean_confidence": sum(vals) / len(vals),
                "n": len(vals),
            }
        )
    return rows_out


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def try_plots(outdir: Path, acc_rows: list[dict], conf_rows: list[dict]) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return

    if acc_rows:
        fig, ax = plt.subplots(figsize=(6, 4))
        xs = [r["conversation_length"] for r in acc_rows]
        ys = [r["acc_pct"] for r in acc_rows]
        ax.plot(xs, ys, marker="*", color="#c2185b", label="KnowGuard smoke20")
        ax.set_xlabel("Average Conversation Length (turns)")
        ax.set_ylabel("Accuracy (%)")
        ax.set_title("Accuracy vs Conversation Length")
        ax.legend()
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        fig.savefig(outdir / "acc_vs_length.png", dpi=140)
        plt.close(fig)

    if conf_rows:
        fig, ax = plt.subplots(figsize=(6, 4))
        xs = [r["progress_pct"] for r in conf_rows]
        ys = [r["mean_confidence"] for r in conf_rows]
        ax.plot(xs, ys, marker="D", color="#4a148c", label="KnowGuard")
        ax.set_xlabel("Normalized Conversation Progress (%)")
        ax.set_ylabel("Normalized Confidence Score")
        ax.set_ylim(0, 1.05)
        ax.set_title("Confidence vs Progress")
        ax.legend()
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        fig.savefig(outdir / "confidence_vs_progress.png", dpi=140)
        plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "results_jsonl",
        nargs="?",
        default="results/KnowGuardExpert_nemotron_ultra_smoke20.jsonl",
    )
    parser.add_argument(
        "--outdir",
        default="results/smoke20_figures",
    )
    args = parser.parse_args()

    src = Path(args.results_jsonl)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    rows = load_jsonl(src) if src.exists() else []
    metrics = compute_metrics(rows)
    metrics["file"] = str(src)
    (outdir / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")

    write_architecture_io(outdir / "architecture_io.md")
    write_round_qa_maps(rows, outdir / "round_qa_maps.md")
    write_case_study(pick_case_study(rows), outdir / "case_study.md")

    acc_rows = acc_vs_length(rows)
    conf_rows = confidence_vs_progress(rows)
    write_csv(
        outdir / "acc_vs_length.csv",
        ["conversation_length", "acc", "acc_pct", "n"],
        acc_rows,
    )
    write_csv(
        outdir / "confidence_vs_progress.csv",
        ["progress", "progress_pct", "mean_confidence", "n"],
        conf_rows,
    )
    try_plots(outdir, acc_rows, conf_rows)

    # Also mirror metrics next to JSONL
    metrics_path = src.with_name(src.stem + "_metrics.json")
    metrics_path.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(metrics, indent=2))
    print(f"wrote figures to {outdir}")


if __name__ == "__main__":
    main()
