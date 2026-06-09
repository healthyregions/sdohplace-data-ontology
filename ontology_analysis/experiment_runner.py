"""
For ACM HPDC26 poster: Run 30 queries through 4 configurations against the chat-search edge function.

Configurations:
  A1: ontology_context=off,            model=M1   (LLM-only baseline)
  A2: ontology_context=deterministic,  model=M1   (strict symbolic, production default)
  A3: ontology_context=prompt,         model=M1   (bounded LLM-grounded selection)
  B2: ontology_context=deterministic,  model=M2   (deterministic mode, model swap)

  (Optional 5th arm B3 = deterministic+M2 swapped to prompt+M2 can be added
   later by changing one config tuple. Keep at 4 to fit the timeline.)

Total: 30 × 4 = 120 calls.

Usage:
    python3 experiment_runner.py \\
        --endpoint http://localhost:8888/chat-search \\
        --queries queries.csv \\
        --m1 gpt-4o \\
        --m2 gpt-4o-mini \\
        --out results.jsonl
"""

import argparse
import csv
import json
import time
import urllib.request
import urllib.error


def run_one(endpoint, question, ontology_mode, model, exp_id, timeout=90):
    payload = {
        "question": question,
        "ontology_context": ontology_mode,  # off | deterministic | prompt
        "exp_id": exp_id,
    }
    if model:
        payload["model"] = model

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp_body = json.loads(r.read().decode("utf-8"))
        dt = time.time() - t0
        return {"ok": True, "client_latency_s": dt, "body": resp_body}
    except urllib.error.HTTPError as e:
        dt = time.time() - t0
        try:
            err_body = e.read().decode("utf-8")
        except Exception:
            err_body = str(e)
        return {"ok": False, "client_latency_s": dt, "status": e.code, "error": err_body}
    except Exception as e:
        dt = time.time() - t0
        return {"ok": False, "client_latency_s": dt, "error": str(e)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", required=True)
    ap.add_argument("--queries", default="queries.csv")
    ap.add_argument("--m1", default="gpt-4o", help="primary model")
    ap.add_argument("--m2", default="gpt-4o-mini", help="alternate model for Arm B")
    ap.add_argument("--out", default="results.jsonl")
    ap.add_argument("--exp_id", default="hpdc26_v1")
    ap.add_argument("--sleep", type=float, default=1.0)
    ap.add_argument("--limit", type=int, default=None, help="run only first N queries (for smoke testing)")
    args = ap.parse_args()

    with open(args.queries) as f:
        rows = list(csv.DictReader(f))
    if args.limit:
        rows = rows[: args.limit]

    configs = [
        ("A1", "off",           args.m1),   # was None
        ("A2", "deterministic", args.m1),   # was None
        ("A3", "prompt",        args.m1),   # was None
        ("B2", "deterministic", args.m2),
    ]

    n_total = len(rows) * len(configs)
    n_done = 0
    n_failed = 0

    with open(args.out, "w") as out:
        for row in rows:
            qid = row["query_id"]
            qtext = row["query_text"]
            for arm_label, ont_mode, model in configs:
                exp_id = f"{args.exp_id}_{qid}_{arm_label}"
                n_done += 1
                print(f"[{n_done}/{n_total}] {qid} | {arm_label} ({ont_mode}) | {qtext[:50]}...")
                res = run_one(args.endpoint, qtext, ont_mode, model, exp_id)
                if not res["ok"]:
                    n_failed += 1
                    print(f"   FAILED: {str(res.get('error', 'unknown'))[:120]}")
                rec = {
                    "query_id": qid,
                    "query_text": qtext,
                    "branch": row["ontology_branch"],
                    "specificity": row["specificity"],
                    "uses_ontology_term_directly": row["uses_ontology_term_directly"],
                    "expected_ontology_terms": row.get("expected_ontology_terms", ""),
                    "arm": arm_label,
                    "ontology_mode": ont_mode,
                    "model_requested": model or args.m1,
                    "result": res,
                }
                out.write(json.dumps(rec) + "\n")
                out.flush()
                time.sleep(args.sleep)

    print(f"\nDone. {n_done} calls, {n_failed} failures. Results in {args.out}")


if __name__ == "__main__":
    main()
