# 파라미터

| 파라미터 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `as_of` | 날짜 | 오늘 | 지연 판정의 기준일 |
| `open_states` | 문자열 배열 | `["unconfirmed","confirmed"]` | 미결로 볼 상태. 완료·취소는 항상 제외 |
| `include_unconfirmed` | boolean | `true` | 미확정 건을 잔량에 포함할지 |
| `delay_threshold_days` | 정수 | `0` | 예정일 초과 며칠부터 지연으로 볼지 |
| `expedite_threshold_days` | 정수 | `7` | 며칠 이상 지연부터 독촉 대상으로 올릴지 |
| `missing_eta_policy` | 문자열 | `"conservative"` | 예정일이 없을 때. `conservative`=제외 판정에 쓰지 않음, `optimistic`=정상으로 간주 |

## params.json 예

```json
{
  "as_of": "2026-08-11",
  "open_states": ["unconfirmed", "confirmed"],
  "include_unconfirmed": true,
  "delay_threshold_days": 0,
  "expedite_threshold_days": 7,
  "missing_eta_policy": "conservative"
}
```

## 파라미터를 정할 때 생각할 것

**`include_unconfirmed`**
가장 중요한 파라미터다. `true`면 미확정 건도 잔량에 넣어 중복 주문을 막지만,
그 건이 승인되지 않고 사라지면 결품이 난다.
그래서 잔량에 넣더라도 **분류는 「확정 필요」로 따로 뺀다.** 방치되지 않게 하는 장치다.

`false`로 두는 경우는 미확정 건이 실제로 자주 폐기되는 조직뿐이다.
그때는 중복 주문을 다른 방법으로 막아야 한다.

**`delay_threshold_days`**
0이면 예정일 하루만 지나도 지연이다. 공급처 납기가 원래 들쭉날쭉하면
0으로 두었을 때 지연 목록이 의미를 잃는다. 실제 납기 편차를 보고 정한다.

**`expedite_threshold_days`**
독촉이 실제로 효과가 나타나는 시점보다 짧아야 한다.
리드타임 45일짜리를 7일 지연에 독촉해 봐야 바뀌는 것이 없다면,
품목군별로 다른 값을 줘야 한다는 신호다.

**`missing_eta_policy`**
`conservative`가 기본이다. 예정일을 모르는 물량을 "곧 온다"고 보는 것이
가장 위험하다. 다만 이 경우 불필요한 주문이 생길 수 있으므로
**반드시 「예정일 확인 필요」 플래그를 남겨** 사람이 판단하게 한다.
