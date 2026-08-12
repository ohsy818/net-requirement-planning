"""net-requirement-planning phase2 입출력 형식."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

# 미결 공급 건의 상태. 시스템별 상태명은 호출하는 쪽이 여기로 매핑한다.
UNCONFIRMED = "unconfirmed"   # 초안·승인대기. 아직 공급처에 나가지 않음
CONFIRMED = "confirmed"       # 확정·미입고. 공급처가 받았고 오는 중
DONE = "done"                 # 완료. 이미 현재고에 반영됨
CANCELLED = "cancelled"       # 취소. 미결이 아님

TERMINAL_STATES = (DONE, CANCELLED)   # open_states 에 넣어도 항상 제외

DISPOSITIONS = ("order", "covered", "expedite", "confirm_existing")


# ----------------------------------------------------------------- 입력
@dataclass
class Requirement:
    """앞 단계(net-requirement-planning phase1)의 shortage_items 한 줄."""
    item_code: str
    required_qty: float
    urgency: str = "low"
    item_name: str = ""


@dataclass
class OpenSupplyLine:
    """미결 공급 건 한 줄. 발주·생산지시·창고이동 무엇이든 이 형식으로."""
    doc_ref: str
    item_code: str
    ordered_qty: float
    received_qty: float = 0.0
    state: str = CONFIRMED
    eta: str | None = None          # ISO 날짜. 없으면 None
    supplier: str = ""
    kind: str = "purchase"          # purchase / production / transfer / consignment


@dataclass
class Params:
    as_of: str | None = None
    open_states: list[str] = field(
        default_factory=lambda: [UNCONFIRMED, CONFIRMED])
    include_unconfirmed: bool = True
    delay_threshold_days: int = 0
    expedite_threshold_days: int = 7
    missing_eta_policy: str = "conservative"     # conservative | optimistic

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "Params":
        d = dict(d or {})
        unknown = set(d) - set(cls.__dataclass_fields__)
        if unknown:
            raise ValueError(f"알 수 없는 파라미터: {sorted(unknown)}")
        p = cls(**d)
        if p.missing_eta_policy not in ("conservative", "optimistic"):
            raise ValueError("missing_eta_policy 는 conservative 또는 optimistic")
        return p

    def defaults_used(self) -> list[str]:
        base = Params()
        return [f for f in self.__dataclass_fields__
                if getattr(self, f) == getattr(base, f)]


@dataclass
class Input:
    requirements: list[Requirement]
    open_supply: list[OpenSupplyLine] = field(default_factory=list)
    on_hand: dict[str, float] = field(default_factory=dict)        # item_code -> qty
    reorder_point: dict[str, float] = field(default_factory=dict)  # item_code -> qty
    need_by: dict[str, str] = field(default_factory=dict)          # item_code -> ISO 날짜

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Input":
        return cls(
            requirements=[Requirement(**r) for r in d.get("requirements", [])],
            open_supply=[OpenSupplyLine(**r) for r in d.get("open_supply", [])],
            on_hand=d.get("on_hand", {}) or {},
            reorder_point=d.get("reorder_point", {}) or {},
            need_by=d.get("need_by", {}) or {},
        )


# ----------------------------------------------------------------- 출력
@dataclass
class NetRequirement:
    item_code: str
    item_name: str
    required_qty: float
    open_qty: float
    net_required_qty: float
    disposition: str                       # DISPOSITIONS
    reason: str = ""
    eta: str | None = None
    urgency: str = "low"
    flags: list[str] = field(default_factory=list)


@dataclass
class ExpediteItem:
    doc_ref: str
    item_code: str
    supplier: str
    open_qty: float
    eta: str | None
    delay_days: int


@dataclass
class Result:
    net_requirements: list[NetRequirement] = field(default_factory=list)
    order_candidates: list[dict] = field(default_factory=list)
    open_supply_lines: list[dict] = field(default_factory=list)
    expedite_items: list[ExpediteItem] = field(default_factory=list)
    confirm_pending_items: list[dict] = field(default_factory=list)
    stockout_risk: list[dict] = field(default_factory=list)
    unmatched_supply: list[dict] = field(default_factory=list)
    disposition_summary: dict[str, int] = field(default_factory=dict)
    has_order_candidates: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
