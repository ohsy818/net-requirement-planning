"""net-requirement-planning phase1 입출력 형식.

이 스킬은 특정 시스템을 전제하지 않는다.
호출하는 쪽이 어떤 소스에서 읽든, 아래 형식으로 정규화해서 넘긴다.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


# ----------------------------------------------------------------- 입력
@dataclass
class OnHandRow:
    """품목 × 위치별 현재고 한 줄."""
    item_code: str
    qty: float
    uom: str
    location: str = ""
    item_name: str = ""
    category: str = ""


@dataclass
class StockPolicy:
    """품목별 기준재고."""
    item_code: str
    reorder_point: float      # 하한. 이 밑으로 떨어지면 소요 발생
    target_level: float       # 상한. 여기까지 채운다
    uom: str = ""


@dataclass
class Params:
    critical_categories: list[str] = field(default_factory=list)
    medium_ratio: float = 0.5
    watch_ratio: float = 1.2
    stale_days: int | None = None
    unit_conversion: dict[str, float] = field(default_factory=dict)
    aggregate_locations: bool = True
    as_of: str | None = None          # ISO 날짜. 없으면 오늘

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "Params":
        d = dict(d or {})
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(d) - known
        if unknown:
            raise ValueError(f"알 수 없는 파라미터: {sorted(unknown)}")
        return cls(**d)

    def defaults_used(self) -> list[str]:
        """기본값 그대로 쓴 항목. 리포트에 밝혀야 한다."""
        base = Params()
        return [f for f in self.__dataclass_fields__
                if getattr(self, f) == getattr(base, f)]


@dataclass
class Input:
    on_hand: list[OnHandRow]
    stock_policy: list[StockPolicy]
    last_issue_date: dict[str, str] = field(default_factory=dict)   # item_code -> ISO 날짜

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Input":
        return cls(
            on_hand=[OnHandRow(**r) for r in d.get("on_hand", [])],
            stock_policy=[StockPolicy(**r) for r in d.get("stock_policy", [])],
            last_issue_date=d.get("last_issue_date", {}) or {},
        )


# ----------------------------------------------------------------- 출력
DISPOSITIONS = ("shortage", "normal", "excess", "undetermined")

UNDETERMINED_REASONS = {
    "no_policy": "기준재고 미설정",
    "inverted_policy": "재주문점 > 목표재고 (기준값 역전)",
    "unit_mismatch": "단위 환산 계수 없음",
    "negative_on_hand": "현재고 음수",
}

URGENCY = ("critical", "medium", "low")


@dataclass
class ShortageItem:
    item_code: str
    item_name: str
    on_hand: float
    reorder_point: float
    target_level: float
    required_qty: float
    urgency: str
    uom: str = ""
    flags: list[str] = field(default_factory=list)


@dataclass
class ExcessItem:
    item_code: str
    item_name: str
    on_hand: float
    target_level: float
    excess_qty: float
    last_issue_date: str | None = None
    is_stale: bool | None = None


@dataclass
class UndeterminedItem:
    item_code: str
    reason: str          # UNDETERMINED_REASONS 의 키
    detail: str = ""
    action: str = ""


@dataclass
class Result:
    shortage_items: list[ShortageItem] = field(default_factory=list)
    watch_items: list[dict] = field(default_factory=list)
    excess_items: list[ExcessItem] = field(default_factory=list)
    undetermined_items: list[UndeterminedItem] = field(default_factory=list)
    on_hand_snapshot: list[dict] = field(default_factory=list)
    has_shortage: bool = False
    notes: list[str] = field(default_factory=list)   # 기본값 사용, 이상 신호 등

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
