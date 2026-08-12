---
name: net-requirement-planning
description: |
  현재고를 기준재고(재주문점·목표재고)와 대조해 소요량과 긴급도를 산출하고, 이미 확보해 둔 미결 공급 물량
  (발주·생산지시·창고이동·위탁반입)을 차감해 순소요량을 낸다. 각 품목을 주문 대상 / 대사 제외 / 독촉 대상 /
  확정 필요로 분류해 중복 주문을 막고, 과잉·장기재고도 함께 탐지한다.
  다음과 같은 요청에 사용할 것 — "재고 점검해줘", "부족한 품목 뽑아줘", "재주문점 미달 확인", "뭘 얼마나 주문해야 하지",
  "이미 발주한 거 빼고 계산해줘", "중복 발주 안 나게", "순소요량 뽑아줘", "미입고 잔량 확인", "재주문 제안이 맞는지 검증",
  "납기 지난 발주 찾아줘", "독촉해야 할 건", "draft 발주 확정하면 되는 품목", "결품 위험 품목", "과잉·악성재고 찾아줘",
  "min-max 재고 점검", "창고별 재고 합쳐서 부족분 계산", "생산지시 걸린 자재 빼고 소요 계산".
  재고 스냅샷과 기준재고만 있으면 어떤 도메인에도 적용된다(소모품·원자재·의료소모품·매장 상품·예비부품).
  다음에는 사용하지 않는다 — 공급처·단가·납기 조회와 주문서 작성은 purchase-order-preparation.
  주문을 생성·확정·취소하거나 재고 데이터를 수정하는 것, 공급처에 독촉 연락을 하는 것은 이 스킬의 범위가 아니다.
---

# Net Requirement Planning

**지금 얼마나 모자란가, 그리고 그중 아직 확보하지 못한 것은 얼마인가.**
이 두 질문에 한 번에 답한다.

## 핵심 원칙

**읽기 전용이다.** 어떤 경우에도 재고나 주문 데이터를 쓰지 않는다.

**"모자라다"와 "그래서 사야 한다"는 다르다.** 보충 업무에서 가장 흔한 사고가 **중복 주문**이고,
원인은 언제나 이미 확보한 물량을 빼지 않은 것이다. 그래서 계산을 **두 단계로 나눠** 수행하고,
2단계가 실행됐는지 출력에서 확인할 수 있게 한다.

**2단계는 1단계의 소요량을 다시 계산하지 않는다.** 받은 값을 그대로 쓴다.
같은 계산을 두 곳에서 하면 결과가 어긋났을 때 어느 쪽이 맞는지 알 수 없다.
`scripts/run.py`가 이 인계를 검산하고, 값이 바뀌었으면 오류를 내고 멈춘다.

**분류가 산출물이다.** 순소요량 숫자보다 네 갈래 분류가 중요하다.
분류를 틀리면 중복 주문이 나거나 결품이 난다.

## 경계

| 한다 | 하지 않는다 |
|---|---|
| 현재고 집계, 위치 합산, 단위 정규화 | 공급처·단가·납기 조회 → `purchase-order-preparation` |
| 기준재고 대조, 소요량·긴급도 산출 | 주문수량 확정, 주문서 작성 → `purchase-order-preparation` |
| 과잉·장기재고 탐지 | **주문 생성·확정·취소** |
| 미결 공급 차감, 순소요량 산출 | 재고 데이터 수정, 재고 조정 전표 |
| 주문/제외/독촉/확정 필요 분류 | 공급처에 독촉 연락 |

## 워크플로

### 1. 입력 수집

| 항목 | 필수 | 내용 |
|---|---|---|
| `on_hand` | ● | 품목 × 위치별 수량·단위 |
| `stock_policy` | ● | 품목별 재주문점(하한) · 목표재고(상한) |
| `open_supply` | ○ | 미결 공급 건 — 없으면 순소요량 = 소요량 |
| `last_issue_date` | ○ | 최종 출고일 (장기재고 판정용) |
| `need_by` | ○ | 품목별 필요 시점 (결품 위험 판정용) |

**현재고 조회 결과가 0건이면 여기서 중단한다.** 빈 리포트를 내면 "부족 없음"으로 오해된다.

**`open_supply`는 주문 문서뿐 아니라 아직 재고에 반영되지 않은 모든 입고 예정 물량을 담는다.**
특히 **저장만 하고 검증하지 않은 입고 문서**를 빠뜨리지 말 것. 보유 수량은 늘지 않았지만
물건은 들어올 예정이다. 이것을 놓치는 것이 중복 주문의 가장 흔한 경로다.

### 2. 계산 실행

```bash
python scripts/run.py --input data.json --params params.json --output result.json
```

두 단계를 순서대로 돌리고 결과를 합쳐 낸다. 단계별로 따로 돌려도 된다.

```bash
python scripts/phase1-requirement/calculate.py  --input d.json --params p.json
python scripts/phase2-reconciliation/reconcile.py --input d.json --params p.json
```

파라미터는 호출하는 쪽이 준다. **기본값을 조직 기준이라고 가정하지 않는다.**
목록과 기본값은 `reference/parameters-phase1.md` · `parameters-phase2.md`.

스크립트를 실행할 수 없는 환경이면 `reference/calculation-rules.md`와
`reference/reconciliation-rules.md`의 규칙을 그대로 따른다. 같은 결과가 나와야 한다.

### 3. 결과 검토

`undetermined_items`(판정 불가)를 먼저 본다. 소요 목록에 섞지 말고 별도로 보고한다.
예외 처리는 `reference/edge-cases.md`, 분류 판단은 `reference/disposition-guide.md`.

**제외한 품목마다 제외 사유와 예정 입고일을 반드시 남긴다.** 사유 없는 제외는 결품으로 이어진다.

### 4. 리포트 작성

`templates/report-phase1.md`(재고·미달 판정)와 `templates/report-phase2.md`(대사)의
섹션 구조를 이어 붙여 하나의 리포트로 낸다.

## 판정 유형

**1단계 — 모든 입력 품목이 넷 중 정확히 하나**

| 유형 | 조건 |
|---|---|
| `shortage` 소요 발생 | 현재고 < 재주문점 |
| `normal` 정상 | 재주문점 ≤ 현재고 ≤ 목표재고 |
| `excess` 과잉 | 현재고 > 목표재고 |
| `undetermined` 판정 불가 | 기준 미설정 / 기준값 역전 / 단위 환산 불가 |

**2단계 — 모든 소요 품목이 넷 중 정확히 하나. 위에서부터 먼저 맞는 것을 적용한다**

| 순서 | 조건 | 분류 | 뜻 |
|---|---|---|---|
| 1 | 예정 납기를 임계일수 이상 초과한 미결 건 있음 | `expedite` 독촉 대상 | 오기로 했는데 안 온다 |
| 2 | 미확정 상태의 주문만 걸려 있음 | `confirm_existing` 확정 필요 | 사려다 말았다 |
| 3 | 현재고 + 미결 잔량 ≥ 재주문점 | `covered` 대사 제외 | 오고 있다 |
| 4 | 순소요량 > 0 | `order` 주문 대상 | 사야 한다 |

**`expedite`와 `confirm_existing`을 주문 대상에 넣지 않는다.** 이 두 오분류가 중복 주문의 대부분이다.

## 출력

| 필드 | 내용 |
|---|---|
| `requirement.shortage_items` | 품목 · 현재고 · 재주문점 · 목표재고 · **소요량** · 긴급도 |
| `requirement.watch_items` | 미달은 아니나 주의 임계 이하 |
| `requirement.excess_items` | 품목 · 과잉량 · 최종 출고일 · 장기 여부 |
| `requirement.undetermined_items` | 품목 · 사유 · 필요한 조치 |
| `requirement.on_hand_snapshot` | 품목 × 위치별 현재고 (근거) |
| `reconciliation.net_requirements` | 소요량 · 미결 잔량 · **순소요량** · 분류 · 사유 |
| `reconciliation.open_supply_lines` | 미결 건 내역 (근거) |
| `reconciliation.expedite_items` | 독촉 대상 — 지연일수 포함 |
| `reconciliation.confirm_pending_items` | 확정 필요 — 미확정 문서 참조 |
| `reconciliation.stockout_risk` | 대사 제외됐으나 도착이 늦어 결품 위험 |
| `reconciliation.unmatched_supply` | 소요 목록 밖의 미결 건 — 기준재고 누락 신호 |
| **`order_candidates`** | 최종 주문 대상 |
| **`has_order_candidates`** | boolean — 분기용 |

**필드 이름은 이 스킬이 정의하는 논리 이름이다.** 실제 폼·변수와의 연결은 호출하는 쪽이 매핑한다.

## 품질 체크리스트

- [ ] 여러 위치 재고를 합계로 판정했는가
- [ ] 판정 불가·과잉을 소요 목록과 분리했는가
- [ ] **미결 공급을 조회했는가** — 주문 문서뿐 아니라 미검증 입고 문서까지
- [ ] `expedite` · `confirm_existing`을 주문 대상에서 뺐는가
- [ ] 제외한 품목마다 사유와 예정 입고일을 남겼는가
- [ ] 계산을 스크립트로 했는가 (손계산 금지)
- [ ] 파라미터를 기본값 그대로 쓴 경우 그 사실을 보고했는가
- [ ] 재고·주문 데이터를 수정하지 않았는가

## 파일 구성

| 경로 | 언제 읽나 |
|---|---|
| `scripts/run.py` | **항상** — 두 단계를 순서대로 실행 |
| `reference/parameters-phase1.md` · `-phase2.md` | 설정값을 정하거나 확인할 때 |
| `reference/calculation-rules.md` | 소요량 계산을 검증할 때 |
| `reference/reconciliation-rules.md` | 대사 계산을 검증할 때 |
| `reference/disposition-guide.md` | 분류가 애매할 때 |
| `reference/edge-cases.md` | 판정 불가·이상 데이터가 나왔을 때 |
| `templates/report-phase1.md` · `-phase2.md` | 리포트를 쓸 때 |
| `scripts/phase*/test_*.py` | 스크립트를 고쳤을 때 |

## 프로세스에 붙일 때

1. **입력 연결** — 재고·기준재고·미결 공급을 어디서 읽을지 지정한다.
   미결 공급의 소스가 둘 이상이면(주문 문서 + 입고 문서) 모두 지정한다.
2. **파라미터 주입** — `reference/parameters-*.md`의 항목에 조직 기준값을 넣는다.
3. **출력 매핑** — 출력 필드를 폼 필드·프로세스 변수에 연결한다. 분기에는 `has_order_candidates`.
4. **받아 줄 곳 지정** — `expedite_items` · `confirm_pending_items` · `stockout_risk`를
   어느 단계가 처리할지 정한다. 갈 곳이 없으면 분류가 조치로 이어지지 않는다.

이 네 가지를 프로세스 쪽 문서에 표로 정리해 두면, 프로세스가 바뀌어도
이 스킬은 그대로 두고 매핑표만 고치면 된다.
