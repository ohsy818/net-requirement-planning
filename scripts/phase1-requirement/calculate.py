#!/usr/bin/env python3
"""현재고를 기준재고와 대조해 소요량·긴급도·과잉을 산출한다.

규칙은 reference/calculation-rules.md 와 일대일 대응한다.
규칙을 고치면 이 파일과 그 문서를 함께 고친다.

사용:
    python calculate.py --input data.json --params params.json --output result.json
    python calculate.py --input data.json            # 결과를 stdout 으로
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, datetime

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from schema import (  # noqa: E402
    ExcessItem, Input, Params, Result, ShortageItem, UndeterminedItem,
    UNDETERMINED_REASONS,
)

ACTIONS = {
    "no_policy": "재주문점·목표재고 설정",
    "inverted_policy": "기준값 정정",
    "unit_mismatch": "unit_conversion 에 환산 계수 추가",
    "negative_on_hand": "재고 실사",
}


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    return datetime.fromisoformat(str(s)[:10]).date()


def _convert(qty: float, from_uom: str, to_uom: str, table: dict[str, float]):
    """단위 환산. 계수가 없으면 None 을 돌려준다 (임의 환산 금지)."""
    if not to_uom or from_uom == to_uom:
        return qty
    factor = table.get(f"{from_uom}->{to_uom}")
    if factor is not None:
        return qty * factor
    inverse = table.get(f"{to_uom}->{from_uom}")
    if inverse:
        return qty / inverse
    return None


def calculate(data: Input, params: Params) -> Result:
    as_of = _parse_date(params.as_of) or date.today()
    policy = {p.item_code: p for p in data.stock_policy}
    result = Result()

    if not data.on_hand and not data.stock_policy:
        raise ValueError(
            "입력이 비어 있다. 조회 결과 0건이면 중단하고 범위 재확인을 요청할 것 "
            "(reference/edge-cases.md 중단 조건)"
        )

    # --- 1. 현재고 집계 --------------------------------------------------
    buckets: dict[tuple[str, str], dict] = {}
    for row in data.on_hand:
        key = (row.item_code, "" if params.aggregate_locations else row.location)
        b = buckets.setdefault(key, {
            "item_code": row.item_code, "item_name": row.item_name,
            "category": row.category, "location": key[1],
            "qty_by_uom": defaultdict(float), "rows": 0,
        })
        b["qty_by_uom"][row.uom] += row.qty
        b["rows"] += 1
        b["item_name"] = b["item_name"] or row.item_name
        b["category"] = b["category"] or row.category
        result.on_hand_snapshot.append({
            "item_code": row.item_code, "item_name": row.item_name,
            "location": row.location, "qty": row.qty, "uom": row.uom,
        })

    merged = sum(b["rows"] - 1 for b in buckets.values() if b["rows"] > 1)
    if merged:
        result.notes.append(f"중복 행 {merged}건을 합산했다")

    # 기준재고는 있는데 현재고 기록이 없는 품목 → 0 으로 채운다
    for code, pol in policy.items():
        if not any(k[0] == code for k in buckets):
            buckets[(code, "")] = {
                "item_code": code, "item_name": "", "category": "", "location": "",
                "qty_by_uom": defaultdict(float, {pol.uom: 0.0}), "rows": 0,
                "no_record": True,
            }

    # --- 2~7. 품목별 판정 -------------------------------------------------
    # aggregate_locations=False 이면 한 품목이 위치 수만큼 판정 단위가 된다.
    # 검산은 「품목」이 아니라 「판정 단위」 기준으로 한다.
    seen: set[tuple[str, str]] = set()
    classified: list[tuple[str, str]] = []
    for (code, _loc), b in sorted(buckets.items()):
        unit_key = (code, _loc)
        pol = policy.get(code)
        flags: list[str] = []
        if b.get("no_record"):
            flags.append("no_stock_record")

        # 단위 정규화
        target_uom = (pol.uom if pol and pol.uom else next(iter(b["qty_by_uom"]), ""))
        on_hand = 0.0
        bad_unit = False
        for uom, qty in b["qty_by_uom"].items():
            conv = _convert(qty, uom, target_uom, params.unit_conversion)
            if conv is None:
                bad_unit = True
                break
            on_hand += conv

        def undetermined(reason: str, detail: str = ""):
            seen.add(unit_key)
            classified.append(unit_key)
            result.undetermined_items.append(UndeterminedItem(
                item_code=code, reason=reason,
                detail=detail or UNDETERMINED_REASONS[reason],
                action=ACTIONS[reason],
            ))

        if bad_unit:
            undetermined("unit_mismatch",
                         f"{sorted(b['qty_by_uom'])} → {target_uom} 환산 계수 없음")
            continue
        if on_hand < 0:
            undetermined("negative_on_hand", f"현재고 {on_hand}")
            continue
        if pol is None:
            undetermined("no_policy")
            continue
        if pol.reorder_point > pol.target_level:
            undetermined("inverted_policy",
                         f"재주문점 {pol.reorder_point} > 목표재고 {pol.target_level}")
            continue

        seen.add(unit_key)
        name = b["item_name"]

        if on_hand < pol.reorder_point:                      # shortage
            required = pol.target_level - on_hand
            if b["category"] and b["category"] in params.critical_categories:
                urgency = "critical"
            elif on_hand == 0:
                urgency = "critical"
            elif on_hand < pol.reorder_point * params.medium_ratio:
                urgency = "medium"
            else:
                urgency = "low"
            if required == pol.target_level:
                flags.append("완전 결품")
            result.shortage_items.append(ShortageItem(
                item_code=code, item_name=name, on_hand=on_hand,
                reorder_point=pol.reorder_point, target_level=pol.target_level,
                required_qty=required, urgency=urgency, uom=target_uom, flags=flags,
            ))
            classified.append(unit_key)
        elif on_hand > pol.target_level:                      # excess
            issued = _parse_date(data.last_issue_date.get(code))
            is_stale = None
            if params.stale_days is not None and issued is not None:
                is_stale = (as_of - issued).days > params.stale_days
            result.excess_items.append(ExcessItem(
                item_code=code, item_name=name, on_hand=on_hand,
                target_level=pol.target_level,
                excess_qty=on_hand - pol.target_level,
                last_issue_date=data.last_issue_date.get(code), is_stale=is_stale,
            ))
            classified.append(unit_key)
            if on_hand > pol.target_level * 2:
                result.notes.append(f"{code}: 목표재고의 2배 초과 보유. 과잉 발주 이력 의심")
        else:                                                  # normal
            if on_hand <= pol.reorder_point * params.watch_ratio:
                result.watch_items.append({
                    "item_code": code, "item_name": name, "on_hand": on_hand,
                    "reorder_point": pol.reorder_point, "uom": target_uom,
                })

    result.has_shortage = bool(result.shortage_items)

    # --- 이상 신호 --------------------------------------------------------
    total = len(seen)
    if total:
        if len(result.shortage_items) / total > 0.30:
            result.notes.append(
                f"미달 품목 비율 {len(result.shortage_items)/total:.0%}. "
                "기준재고가 현실과 맞는지 재검토 권고")
        if len(result.undetermined_items) / total > 0.10:
            result.notes.append(
                f"판정 불가 비율 {len(result.undetermined_items)/total:.0%}. "
                "마스터 데이터 정비 필요")
    if params.defaults_used():
        result.notes.append("기본값 사용: " + ", ".join(params.defaults_used()))

    _verify(result, total, classified)
    return result


def _verify(result: Result, total: int, classified: list) -> None:
    """reference/calculation-rules.md 「검산」 절.

    검산 단위는 「판정 단위」다. aggregate_locations=False 이면
    한 품목이 위치 수만큼의 판정 단위로 쪼개진다.
    """
    counted = (len(result.shortage_items) + len(result.excess_items)
               + len(result.undetermined_items))
    assert counted == len(classified), f"분류 누락: {counted} != {len(classified)}"
    assert counted <= total, f"분류 총합 초과: {counted} > {total}"

    dup = {k for k in classified if classified.count(k) > 1}
    assert not dup, f"한 판정 단위가 두 유형에 들어갔다: {sorted(dup)}"

    bad = [i.item_code for i in result.shortage_items if i.required_qty <= 0]
    assert not bad, f"소요량이 0 이하인 shortage: {bad}"
    bad = [i.item_code for i in result.excess_items if i.excess_qty <= 0]
    assert not bad, f"과잉량이 0 이하인 excess: {bad}"
    assert result.has_shortage == bool(result.shortage_items), "has_shortage 불일치"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True)
    ap.add_argument("--params")
    ap.add_argument("--output")
    a = ap.parse_args()

    data = Input.from_dict(json.load(open(a.input, encoding="utf-8")))
    params = Params.from_dict(
        json.load(open(a.params, encoding="utf-8")) if a.params else None)

    out = json.dumps(calculate(data, params).to_dict(), ensure_ascii=False, indent=2)
    if a.output:
        open(a.output, "w", encoding="utf-8").write(out)
        print(f"wrote {a.output}")
    else:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
