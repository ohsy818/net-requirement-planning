"""calculate.py 경계값 테스트.  실행: pytest -q"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from calculate import calculate                      # noqa: E402
from schema import Input, OnHandRow, Params, StockPolicy  # noqa: E402


def build(on_hand, policy, last_issue=None):
    return Input(on_hand=on_hand, stock_policy=policy, last_issue_date=last_issue or {})


def test_소요량은_목표재고까지_채운다():
    r = calculate(
        build([OnHandRow("A", 4, "EA")], [StockPolicy("A", 20, 60)]), Params())
    assert r.shortage_items[0].required_qty == 56
    assert r.has_shortage is True


def test_재주문점_경계는_미달이_아니다():
    r = calculate(
        build([OnHandRow("A", 20, "EA")], [StockPolicy("A", 20, 60)]), Params())
    assert r.shortage_items == []


def test_긴급도_분류():
    p = Params(critical_categories=["safety"], medium_ratio=0.5)
    data = build([
        OnHandRow("Z", 0, "EA"),                          # 재고 0 → critical
        OnHandRow("M", 4, "EA"),                          # 4 < 10*0.5 → medium
        OnHandRow("L", 8, "EA"),                          # 8 >= 5 → low
        OnHandRow("S", 9, "EA", category="safety"),       # 카테고리 → critical
    ], [StockPolicy(c, 10, 20) for c in ("Z", "M", "L", "S")])
    got = {i.item_code: i.urgency for i in calculate(data, p).shortage_items}
    assert got == {"Z": "critical", "M": "medium", "L": "low", "S": "critical"}


def test_위치_합산이_불필요한_주문을_막는다():
    rows = [OnHandRow("A", 6, "EA", location="W1"), OnHandRow("A", 8, "EA", location="W2")]
    pol = [StockPolicy("A", 10, 20)]
    assert calculate(build(rows, pol), Params(aggregate_locations=True)).shortage_items == []
    split = calculate(build(rows, pol), Params(aggregate_locations=False))
    assert len(split.shortage_items) == 2


def test_단위_환산_계수가_없으면_판정하지_않는다():
    data = build([OnHandRow("A", 3, "BOX")], [StockPolicy("A", 10, 20, uom="EA")])
    assert calculate(data, Params()).undetermined_items[0].reason == "unit_mismatch"
    ok = calculate(data, Params(unit_conversion={"BOX->EA": 10}))
    assert ok.shortage_items == []          # 30 EA → 미달 아님


@pytest.mark.parametrize("row,pol,reason", [
    (OnHandRow("A", 5, "EA"), None, "no_policy"),
    (OnHandRow("A", 5, "EA"), StockPolicy("A", 30, 10), "inverted_policy"),
    (OnHandRow("A", -2, "EA"), StockPolicy("A", 10, 20), "negative_on_hand"),
])
def test_판정불가_사유(row, pol, reason):
    r = calculate(build([row], [pol] if pol else []), Params())
    assert r.undetermined_items[0].reason == reason
    assert r.shortage_items == []           # 소요 목록에 섞이지 않는다


def test_기준재고만_있고_재고기록이_없으면_0으로_본다():
    r = calculate(build([], [StockPolicy("A", 10, 20)]), Params())
    assert r.shortage_items[0].required_qty == 20
    assert "no_stock_record" in r.shortage_items[0].flags


def test_과잉과_장기재고():
    data = build([OnHandRow("A", 11, "EA")], [StockPolicy("A", 3, 6)],
                 {"A": "2026-01-01"})
    r = calculate(data, Params(stale_days=180, as_of="2026-08-11"))
    assert r.excess_items[0].excess_qty == 5
    assert r.excess_items[0].is_stale is True
    assert r.has_shortage is False


def test_주의_품목은_미달이_아니다():
    r = calculate(build([OnHandRow("A", 11, "EA")], [StockPolicy("A", 10, 20)]),
                  Params(watch_ratio=1.2))
    assert r.shortage_items == [] and len(r.watch_items) == 1


def test_중복행은_합산된다():
    r = calculate(build([OnHandRow("A", 5, "EA"), OnHandRow("A", 6, "EA")],
                        [StockPolicy("A", 10, 20)]), Params())
    assert r.shortage_items == []
    assert any("중복 행" in n for n in r.notes)


def test_입력이_비면_중단한다():
    with pytest.raises(ValueError, match="0건"):
        calculate(build([], []), Params())


def test_알수없는_파라미터는_거부한다():
    with pytest.raises(ValueError, match="알 수 없는 파라미터"):
        Params.from_dict({"medium_ratio": 0.4, "typo_param": 1})


def test_기본값_사용을_보고한다():
    r = calculate(build([OnHandRow("A", 4, "EA")], [StockPolicy("A", 20, 60)]), Params())
    assert any("기본값 사용" in n for n in r.notes)
