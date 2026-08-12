#!/usr/bin/env python3
"""소요량에서 미결 공급 물량을 차감하고 네 갈래로 분류한다.

규칙은 reference/reconciliation-rules.md 와 일대일 대응한다.
분류 순서(5절)를 바꾸면 중복 주문이 난다. 순서를 유지할 것.

사용:
    python reconcile.py --input data.json --params params.json --output result.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, datetime

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from schema import (  # noqa: E402
    CONFIRMED, DISPOSITIONS, ExpediteItem, Input, NetRequirement, Params,
    Result, TERMINAL_STATES, UNCONFIRMED,
)


def _d(s: str | None) -> date | None:
    return datetime.fromisoformat(str(s)[:10]).date() if s else None


def reconcile(data: Input, params: Params) -> Result:
    as_of = _d(params.as_of) or date.today()
    result = Result()

    # --- 1. 미결 물량 집계 -------------------------------------------------
    states = [s for s in params.open_states if s not in TERMINAL_STATES]
    by_item: dict[str, list] = defaultdict(list)
    for ln in data.open_supply:
        if ln.state not in states:
            continue
        remaining = max(ln.ordered_qty - ln.received_qty, 0.0)
        eta = _d(ln.eta)
        delay = (as_of - eta).days if eta else None
        rec = {
            "doc_ref": ln.doc_ref, "item_code": ln.item_code, "state": ln.state,
            "ordered_qty": ln.ordered_qty, "received_qty": ln.received_qty,
            "open_qty": remaining, "eta": ln.eta, "delay_days": delay,
            "supplier": ln.supplier, "kind": ln.kind,
            "counts_toward_qty": remaining > 0 and (
                ln.state != UNCONFIRMED or params.include_unconfirmed),
        }
        by_item[ln.item_code].append(rec)
        result.open_supply_lines.append(rec)

    req_codes = {r.item_code for r in data.requirements}
    for code, lines in by_item.items():
        if code not in req_codes:
            result.unmatched_supply.append({
                "item_code": code,
                "open_qty": sum(l["open_qty"] for l in lines),
                "docs": [l["doc_ref"] for l in lines],
                "note": "소요 판정에 없는 품목에 미결 건이 있다. 부족 판정 누락 여부 확인",
            })

    # --- 2~6. 품목별 대사 --------------------------------------------------
    for req in data.requirements:
        lines = by_item.get(req.item_code, [])
        open_qty = sum(l["open_qty"] for l in lines if l["counts_toward_qty"])
        net = max(req.required_qty - open_qty, 0.0)
        on_hand = data.on_hand.get(req.item_code, 0.0)
        rop = data.reorder_point.get(req.item_code, 0.0)
        flags: list[str] = []

        # 제외 판정에 쓸 잔량 (예정일 없는 건은 보수적으로 제외)
        if params.missing_eta_policy == "conservative":
            trust_qty = sum(l["open_qty"] for l in lines
                            if l["counts_toward_qty"] and l["eta"])
            if any(l["counts_toward_qty"] and not l["eta"] for l in lines):
                flags.append("missing_eta")
        else:
            trust_qty = open_qty
        covered = (on_hand + trust_qty) >= rop if lines else False

        delayed = [l for l in lines
                   if l["delay_days"] is not None
                   and l["delay_days"] > params.delay_threshold_days]
        to_expedite = [l for l in delayed
                       if l["delay_days"] >= params.expedite_threshold_days]
        unconfirmed_only = bool(lines) and all(
            l["state"] == UNCONFIRMED for l in lines)

        earliest = sorted([l["eta"] for l in lines if l["eta"]])
        eta = earliest[0] if earliest else None

        # --- 5. 분류 결정 순서. 순서를 바꾸지 말 것 -------------------------
        if to_expedite:
            disp, reason = "expedite", (
                f"미결 {len(to_expedite)}건이 {max(l['delay_days'] for l in to_expedite)}일 지연. "
                "새 주문이 아니라 독촉 대상")
            for l in to_expedite:
                result.expedite_items.append(ExpediteItem(
                    doc_ref=l["doc_ref"], item_code=l["item_code"],
                    supplier=l["supplier"], open_qty=l["open_qty"],
                    eta=l["eta"], delay_days=l["delay_days"]))
        elif unconfirmed_only:
            disp, reason = "confirm_existing", (
                f"미확정 건 {len(lines)}건({', '.join(l['doc_ref'] for l in lines)})만 존재. "
                "새 주문이 아니라 기존 건 확정")
            result.confirm_pending_items.append({
                "item_code": req.item_code, "item_name": req.item_name,
                "docs": [l["doc_ref"] for l in lines], "open_qty": open_qty})
        elif covered:
            disp, reason = "covered", (
                f"현재고 {on_hand} + 미입고 잔량 {trust_qty} ≥ 재주문점 {rop}")
        elif net > 0:
            disp, reason = "order", (
                f"미결 잔량 {open_qty} 차감 후 순소요 {net}" if lines else "미결 없음")
        else:
            disp, reason = "covered", "순소요 0 (잔량이 소요량을 덮음)"

        if open_qty > req.required_qty and req.required_qty > 0:
            flags.append("과잉 주문 이력 의심")
            result.notes.append(
                f"{req.item_code}: 미결 잔량 {open_qty} > 소요량 {req.required_qty}")

        # --- 6. 결품 위험 ---------------------------------------------------
        need = _d(data.need_by.get(req.item_code))
        first_eta = _d(eta)
        if on_hand == 0 and disp != "order":
            if first_eta is None or (need and first_eta > need):
                flags.append("결품 위험")
                result.stockout_risk.append({
                    "item_code": req.item_code, "item_name": req.item_name,
                    "on_hand": on_hand, "eta": eta,
                    "need_by": data.need_by.get(req.item_code),
                    "disposition": disp})

        result.net_requirements.append(NetRequirement(
            item_code=req.item_code, item_name=req.item_name,
            required_qty=req.required_qty, open_qty=open_qty,
            net_required_qty=net, disposition=disp, reason=reason,
            eta=eta, urgency=req.urgency, flags=flags))

        if disp == "order":
            result.order_candidates.append({
                "item_code": req.item_code, "item_name": req.item_name,
                "net_required_qty": net, "urgency": req.urgency})

    result.disposition_summary = {
        d: sum(1 for n in result.net_requirements if n.disposition == d)
        for d in DISPOSITIONS}
    result.has_order_candidates = bool(result.order_candidates)

    if not data.open_supply:
        result.notes.append("미결 공급 건 0건. 소요량 = 순소요량")
    if not params.include_unconfirmed:
        result.notes.append("미확정 건을 잔량에서 제외하고 계산했다")
    if params.defaults_used():
        result.notes.append("기본값 사용: " + ", ".join(params.defaults_used()))

    _verify(result, data, by_item)
    return result


def _verify(result: Result, data: Input, by_item: dict) -> None:
    """reference/reconciliation-rules.md 「검산」 절."""
    assert len(result.net_requirements) == len(data.requirements), "분류 누락"

    codes = [n.item_code for n in result.net_requirements]
    dup = {c for c in codes if codes.count(c) > 1}
    assert not dup, f"한 품목이 두 번 분류됐다: {sorted(dup)}"

    assert sum(result.disposition_summary.values()) == len(data.requirements), \
        "분류 합계 불일치"

    for n in result.net_requirements:
        assert n.net_required_qty >= 0, f"{n.item_code}: 순소요 음수"
        assert n.disposition in DISPOSITIONS, f"{n.item_code}: 알 수 없는 분류"
        if n.disposition == "order":
            assert n.net_required_qty > 0, f"{n.item_code}: order 인데 순소요 0"
        expected = sum(l["open_qty"] for l in by_item.get(n.item_code, [])
                       if l["counts_toward_qty"])
        assert abs(n.open_qty - expected) < 1e-9, f"{n.item_code}: 잔량 불일치"

    assert result.has_order_candidates == bool(
        result.disposition_summary["order"]), "has_order_candidates 불일치"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True)
    ap.add_argument("--params")
    ap.add_argument("--output")
    a = ap.parse_args()

    data = Input.from_dict(json.load(open(a.input, encoding="utf-8")))
    params = Params.from_dict(
        json.load(open(a.params, encoding="utf-8")) if a.params else None)

    out = json.dumps(reconcile(data, params).to_dict(), ensure_ascii=False, indent=2)
    if a.output:
        open(a.output, "w", encoding="utf-8").write(out)
        print(f"wrote {a.output}")
    else:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
