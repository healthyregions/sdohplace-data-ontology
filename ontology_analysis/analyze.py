"""
For ACM HPDC26 poster: it compute metrics from results.jsonl produced by experiment_runner.py for the 4-arm
three-mode experiment (off, deterministic, prompt + model swap on deterministic).

Arms:
  A1: off,            M1
  A2: deterministic,  M1   (production)
  A3: prompt,         M1
  B2: deterministic,  M2

Key metrics:
  1. Vocabulary uptake: fraction of keyTerms matching OWL ontology terms
  2. Expected-term recall: did the response surface any expected ontology terms?
  3. Cross-arm Jaccard divergence
  4. A2 vs B2 stability: same input under deterministic mode, different model

Usage:
    python3 analyze.py --in results.jsonl --owl /path/to/ontology.owl \\
        --queries queries.csv --out_summary summary.json --out_fig figure_results.png
"""

import argparse
import csv
import json
import re
from collections import defaultdict
from statistics import mean, median, StatisticsError


def load_ontology_terms(owl_path):
    try:
        import rdflib
        from rdflib.namespace import OWL, RDFS, RDF, SKOS
    except ImportError:
        print("rdflib not installed; pip install rdflib")
        return set()

    g = rdflib.Graph()
    g.parse(owl_path, format="xml")
    terms = set()
    for c in g.subjects(RDF.type, OWL.Class):
        for label in g.objects(c, RDFS.label):
            terms.add(normalize(str(label)))
        for alt in g.objects(c, SKOS.altLabel):
            terms.add(normalize(str(alt)))
    terms.discard("")
    return terms


def normalize(s):
    s = s.lower().strip()
    s = re.sub(r"[-_]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s


def term_matches_ontology(term, ontology_terms):
    nt = normalize(term)
    if not nt:
        return False
    if nt in ontology_terms:
        return True
    nt_words = set(nt.split())
    for ot in ontology_terms:
        ot_words = set(ot.split())
        if nt_words and nt_words.issubset(ot_words):
            return True
        if ot_words and ot_words.issubset(nt_words):
            return True
    return False


def expected_terms_hit(returned_terms, expected_csv):
    if not expected_csv:
        return None
    expected = [normalize(t) for t in expected_csv.split(",") if t.strip()]
    returned_norm = [normalize(t) for t in returned_terms]
    for e in expected:
        e_words = set(e.split())
        for r in returned_norm:
            r_words = set(r.split())
            if e_words & r_words:
                return 1
    return 0


def extract_signals(body):
    """Extract keyTerms list, suggestedQueries list, and metadata from response."""
    if not isinstance(body, dict):
        return [], [], None, None, None

    inner = body.get("body") if "body" in body else body
    if not isinstance(inner, dict):
        return [], [], None, None, None

    key_terms = []
    for kt in inner.get("keyTerms", []):
        if isinstance(kt, dict) and "term" in kt:
            key_terms.append(kt["term"].strip())
        elif isinstance(kt, str):
            key_terms.append(kt.strip())

    suggested = []
    for sq in inner.get("suggestedQueries", []):
        if isinstance(sq, str):
            m = re.search(r"q=([^&]+)", sq)
            if m:
                from urllib.parse import unquote
                suggested.append(unquote(m.group(1)).strip())
            else:
                suggested.append(sq.strip())

    exp = inner.get("_experiment", {}) or {}
    prompt_tokens = exp.get("prompt_tokens")
    completion_tokens = exp.get("completion_tokens")

    latency_ms = None
    if "client_latency_s" in body:
        latency_ms = body["client_latency_s"] * 1000.0

    return key_terms, suggested, latency_ms, prompt_tokens, completion_tokens


def jaccard_divergence(a, b):
    sa, sb = set(normalize(x) for x in a), set(normalize(x) for x in b)
    if not sa and not sb:
        return 0.0
    return 1.0 - len(sa & sb) / len(sa | sb)


def safe_mean(xs):
    xs = [x for x in xs if x is not None]
    try:
        return mean(xs) if xs else None
    except StatisticsError:
        return None


def safe_median(xs):
    xs = [x for x in xs if x is not None]
    try:
        return median(xs) if xs else None
    except StatisticsError:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="results.jsonl")
    ap.add_argument("--owl", required=True, help="Path to OWL ontology file")
    ap.add_argument("--queries", default="queries.csv")
    ap.add_argument("--out_summary", default="summary.json")
    ap.add_argument("--out_fig", default="figure_results.png")
    args = ap.parse_args()

    print(f"Loading ontology terms from {args.owl}...")
    ontology_terms = load_ontology_terms(args.owl)
    print(f"  {len(ontology_terms)} ontology terms loaded")

    expected_per_query = {}
    with open(args.queries) as f:
        for row in csv.DictReader(f):
            expected_per_query[row["query_id"]] = row.get("expected_ontology_terms", "")

    records = defaultdict(dict)
    with open(args.inp) as f:
        for line in f:
            r = json.loads(line)
            records[r["query_id"]][r["arm"]] = r

    arms = ["A1", "A2", "A3", "B2"]
    metrics = []
    for qid, rec_arms in records.items():
        if not all(a in rec_arms for a in arms):
            print(f"Skipping {qid}: missing arms ({list(rec_arms.keys())})")
            continue
        if not all(rec_arms[a]["result"].get("ok") for a in arms):
            print(f"Skipping {qid}: failed call in one or more arms")
            continue

        signals = {a: extract_signals(rec_arms[a]["result"]) for a in arms}
        kt = {a: signals[a][0] for a in arms}  # keyTerms per arm
        sq = {a: signals[a][1] for a in arms}  # suggestedQueries per arm
        lat = {a: signals[a][2] for a in arms}
        ptokens = {a: signals[a][3] for a in arms}
        ctokens = {a: signals[a][4] for a in arms}

        def uptake(terms):
            if not terms:
                return None
            return sum(1 for t in terms if term_matches_ontology(t, ontology_terms)) / len(terms)

        expected_csv = expected_per_query.get(qid, "")

        m = {
            "query_id": qid,
            "branch": rec_arms["A1"]["branch"],
            "specificity": rec_arms["A1"]["specificity"],
            "expected_csv": expected_csv,

            # Vocabulary uptake per arm
            **{f"uptake_{a}": uptake(kt[a]) for a in arms},

            # Expected-term recall per arm
            **{f"expected_hit_{a}": expected_terms_hit(kt[a], expected_csv) for a in arms},

            # Cross-arm Jaccard divergence (keyTerms)
            "jaccard_kt_A1_A2": jaccard_divergence(kt["A1"], kt["A2"]),
            "jaccard_kt_A1_A3": jaccard_divergence(kt["A1"], kt["A3"]),
            "jaccard_kt_A2_A3": jaccard_divergence(kt["A2"], kt["A3"]),
            "jaccard_kt_A2_B2": jaccard_divergence(kt["A2"], kt["B2"]),  # headline: deterministic across models

            # Cross-arm Jaccard divergence (suggestedQueries)
            "jaccard_sq_A1_A2": jaccard_divergence(sq["A1"], sq["A2"]),
            "jaccard_sq_A1_A3": jaccard_divergence(sq["A1"], sq["A3"]),
            "jaccard_sq_A2_A3": jaccard_divergence(sq["A2"], sq["A3"]),
            "jaccard_sq_A2_B2": jaccard_divergence(sq["A2"], sq["B2"]),

            # Stability under model swap (A2 vs B2): are keyTerms identical?
            "deterministic_stability": int(set(map(normalize, kt["A2"])) == set(map(normalize, kt["B2"]))) if kt["A2"] and kt["B2"] else None,

            # Latency / tokens per arm
            **{f"lat_{a}": lat[a] for a in arms},
            **{f"ptokens_{a}": ptokens[a] for a in arms},
            **{f"ctokens_{a}": ctokens[a] for a in arms},

            # Sample for inspection
            **{f"keyTerms_{a}": kt[a] for a in arms},
        }
        metrics.append(m)

    if not metrics:
        print("No usable records.")
        return

    summary = {
        "n_queries": len(metrics),

        # PRIMARY: vocabulary uptake per arm
        "ontology_vocabulary_uptake": {
            "A1_off": safe_mean([m["uptake_A1"] for m in metrics]),
            "A2_deterministic_M1": safe_mean([m["uptake_A2"] for m in metrics]),
            "A3_prompt_M1": safe_mean([m["uptake_A3"] for m in metrics]),
            "B2_deterministic_M2": safe_mean([m["uptake_B2"] for m in metrics]),
        },

        # Expected-term recall per arm
        "expected_term_recall": {
            "A1": safe_mean([m["expected_hit_A1"] for m in metrics]),
            "A2": safe_mean([m["expected_hit_A2"] for m in metrics]),
            "A3": safe_mean([m["expected_hit_A3"] for m in metrics]),
            "B2": safe_mean([m["expected_hit_B2"] for m in metrics]),
        },

        # HEADLINE: deterministic mode stability across model swap
        "deterministic_stability_A2_vs_B2": safe_mean([m["deterministic_stability"] for m in metrics]),

        # Cross-arm divergence
        "jaccard_keyTerms": {
            "A1_vs_A2_baseline_vs_deterministic": safe_mean([m["jaccard_kt_A1_A2"] for m in metrics]),
            "A1_vs_A3_baseline_vs_prompt": safe_mean([m["jaccard_kt_A1_A3"] for m in metrics]),
            "A2_vs_A3_deterministic_vs_prompt": safe_mean([m["jaccard_kt_A2_A3"] for m in metrics]),
            "A2_vs_B2_deterministic_model_swap": safe_mean([m["jaccard_kt_A2_B2"] for m in metrics]),
        },
        "jaccard_suggestedQueries": {
            "A1_vs_A2": safe_mean([m["jaccard_sq_A1_A2"] for m in metrics]),
            "A1_vs_A3": safe_mean([m["jaccard_sq_A1_A3"] for m in metrics]),
            "A2_vs_A3": safe_mean([m["jaccard_sq_A2_A3"] for m in metrics]),
            "A2_vs_B2": safe_mean([m["jaccard_sq_A2_B2"] for m in metrics]),
        },

        "latency_ms": {
            **{f"mean_{a}": safe_mean([m[f"lat_{a}"] for m in metrics]) for a in arms},
            **{f"median_{a}": safe_median([m[f"lat_{a}"] for m in metrics]) for a in arms},
        },
        "tokens_per_query": {
            **{f"mean_prompt_{a}": safe_mean([m[f"ptokens_{a}"] for m in metrics]) for a in arms},
            **{f"mean_completion_{a}": safe_mean([m[f"ctokens_{a}"] for m in metrics]) for a in arms},
        },
    }

    with open(args.out_summary, "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))

    # Save sample diffs
    sample_path = args.out_summary.replace(".json", "_samples.txt")
    with open(sample_path, "w") as f:
        f.write("Sample per-query keyTerms across arms (for paper §3 illustration)\n")
        f.write("=" * 70 + "\n\n")
        for m in metrics[:15]:
            f.write(f"[{m['query_id']}] {m['branch']} ({m['specificity']})\n")
            f.write(f"  expected: {m['expected_csv']}\n")
            f.write(f"  A1 (off):           {m['keyTerms_A1']}  uptake={m['uptake_A1']}\n")
            f.write(f"  A2 (deterministic): {m['keyTerms_A2']}  uptake={m['uptake_A2']}\n")
            f.write(f"  A3 (prompt):        {m['keyTerms_A3']}  uptake={m['uptake_A3']}\n")
            f.write(f"  B2 (det. + M2):     {m['keyTerms_B2']}  uptake={m['uptake_B2']}\n")
            f.write("\n")
    print(f"\nSample diffs saved: {sample_path}")

    # Plot
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        fig, axes = plt.subplots(1, 3, figsize=(12, 3.4))

        # Panel 1: Vocabulary uptake
        ax = axes[0]
        labels = ["A1\noff", "A2\ndeterm.\nM1", "A3\nprompt\nM1", "B2\ndeterm.\nM2"]
        vals = [
            summary["ontology_vocabulary_uptake"]["A1_off"] or 0,
            summary["ontology_vocabulary_uptake"]["A2_deterministic_M1"] or 0,
            summary["ontology_vocabulary_uptake"]["A3_prompt_M1"] or 0,
            summary["ontology_vocabulary_uptake"]["B2_deterministic_M2"] or 0,
        ]
        colors = ["#888", "#2a9d8f", "#f4a261", "#264653"]
        bars = ax.bar(labels, vals, color=colors)
        ax.set_ylabel("Vocabulary uptake")
        ax.set_title("(a) Ontology vocabulary uptake")
        ax.set_ylim(0, 1.05)
        for bar, v in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width()/2, v + 0.02, f"{v:.2f}", ha="center", fontsize=9)

        # Panel 2: Latency
        ax = axes[1]
        arm_short = ["A1", "A2", "A3", "B2"]
        means = [summary["latency_ms"][f"mean_{a}"] or 0 for a in arm_short]
        ax.bar(arm_short, means, color=colors)
        ax.set_ylabel("Mean latency (ms)")
        ax.set_title("(b) End-to-end latency")

        # Panel 3: Cross-arm Jaccard
        ax = axes[2]
        comparisons = ["A1↔A2", "A1↔A3", "A2↔A3", "A2↔B2"]
        jvals = [
            summary["jaccard_keyTerms"]["A1_vs_A2_baseline_vs_deterministic"] or 0,
            summary["jaccard_keyTerms"]["A1_vs_A3_baseline_vs_prompt"] or 0,
            summary["jaccard_keyTerms"]["A2_vs_A3_deterministic_vs_prompt"] or 0,
            summary["jaccard_keyTerms"]["A2_vs_B2_deterministic_model_swap"] or 0,
        ]
        bars = ax.bar(comparisons, jvals, color=["#888", "#888", "#f4a261", "#264653"])
        ax.set_ylabel("Mean Jaccard divergence (keyTerms)")
        ax.set_title("(c) Cross-arm divergence")
        ax.set_ylim(0, 1.05)
        for bar, v in zip(bars, jvals):
            ax.text(bar.get_x() + bar.get_width()/2, v + 0.02, f"{v:.2f}", ha="center", fontsize=9)

        plt.tight_layout()
        plt.savefig(args.out_fig, dpi=200, bbox_inches="tight")
        print(f"Figure saved: {args.out_fig}")
    except ImportError:
        print("matplotlib not installed; skipping figure")


if __name__ == "__main__":
    main()
