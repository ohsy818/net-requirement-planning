"""net-requirement-planning 진입점.

두 단계를 순서대로 돌리고 결과를 하나로 합친다.

  phase1-requirement  현재고 ↔ 기준재고 대조 → 소요량·긴급도·과잉
  phase2-reconciliation  미결 공급 차감 → 순소요량·분류

phase2는 phase1이 낸 소요량을 그대로 받는다. 재계산하지 않는다.

사용법
  python run.py --input data.json --params params.json [--output out.json]

입력(data.json)
  {
    "on_hand":        [{"item_code","qty","uom","location","item_name","category"}],
    "stock_policy":   [{"item_code","reorder_point","target_level","uom"}],
    "last_issue_date": {"품목": "ISO날짜"},        (선택)
    "open_supply":    [{"doc_ref","item_code","ordered_qty","received_qty",
                        "state","eta","supplier","kind"}],   (선택)
    "need_by":        {"품목": "ISO날짜"}          (선택)
  }

파라미터(params.json) — 단계별로 나눠서 넣는다
  {"requirement": {...}, "reconciliation": {...}}
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
P1 = os.path.join(HERE, "phase1-requirement", "calculate.py")
P2 = os.path.join(HERE, "phase2-reconciliation", "reconcile.py")


def _run(script: str, data: dict, params: dict) -> dict:
    with tempfile.TemporaryDirectory() as d:
        di = os.path.join(d, "in.json")
        pi = os.path.join(d, "params.json")
        json.dump(data, open(di, "w", encoding="utf-8"), ensure_ascii=False)
        json.dump(params or {}, open(pi, "w", encoding="utf-8"), ensure_ascii=False)
        r = subprocess.run([sys.executable, script, "--input", di, "--params", pi],
                           capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"{os.path.basename(script)} 실패\n{r.stderr}")
    return json.loads(r.stdout)


def plan(data: dict, params: dict) -> dict:
    params = params or {}

    # ── phase 1 ────────────────────────────────────────────────
    req = _run(P1, {
        "on_hand": data.get("on_hand", []),
        "stock_policy": data.get("stock_policy", []),
        "last_issue_date": data.get("last_issue_date", {}),
    }, params.get("requirement", {}))

    # ── phase 1 → phase 2 인계 ─────────────────────────────────
    # 소요량을 그대로 넘긴다. 여기서 값을 바꾸면 두 단계의 답이 어긋난다.
    requirements = [{
        "item_code": s["item_code"],
        "item_name": s.get("item_name", ""),
        "required_qty": s["required_qty"],
        "urgency": s.get("urgency", "low"),
    } for s in req["shortage_items"]]

    on_hand_map: dict[str, float] = {}
    for row in data.get("on_hand", []):
        on_hand_map[row["item_code"]] = on_hand_map.get(row["item_code"], 0) + row["qty"]

    reorder_map = {p["item_code"]: p["reorder_point"] for p in data.get("stock_policy", [])}

    rec = _run(P2, {
        "requirements": requirements,
        "open_supply": data.get("open_supply", []),
        "on_hand": on_hand_map,
        "reorder_point": reorder_map,
        "need_by": data.get("need_by", {}),
    }, params.get("reconciliation", {}))

    # ── 검산 ───────────────────────────────────────────────────
    assert len(rec["net_requirements"]) == len(requirements), \
        "소요 품목 수와 대사 결과 수가 다르다"
    for n in rec["net_requirements"]:
        src = next(r for r in requirements if r["item_code"] == n["item_code"])
        assert abs(n["required_qty"] - src["required_qty"]) < 1e-9, \
            f"{n['item_code']}: 대사 단계가 소요량을 바꿨다"

    return {
        "requirement": req,
        "reconciliation": rec,
        # 프로세스가 바로 쓰는 값
        "order_candidates": rec["order_candidates"],
        "has_order_candidates": rec["has_order_candidates"],
        "disposition_summary": rec["disposition_summary"],
        "notes": req.get("notes", []) + rec.get("notes", []),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="현재고와 미결 공급을 함께 보고 순소요량을 낸다")
    ap.add_argument("--input", required=True)
    ap.add_argument("--params")
    ap.add_argument("--output")
    a = ap.parse_args()

    data = json.load(open(a.input, encoding="utf-8"))
    params = json.load(open(a.params, encoding="utf-8")) if a.params else {}

    out = json.dumps(plan(data, params), ensure_ascii=False, indent=2)
    if a.output:
        open(a.output, "w", encoding="utf-8").write(out)
        print(f"wrote {a.output}")
    else:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
