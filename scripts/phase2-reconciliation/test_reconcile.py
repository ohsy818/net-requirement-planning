"""reconcile.py 분류 테스트.  실행: pytest -q

분류가 이 스킬의 산출물이므로, 테스트도 분류 중심이다.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from reconcile import reconcile                                    # noqa: E402
from schema import (CONFIRMED, Input, OpenSupplyLine, Params,      # noqa: E402
                    Requirement, UNCONFIRMED)

P = Params(as_of="2026-08-11")


def build(reqs, supply=(), on_hand=None, rop=None, need_by=None):
    return Input(requirements=list(reqs), open_supply=list(supply),
                 on_hand=on_hand or {}, reorder_point=rop or {},
                 need_by=need_by or {})


def disp(result, code):
    return next(n.disposition for n in result.net_requirements if n.item_code == code)


# ---------------------------------------------------------------- 네 갈래
def test_미결이_없으면_주문_대상():
    r = reconcile(build([Requirement("A", 56)], on_hand={"A": 4}, rop={"A": 20}), P)
    assert disp(r, "A") == "order"
    assert r.net_requirements[0].net_required_qty == 56
    assert r.has_order_candidates is True


def test_확정_미입고가_커버하면_대사_제외():
    r = reconcile(build(
        [Requirement("A", 11)],
        [OpenSupplyLine("PO1", "A", 8, state=CONFIRMED, eta="2026-08-20")],
        on_hand={"A": 1}, rop={"A": 4}), P)
    assert disp(r, "A") == "covered"


def test_지연된_건은_독촉_대상이지_주문이_아니다():
    r = reconcile(build(
        [Requirement("A", 2)],
        [OpenSupplyLine("PO7", "A", 1, state=CONFIRMED, eta="2026-06-27")],
        on_hand={"A": 0}, rop={"A": 1}), P)
    assert disp(r, "A") == "expedite"
    assert r.expedite_items[0].delay_days == 45
    assert r.has_order_candidates is False


def test_미확정_건만_있으면_확정_필요():
    r = reconcile(build(
        [Requirement("A", 6)],
        [OpenSupplyLine("PO9", "A", 4, state=UNCONFIRMED, eta="2026-08-25")],
        on_hand={"A": 0}, rop={"A": 2}), P)
    assert disp(r, "A") == "confirm_existing"
    assert r.confirm_pending_items[0]["docs"] == ["PO9"]


def test_분류_순서_지연이_확정필요보다_우선():
    """미확정이면서 지연된 건 → 독촉이 먼저."""
    r = reconcile(build(
        [Requirement("A", 5)],
        [OpenSupplyLine("PO1", "A", 5, state=UNCONFIRMED, eta="2026-07-01")],
        on_hand={"A": 0}, rop={"A": 3}), P)
    assert disp(r, "A") == "expedite"


def test_확정건이_있으면_미확정_혼재라도_확정필요가_아니다():
    r = reconcile(build(
        [Requirement("A", 10)],
        [OpenSupplyLine("PO1", "A", 8, state=CONFIRMED, eta="2026-08-20"),
         OpenSupplyLine("PO2", "A", 2, state=UNCONFIRMED, eta="2026-08-25")],
        on_hand={"A": 0}, rop={"A": 5}), P)
    assert disp(r, "A") == "covered"


# ---------------------------------------------------------------- 수량 계산
def test_부분입고는_잔량만_센다():
    r = reconcile(build(
        [Requirement("A", 10)],
        [OpenSupplyLine("PO1", "A", ordered_qty=10, received_qty=6,
                        state=CONFIRMED, eta="2026-08-20")],
        on_hand={"A": 6}, rop={"A": 16}), P)
    n = r.net_requirements[0]
    assert n.open_qty == 4 and n.net_required_qty == 6


def test_소요량을_재계산하지_않는다():
    """현재고가 이상해도 입력 소요량을 그대로 쓴다."""
    r = reconcile(build([Requirement("A", 99)], on_hand={"A": 500}, rop={"A": 1}), P)
    assert r.net_requirements[0].required_qty == 99


def test_잔량이_소요량보다_크면_과잉_주문_이력():
    r = reconcile(build(
        [Requirement("A", 5)],
        [OpenSupplyLine("PO1", "A", 20, state=CONFIRMED, eta="2026-08-20")],
        on_hand={"A": 0}, rop={"A": 5}), P)
    assert r.net_requirements[0].net_required_qty == 0
    assert "과잉 주문 이력 의심" in r.net_requirements[0].flags


def test_취소_완료_건은_미결이_아니다():
    r = reconcile(build(
        [Requirement("A", 10)],
        [OpenSupplyLine("PO1", "A", 10, state="cancelled", eta="2026-08-20"),
         OpenSupplyLine("PO2", "A", 10, state="done")],
        on_hand={"A": 0}, rop={"A": 10}), P)
    assert disp(r, "A") == "order" and r.net_requirements[0].open_qty == 0


def test_미확정_제외_설정():
    data = build([Requirement("A", 6)],
                 [OpenSupplyLine("PO9", "A", 4, state=UNCONFIRMED, eta="2026-08-25")],
                 on_hand={"A": 0}, rop={"A": 2})
    off = reconcile(data, Params(as_of="2026-08-11", include_unconfirmed=False))
    assert off.net_requirements[0].open_qty == 0
    assert disp(off, "A") == "confirm_existing"   # 분류는 그대로


# ---------------------------------------------------------------- 예외
def test_예정일_없으면_보수적으로_제외하지_않는다():
    d = build([Requirement("A", 10)],
              [OpenSupplyLine("PO1", "A", 10, state=CONFIRMED, eta=None)],
              on_hand={"A": 0}, rop={"A": 10})
    cons = reconcile(d, Params(as_of="2026-08-11"))
    assert "missing_eta" in cons.net_requirements[0].flags
    assert disp(cons, "A") == "covered"           # 순소요 0 이므로
    opt = reconcile(d, Params(as_of="2026-08-11", missing_eta_policy="optimistic"))
    assert "missing_eta" not in opt.net_requirements[0].flags


def test_결품_위험_플래그():
    r = reconcile(build(
        [Requirement("A", 10)],
        [OpenSupplyLine("PO1", "A", 10, state=CONFIRMED, eta="2026-09-30")],
        on_hand={"A": 0}, rop={"A": 10}, need_by={"A": "2026-08-20"}), P)
    assert disp(r, "A") == "covered"
    assert "결품 위험" in r.net_requirements[0].flags
    assert len(r.stockout_risk) == 1


def test_소요목록에_없는_미결건은_별도_보고():
    r = reconcile(build(
        [Requirement("A", 10)],
        [OpenSupplyLine("PO1", "B", 5, state=CONFIRMED, eta="2026-08-20")],
        on_hand={"A": 0}, rop={"A": 10}), P)
    assert r.unmatched_supply[0]["item_code"] == "B"
    assert len(r.net_requirements) == 1


def test_미결_0건도_명시한다():
    r = reconcile(build([Requirement("A", 5)], on_hand={"A": 0}, rop={"A": 5}), P)
    assert any("미결 공급 건 0건" in n for n in r.notes)


def test_분류_합계는_입력_품목수와_같다():
    reqs = [Requirement(c, 10) for c in "ABCDE"]
    supply = [OpenSupplyLine("PO1", "B", 10, state=CONFIRMED, eta="2026-08-20"),
              OpenSupplyLine("PO2", "C", 10, state=CONFIRMED, eta="2026-06-01"),
              OpenSupplyLine("PO3", "D", 10, state=UNCONFIRMED, eta="2026-08-25")]
    r = reconcile(build(reqs, supply, on_hand={c: 0 for c in "ABCDE"},
                        rop={c: 10 for c in "ABCDE"}), P)
    assert sum(r.disposition_summary.values()) == 5
    assert r.disposition_summary == {
        "order": 2, "covered": 1, "expedite": 1, "confirm_existing": 1}


def test_알수없는_파라미터는_거부한다():
    with pytest.raises(ValueError, match="알 수 없는 파라미터"):
        Params.from_dict({"expedite_threshold_days": 3, "oops": 1})


def test_잘못된_missing_eta_policy는_거부한다():
    with pytest.raises(ValueError, match="conservative"):
        Params.from_dict({"missing_eta_policy": "whatever"})
