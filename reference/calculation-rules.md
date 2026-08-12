# 계산 규칙

`scripts/calculate.py`가 구현하는 규칙이다.
스크립트를 실행할 수 없는 환경에서는 이 문서를 그대로 따른다. **같은 결과가 나와야 한다.**

## 1. 현재고 집계

품목코드 · 품목명 · 위치 · 수량 · 단위로 정규화한다.

```
aggregate_locations = true  →  판정용 현재고 = Σ(위치별 수량)
aggregate_locations = false →  위치별로 각각 판정
```

표에는 **언제나 위치별로 남긴다.** 합산은 판정에만 쓴다.

## 2. 단위 정규화

기준재고와 단위가 다르면 `unit_conversion`으로 환산한다.

```
환산 계수 = unit_conversion["<현재고 단위>-><기준 단위>"]
환산 수량 = 수량 × 계수
```

계수가 없으면 **환산하지 않고** 해당 품목을 `undetermined`(단위 확인 필요)로 보낸다.
**임의 환산 금지.** BOX가 10입인지 12입인지 추측하면 소요량이 통째로 틀린다.

## 3. 소요량·과잉량

```
미달 여부 : 현재고 < 재주문점
소요량    : 목표재고 − 현재고         (미달 품목만)
과잉량    : 현재고 − 목표재고         (초과 품목만)
```

**소수·음수를 0으로 자르지 않는다.** 그대로 표기한다. 데이터 오류의 단서다.

목표재고가 재주문점과 같으면 소요량은 `재주문점 − 현재고`가 된다. 정상 동작이다.

## 4. 긴급도

위에서부터 먼저 맞는 것을 적용한다.

```
1) 품목 카테고리 ∈ critical_categories   → critical
2) 현재고 == 0                            → critical
3) 현재고 < 재주문점 × medium_ratio       → medium
4) 그 외 미달 품목                        → low
```

## 5. 주의 품목

```
재주문점 ≤ 현재고 ≤ 재주문점 × watch_ratio  →  watch_items
```

미달이 아니므로 `shortage_items`에는 들어가지 않는다. 보고용이다.

## 6. 과잉·장기 판정

```
현재고 > 목표재고  →  excess_items

stale_days 가 설정돼 있고
(as_of − 최종 출고일) > stale_days      →  is_stale = true
```

`is_stale`인 과잉 품목이 처분 검토 우선순위가 높다.

## 7. 판정 유형 결정 순서

```
1) 판정 불가 조건에 걸리면          → undetermined   (edge-cases.md 참조)
2) 현재고 < 재주문점                → shortage
3) 현재고 > 목표재고                → excess
4) 그 외                            → normal
```

**`undetermined`를 가장 먼저 거른다.** 기준값이 이상한 품목을 소요 계산에 넣으면
숫자는 나오지만 의미가 없다.

## 검산

| 항목 | 성립해야 하는 식 |
|---|---|
| 분류 총합 | `len(shortage) + len(normal) + len(excess) + len(undetermined)` = 입력 품목 수 |
| 중복 없음 | 한 품목이 두 유형에 들어가지 않음 |
| 소요량 부호 | `shortage_items`의 소요량은 모두 > 0 |
| 과잉량 부호 | `excess_items`의 과잉량은 모두 > 0 |
| 플래그 일치 | `has_shortage` == (`len(shortage_items)` > 0) |

`scripts/calculate.py`는 이 검산을 실행하고, 하나라도 어긋나면 오류를 낸다.
