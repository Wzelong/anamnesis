"""Demo-grade augmentation benchmark.

Runs the full corpus N times, aggregates accuracy/consistency/code/trap/provenance
metrics, renders charts and a markdown report. Intended to be re-run by judges
with one command and zero configuration.

  python benchmarks/eval-corpus-v1/run_demo_benchmark.py
  python benchmarks/eval-corpus-v1/run_demo_benchmark.py --runs 5 --only C2,N4
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent.parent
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(ROOT))

from openai import AsyncOpenAI

from config import settings
from run_augmentation_benchmark import (
    clear_pipeline_caches,
    load_pairs,
    run_full_pass,
)

ACTIONS = ["NEW", "DUPLICATE", "UPDATING", "CONFLICTING"]
ACTUAL_AXIS = ACTIONS + ["MISSING"]
TIERS = ["clean", "messy", "trap"]
SYSTEMS = ["SNOMED", "ICD-10", "LOINC", "RxNorm"]
COST_PER_RUN_USD = 0.30


def parse_args():
    p = argparse.ArgumentParser(description="Anamnesis augmentation demo benchmark.")
    p.add_argument("--runs", type=int, default=5)
    p.add_argument("--only", help="Comma-separated note IDs (e.g. C1,E1)")
    p.add_argument("--no-charts", action="store_true", help="Skip matplotlib charts")
    p.add_argument("--keep-cache", action="store_true",
                   help="Don't clear LLM cache between runs (debugging)")
    p.add_argument("--output", help="Output dir (default results/<UTC timestamp>)")
    p.add_argument("--yes", action="store_true",
                   help="Skip cost confirmation (non-interactive)")
    return p.parse_args()


def confirm_cost(n_runs: int, n_notes: int, accept_default: bool) -> bool:
    estimate = COST_PER_RUN_USD * n_runs * (n_notes / 18)
    print(f"Estimated cost: ~${estimate:.2f} ({n_runs} runs × {n_notes} notes)")
    if accept_default or not sys.stdin.isatty():
        return True
    reply = input("Proceed? [y/N] ").strip().lower()
    return reply in ("y", "yes")


def _avg(xs):
    return sum(xs) / len(xs) if xs else 0.0


def aggregate(per_run_rows, per_run_traps, n_runs):
    confusion = {a: Counter() for a in ACTIONS}
    for rows in per_run_rows:
        for r in rows:
            confusion[r["expected"]][r["actual"]] += 1

    per_class_runs: dict[str, list[float]] = {a: [] for a in ACTIONS}
    for rows in per_run_rows:
        totals = Counter(r["expected"] for r in rows)
        hits = Counter(r["expected"] for r in rows if r["hit"])
        for a in ACTIONS:
            if totals[a]:
                per_class_runs[a].append(hits[a] / totals[a])
    per_class = {}
    for a in ACTIONS:
        vals = per_class_runs[a]
        n_facts = sum(1 for rows in per_run_rows for r in rows if r["expected"] == a)
        per_class[a] = {
            "mean": _avg(vals),
            "min": min(vals) if vals else None,
            "max": max(vals) if vals else None,
            "n": int(n_facts / n_runs) if n_runs else 0,
        }

    per_tier_runs: dict[str, list[float]] = defaultdict(list)
    for rows in per_run_rows:
        totals = Counter(r["tier"] for r in rows if r["tier"])
        hits = Counter(r["tier"] for r in rows if r["tier"] and r["hit"])
        for tier in totals:
            per_tier_runs[tier].append(hits[tier] / totals[tier])
    per_tier = {
        tier: {"mean": _avg(vals), "min": min(vals), "max": max(vals)}
        for tier, vals in per_tier_runs.items()
    }

    overall_runs = [
        sum(1 for r in rows if r["hit"]) / len(rows) if rows else 0.0
        for rows in per_run_rows
    ]
    overall = {
        "mean": _avg(overall_runs),
        "min": min(overall_runs) if overall_runs else 0.0,
        "max": max(overall_runs) if overall_runs else 0.0,
        "per_run": overall_runs,
    }

    all_keys: set[tuple[str, str]] = set()
    fact_expected: dict[tuple[str, str], str] = {}
    classifications_by_fact: dict[tuple[str, str], Counter] = defaultdict(Counter)
    fact_hits: Counter = Counter()
    for rows in per_run_rows:
        for r in rows:
            key = (r["note"], r["fact_id"])
            all_keys.add(key)
            fact_expected[key] = r["expected"]
            classifications_by_fact[key][r["actual"]] += 1
            if r["hit"]:
                fact_hits[key] += 1

    hit_rate_buckets: Counter = Counter()
    for key in all_keys:
        hit_rate_buckets[fact_hits.get(key, 0)] += 1

    threshold = max(math.ceil(0.8 * n_runs), 1)
    consistent = sum(c for hits, c in hit_rate_buckets.items() if hits >= threshold)
    total_facts = len(all_keys)
    consistency = consistent / total_facts if total_facts else 0.0

    stable_right = sum(1 for k in all_keys if fact_hits.get(k, 0) == n_runs)
    stable_wrong = sum(1 for k in all_keys if fact_hits.get(k, 0) == 0)
    flaky = total_facts - stable_right - stable_wrong

    stable_wrong_cases = []
    for key in sorted(all_keys):
        if fact_hits.get(key, 0) == 0:
            dist = classifications_by_fact[key]
            most_common = dist.most_common(1)[0][0]
            stable_wrong_cases.append({
                "note": key[0],
                "fact_id": key[1],
                "expected": fact_expected[key],
                "always_actual": most_common,
                "distribution": dict(dist),
            })

    code_total = 0
    code_hit = 0
    per_system_total: Counter = Counter()
    per_system_hit: Counter = Counter()
    for rows in per_run_rows:
        for r in rows:
            if r["code_matched"] is None:
                continue
            code_total += 1
            if r["code_matched"]:
                code_hit += 1
            for system in r["expected_systems"]:
                per_system_total[system] += 1
                if r["code_matched"]:
                    per_system_hit[system] += 1
    code_accuracy = code_hit / code_total if code_total else None
    per_system = {
        s: per_system_hit[s] / per_system_total[s]
        for s in SYSTEMS
        if per_system_total[s] > 0
    }

    decomp: Counter = Counter()
    for rows in per_run_rows:
        for r in rows:
            if r["hit"]:
                continue
            if r["actual"] == "MISSING":
                decomp["extraction_miss"] += 1
            elif r["code_matched"] is False:
                decomp["coding_miss"] += 1
            else:
                decomp["reconciler_miss"] += 1

    trap_runs: list[float] = []
    for traps in per_run_traps:
        if not traps:
            continue
        trap_runs.append(sum(1 for t in traps if t["rejected"]) / len(traps))
    trap_rate = {
        "mean": _avg(trap_runs) if trap_runs else None,
        "min": min(trap_runs) if trap_runs else None,
        "max": max(trap_runs) if trap_runs else None,
    }

    prov_total = 0
    prov_with = 0
    for rows in per_run_rows:
        for r in rows:
            if r["expected"] == "DUPLICATE" or r["actual"] == "MISSING":
                continue
            prov_total += 1
            if r["provenance_count"] > 0:
                prov_with += 1
    provenance = prov_with / prov_total if prov_total else None

    return {
        "n_runs": n_runs,
        "consistency_threshold": threshold,
        "total_facts": total_facts,
        "overall_accuracy": overall,
        "consistency_at_80pct": consistency,
        "code_accuracy": code_accuracy,
        "per_system_accuracy": per_system,
        "per_class_accuracy": per_class,
        "per_tier_accuracy": per_tier,
        "trap_rejection": trap_rate,
        "provenance_coverage": provenance,
        "stability": {
            "stable_right": stable_right,
            "flaky": flaky,
            "stable_wrong": stable_wrong,
        },
        "stable_wrong_cases": stable_wrong_cases,
        "hit_rate_distribution": dict(hit_rate_buckets),
        "misclassification_decomposition": dict(decomp),
        "confusion_matrix": {a: dict(confusion[a]) for a in ACTIONS},
    }


def render_charts(summary, out_dir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    n = summary["n_runs"]

    cm = np.zeros((len(ACTIONS), len(ACTUAL_AXIS)), dtype=int)
    for i, a in enumerate(ACTIONS):
        for j, b in enumerate(ACTUAL_AXIS):
            cm[i, j] = summary["confusion_matrix"][a].get(b, 0)
    fig, ax = plt.subplots(figsize=(8, 5), dpi=100)
    ax.imshow(cm, cmap="Reds", aspect="auto")
    for i in range(len(ACTIONS)):
        for j in range(len(ACTUAL_AXIS)):
            row_total = cm[i].sum()
            pct_val = (cm[i, j] / row_total * 100) if row_total else 0.0
            color = "white" if (i == j and cm[i, j] > 0) else "black"
            ax.text(j, i, f"{cm[i, j]}\n{pct_val:.0f}%", ha="center", va="center",
                    color=color, fontsize=10)
    for i in range(len(ACTIONS)):
        if cm[i, i] > 0:
            ax.add_patch(plt.Rectangle((i - 0.5, i - 0.5), 1, 1, fill=False,
                                       edgecolor="#16a34a", lw=2))
    ax.set_xticks(range(len(ACTUAL_AXIS)))
    ax.set_xticklabels(ACTUAL_AXIS)
    ax.set_yticks(range(len(ACTIONS)))
    ax.set_yticklabels(ACTIONS)
    ax.set_xlabel("Pipeline classification")
    ax.set_ylabel("Expected action")
    fig.tight_layout()
    fig.savefig(out_dir / "confusion_matrix.png")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 5), dpi=100)
    means = [summary["per_class_accuracy"][a]["mean"] * 100 for a in ACTIONS]
    mins = [(summary["per_class_accuracy"][a]["min"] or 0) * 100 for a in ACTIONS]
    maxs = [(summary["per_class_accuracy"][a]["max"] or 0) * 100 for a in ACTIONS]
    err_lo = [m - lo for m, lo in zip(means, mins)]
    err_hi = [hi - m for m, hi in zip(means, maxs)]
    bars = ax.bar(ACTIONS, means, color="#475569", yerr=[err_lo, err_hi],
                  capsize=6, error_kw={"elinewidth": 1.2, "ecolor": "#0f172a"})
    overall_mean = summary["overall_accuracy"]["mean"] * 100
    ax.axhline(overall_mean, ls="--", color="#94a3b8", lw=1)
    ax.text(len(ACTIONS) - 0.5, overall_mean + 1.5, f"overall {overall_mean:.0f}%",
            ha="right", color="#475569", fontsize=9)
    ax.set_ylim(0, 110)
    ax.set_ylabel("Accuracy (%)")
    ax.set_xlabel("Expected classification")
    for bar, val in zip(bars, means):
        ax.text(bar.get_x() + bar.get_width() / 2, val + 3, f"{val:.0f}%",
                ha="center", fontsize=10)
    fig.tight_layout()
    fig.savefig(out_dir / "per_class_accuracy.png")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 5), dpi=100)
    buckets = list(range(n + 1))
    counts = [summary["hit_rate_distribution"].get(b, 0) for b in buckets]
    if n == 0:
        colors = ["#94a3b8"]
    elif n == 1:
        colors = ["#dc2626", "#16a34a"]
    else:
        colors = ["#dc2626"] + ["#94a3b8"] * (n - 1) + ["#16a34a"]
    ax.bar([f"{b}/{n}" for b in buckets], counts, color=colors)
    ax.set_xlabel("Runs correct")
    ax.set_ylabel("Number of facts")
    for i, c in enumerate(counts):
        if c > 0:
            ax.text(i, c + 0.3, str(c), ha="center", fontsize=10)
    fig.tight_layout()
    fig.savefig(out_dir / "consistency_histogram.png")
    plt.close(fig)


def _pct(v, d=0):
    if v is None:
        return "—"
    return f"{v * 100:.{d}f}%"


def _pct_range(d):
    if d is None or d.get("mean") is None:
        return "—"
    return f"{_pct(d['mean'])} [{_pct(d['min'])}, {_pct(d['max'])}]"


def render_report(summary, meta, out_dir, charts):
    n = summary["n_runs"]
    threshold = summary["consistency_threshold"]
    overall = summary["overall_accuracy"]
    code_acc = summary["code_accuracy"]
    trap = summary["trap_rejection"]
    prov = summary["provenance_coverage"]

    headline = (
        f"**{_pct(overall['mean'])} augmentation accuracy · "
        f"{_pct(summary['consistency_at_80pct'])} of facts correct in "
        f"≥{threshold} of {n} runs · "
        f"{_pct(prov)} provenance coverage**"
    )

    why = (
        f"Anamnesis turns unstructured clinical narrative into structured FHIR "
        f"augmentations a provider can review in seconds rather than minutes. "
        f"On this benchmark — {meta['n_notes']} multi-source notes against "
        f"{meta['n_fixtures']} patient charts — the pipeline correctly classifies "
        f"{_pct(overall['mean'])} of candidate facts: surfacing genuine new findings, "
        f"suppressing duplicates the chart already contains, flagging dose changes "
        f"that read as routine prose, and catching contradictions like a sulfa "
        f"allergy disclosed against an existing NKDA record. Every accepted change "
        f"writes back to FHIR with a Provenance resource pointing at the source "
        f"span — an audit trail manual chart review does not produce. The "
        f"hypothesis: faster pre-visit chart catch-up, fewer missed updates, and a "
        f"record of *why* every structured fact entered the chart."
    )

    headline_table = (
        "| Metric | Value |\n"
        "|---|---|\n"
        f"| Augmentation accuracy | {_pct_range(overall)} |\n"
        f"| Consistency (correct in ≥{threshold}/{n} runs) | {_pct(summary['consistency_at_80pct'])} |\n"
        f"| Code accuracy | {_pct(code_acc)} |\n"
        f"| Trap rejection | {_pct_range(trap)} |\n"
        f"| Provenance coverage | {_pct(prov)} |\n"
    )

    per_class_rows = []
    for a in ACTIONS:
        d = summary["per_class_accuracy"][a]
        per_class_rows.append(f"| {a} | {d['n']} | {_pct_range(d)} |")
    per_class_table = (
        "| Class | Facts | Accuracy |\n|---|---|---|\n" + "\n".join(per_class_rows)
    )

    per_tier_rows = []
    for tier in TIERS:
        d = summary["per_tier_accuracy"].get(tier)
        if d is None:
            continue
        per_tier_rows.append(f"| {tier} | {_pct_range(d)} |")
    per_tier_table = (
        "| Tier | Accuracy |\n|---|---|\n" + "\n".join(per_tier_rows)
        if per_tier_rows else "_(no tier breakdown available)_"
    )

    per_system_rows = []
    for s in SYSTEMS:
        v = summary["per_system_accuracy"].get(s)
        if v is None:
            continue
        per_system_rows.append(f"| {s} | {_pct(v)} |")
    per_system_table = (
        "| System | Accuracy |\n|---|---|\n" + "\n".join(per_system_rows)
        if per_system_rows else "_(no per-system data)_"
    )

    decomp = summary["misclassification_decomposition"]
    decomp_total = sum(decomp.values())
    decomp_labels = {
        "extraction_miss": "Extraction miss (fact never reached pipeline)",
        "coding_miss": "Coding miss (right fact, wrong code)",
        "reconciler_miss": "Reconciler miss (right fact, right code, wrong class)",
    }
    decomp_rows = []
    for k, v in sorted(decomp.items(), key=lambda kv: -kv[1]):
        share = v / decomp_total if decomp_total else 0.0
        decomp_rows.append(f"| {decomp_labels.get(k, k)} | {v} | {share * 100:.0f}% |")
    decomp_table = (
        "| Source | Errors | Share |\n|---|---|---|\n" + "\n".join(decomp_rows)
        if decomp_rows else "_No errors observed._"
    )

    stab = summary["stability"]
    flaky_label = f"Flaky (1..{n - 1} correct)" if n > 1 else "Flaky"
    stab_table = (
        "| Bucket | Facts |\n|---|---|\n"
        f"| Stable-right (correct in {n}/{n} runs) | {stab['stable_right']} |\n"
        f"| {flaky_label} | {stab['flaky']} |\n"
        f"| Stable-wrong (0/{n} correct) | {stab['stable_wrong']} |\n"
    )

    sw_rows = []
    for c in summary["stable_wrong_cases"]:
        sw_rows.append(
            f"| `{c['fact_id']}` | {c['expected']} | {c['always_actual']} | "
            f"`{json.dumps(c['distribution'])}` |"
        )
    sw_table = (
        "| Fact | Expected | Always classified as | Distribution |\n"
        "|---|---|---|---|\n" + "\n".join(sw_rows)
        if sw_rows else "_None — every fact was correctly classified in at least one run._"
    )

    confusion_md = "\n![Confusion matrix](confusion_matrix.png)\n" if charts else ""
    per_class_md = "\n![Per-class accuracy](per_class_accuracy.png)\n" if charts else ""
    consistency_md = "\n![Consistency histogram](consistency_histogram.png)\n" if charts else ""

    body = f"""# Anamnesis augmentation benchmark — {meta['date']}

{headline}

## Why this matters

{why}

## What was tested

{meta['n_notes']} clinical notes (cardiology, ED, neurology) × {meta['n_fixtures']} FHIR chart fixtures × {meta['n_facts_per_run']} labeled facts × {n} runs. Notes span clean / messy / trap difficulty tiers. All evaluation labels are checked into the repo at `benchmarks/eval-corpus-v1/`.

## Headline

{headline_table}

## Per-class accuracy

{per_class_table}
{per_class_md}

## Confusion matrix

Cells aggregate counts across all {n} runs ({n} × {meta['n_facts_per_run']} = {n * meta['n_facts_per_run']} classifications). Rows = expected, columns = actual. The `MISSING` column captures facts the pipeline failed to extract or surface as a candidate.
{confusion_md}

## Consistency

Per-fact hit rate across {n} runs. The `{n}/{n}` bar is the production-ready set; the `0/{n}` bar is stable-wrong.
{consistency_md}

## Code accuracy by terminology

Of facts the pipeline extracted, what fraction included an acceptable code from the labeled `expected_codes`. Per-system rows count any fact whose expected codes include that system.

{per_system_table}

## Per-tier robustness

{per_tier_table}

## Where errors come from

Each misclassified fact traces to one of three pipeline stages.

{decomp_table}

## Stability

{stab_table}

### Stable-wrong cases

{sw_table}

## Reproduce

```bash
git clone <repo> && cd anamnesis
export OPENAI_API_KEY=sk-...
python benchmarks/eval-corpus-v1/run_demo_benchmark.py --runs {n}
```

## Run metadata

- Model: `{meta['model']}`
- Runs: {n}
- Wall time: {meta['wall_seconds']:.0f}s
- Pipeline sha: `{meta['git_sha']}`
- Prompt version: `{meta['prompt_version']}`
- Generated: {meta['date']}
"""
    (out_dir / "REPORT.md").write_text(body, encoding="utf-8")


def get_meta(model, only):
    import subprocess
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=str(REPO),
        ).decode().strip()
    except Exception:
        sha = "unknown"
    try:
        from core.prompts import PROMPT_VERSION
        prompt_version = PROMPT_VERSION
    except Exception:
        prompt_version = "unknown"
    pairs = list(load_pairs(only))
    fixtures = {p[1]["paired_bundle"] for p in pairs}
    facts_per_run = sum(len(p[1]["expected_actions"]) for p in pairs)
    return {
        "model": model,
        "git_sha": sha,
        "prompt_version": prompt_version,
        "n_notes": len(pairs),
        "n_fixtures": len(fixtures),
        "n_facts_per_run": facts_per_run,
    }


def _to_jsonable(o):
    if isinstance(o, set):
        return sorted(o)
    raise TypeError(f"not jsonable: {type(o)}")


async def main():
    args = parse_args()
    only = {x.strip() for x in args.only.split(",")} if args.only else None
    if not settings.openai_api_key:
        print("ERROR: OPENAI_API_KEY not set", file=sys.stderr)
        return 2

    meta = get_meta(settings.openai_model_fast, only)
    if meta["n_notes"] == 0:
        print("ERROR: no notes matched filter", file=sys.stderr)
        return 2

    if not confirm_cost(args.runs, meta["n_notes"], accept_default=args.yes):
        print("Aborted.")
        return 1

    out_dir = Path(args.output) if args.output else (
        ROOT / "results" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Writing artifacts to: {out_dir}")

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    per_run_rows: list[list[dict]] = []
    per_run_traps: list[list[dict]] = []
    started = time.monotonic()
    for run_idx in range(args.runs):
        print(f"\n=== run {run_idx + 1}/{args.runs} ===", flush=True)
        if run_idx > 0 and not args.keep_cache:
            clear_pipeline_caches()
        rows, _spurious, traps = await run_full_pass(only, client)
        per_run_rows.append(rows)
        per_run_traps.append(traps)
    wall_seconds = time.monotonic() - started

    summary = aggregate(per_run_rows, per_run_traps, args.runs)
    meta["wall_seconds"] = wall_seconds
    meta["date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    (out_dir / "raw_runs.json").write_text(
        json.dumps({"runs": per_run_rows, "traps": per_run_traps, "meta": meta},
                   indent=2, default=_to_jsonable) + "\n",
        encoding="utf-8",
    )
    (out_dir / "summary.json").write_text(
        json.dumps({**summary, "meta": meta}, indent=2, default=_to_jsonable) + "\n",
        encoding="utf-8",
    )

    if not args.no_charts:
        try:
            render_charts(summary, out_dir)
        except ImportError:
            print("WARN: matplotlib not installed; skipping charts.", file=sys.stderr)
            args.no_charts = True

    render_report(summary, meta, out_dir, charts=not args.no_charts)

    print()
    print(f"Augmentation accuracy:  {summary['overall_accuracy']['mean'] * 100:.1f}%  "
          f"[{summary['overall_accuracy']['min'] * 100:.1f}, "
          f"{summary['overall_accuracy']['max'] * 100:.1f}]")
    print(f"Consistency (≥{summary['consistency_threshold']}/{args.runs}): "
          f"{summary['consistency_at_80pct'] * 100:.1f}%")
    if summary["code_accuracy"] is not None:
        print(f"Code accuracy:          {summary['code_accuracy'] * 100:.1f}%")
    if summary["trap_rejection"]["mean"] is not None:
        print(f"Trap rejection:         {summary['trap_rejection']['mean'] * 100:.1f}%")
    if summary["provenance_coverage"] is not None:
        print(f"Provenance coverage:    {summary['provenance_coverage'] * 100:.1f}%")
    print(f"\nReport: {out_dir / 'REPORT.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
