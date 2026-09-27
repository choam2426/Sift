# A의 2차 Jev 묶음 평가 입출력 설계

> 상태: 2026-09-25 **실행 보류·재설계 대상**. CodeQL을 직접 호출 이웃 추출에만 사용한 입력은 [CodeQL 데이터베이스 기반 대안](codeql-evidence-proposal.md)과 비교해 다시 설계한다. 아래 JSON 구조·질문·응답 기록은 이전 제안이며 2차 호출에 사용하도록 확정하지 않았다. [이전 입력](input-v1.md)의 `target` 중심 질문과 상태도 채점에 사용하지 않는다.

| 단계 | 받는 자료 | 만드는 자료 |
|---|---|---|
| 묶음 생성 | 1차 통과 함수·원본 본문·확인된 직접 호출 | 중복 없는 `states.jsonl`, 묶음별 `groups.jsonl`, 출발 함수 대응 `origins.jsonl` |
| Jev 채점 | 묶음 하나의 `state`와 단일 질문 | 묶음별 `Noul` 원시 응답과 실행 기록 `responses.jsonl` |
| 순위화 | 정상 응답과 묶음 ID | 점수순 묶음 목록, 미평가 목록; 3차는 묶음의 원래 코드·관계를 조회 |

## 평가 대상과 생성

1차를 통과한 함수는 **묶음 생성의 출발점**이다. 한 출발 함수와 선택된 관련 함수·관계를 포함한 묶음 하나가 2차 점수의 대상이다. 출발 함수는 모델 입력에서 특별한 평가 대상으로 표시하지 않는다. 함수가 하나만 남으면 그 함수 하나로 이루어진 묶음을 평가한다.

첫 A 기준선은 [ADR 0006](../../docs/adr/0006-codeql-source-relation-experiment.md)에 따라 원본 호출 위치가 확인된 직접 호출 관계만 사용한다. 출발 함수에서 한 관계 단계로 연결된 모든 함수의 전체 본문을 포함하고, 포함된 함수들 사이에서 확인된 직접 호출 관계도 모두 넣는다. 크기에 따른 선택·제외·본문 절단은 하지 않는다. 관계를 입증하지 못한 호출은 입력 밖의 실행 기록에 남긴다.

## Jev 요청

`state`는 함수 목록과 그 사이의 관계로 구성한다. 아래 코드 문자열은 설명을 위해 줄였으며 실제 요청에는 원본 함수 **전체 본문**을 넣는다.

```json
{
  "functions": [
    {
      "key": "F1",
      "file": "C/XzDec.c",
      "start_line": 580,
      "end_line": 785,
      "symbol": "MixCoder_Code",
      "code": "<원본 전체 코드>"
    },
    {
      "key": "F2",
      "file": "C/XzDec.c",
      "start_line": 1015,
      "end_line": 1369,
      "symbol": "XzUnpacker_Code",
      "code": "<원본 전체 코드>"
    }
  ],
  "relations": [
    {
      "kind": "direct_call",
      "from": "F2",
      "to": "F1",
      "evidence": [
        {
          "file": "C/XzDec.c",
          "start_line": 1071,
          "end_line": 1074,
          "code": "<호출 지점의 원본 네 줄>"
        }
      ]
    }
  ]
}
```

`F1` 등의 키는 요청 안에서만 쓰고, **출발 함수 ID·1차 점수·리비전·수정 여부·취약점 라벨은 모델에 보내지 않는다.** 함수 목록은 대상 스냅샷 안의 안정적인 함수 ID순으로 정렬한 뒤 `F1`, `F2`를 붙인다. 관계는 종류·출발 키·도착 키·증거 위치 순으로 정렬한다. `from`과 `to`는 실제 호출 방향이다. 동일 함수 본문은 입력 안에서 한 번만 싣고 여러 관계가 같은 키를 참조한다. `evidence.code`는 지정한 소스 줄의 원본 문자열이다. 입력은 공백 없는 UTF-8 JSON으로 직렬화하고 실제 바이트 수와 SHA-256을 기록한다.

Jev `POST /v1/systemone` 요청은 고정 모델 `jev-1.13.0`, 위 `state`, 다음 **단일 `Noul` 질문**으로 구성한다. `state`가 JSON 객체인 형태와 `Noul` 응답은 [TypeSafe State](https://docs.typesafe.ai/concepts/state), [Noul](https://docs.typesafe.ai/primitives/noul), [모델 문서](https://docs.typesafe.ai/models)에 따른다. 질문 문구와 점수 의미는 **검토 중인 제안**이다.

```json
{
  "has_security_vulnerability": {
    "type": "noul",
    "instructions": "Based on the provided functions and their stated relations, does the behavior implemented by this group contain a concrete security vulnerability? General complexity, risky API use, or a code smell alone is insufficient; the code must support a specific failure mode with security impact."
  }
}
```

이 질문은 함수 하나를 `target`으로 지정하지 않고 묶음이 구현한 동작의 **구체적인 보안 취약점 존재 여부**를 묻는다. `Noul` 값은 이 질문에 대한 모델의 판단 신호다. 높은 값도 취약점 확인 결과나 보정된 취약 확률이 아니며, 낮은 값도 안전성의 증명이 아니다. 한 단계 직접 호출로 만든 묶음에는 필요한 호출 경로·환경·방어 코드가 빠질 수 있다. 1차 조사 가치 점수와 2차 취약성 판단 점수의 절대값을 직접 비교하지 않는다. 확인된 버그와 미확정 후보의 구분은 [제품 명세](../../docs/product.md)에 따른 3차 검증에서 한다.

요청 전에는 `group_id`, 소스 리비전, 정규화한 `state`의 SHA-256, `questions`의 SHA-256과 요청 모델을 고정한다. `group_id`는 **소스 리비전 + NUL 바이트 + 정규화한 `state` 바이트**의 SHA-256이다. `questions` 해시는 키를 정렬한 공백 없는 UTF-8 JSON의 SHA-256으로 계산한다. 동일 묶음은 출발 함수가 여러 개여도 **독립 평가 회차(`trial`)당 요청 한 건**으로 센다. 실행 기록의 출발 함수 ID와 1차 점수는 Jev 요청에 넣지 않는다.

## Jev 응답과 저장 형식

기존 1차 정상 응답에서 확인한 Jev 응답은 `answers.review_worth_plain.noul`, `model`, `usage.input_tokens`, `usage.output_tokens`를 포함했다. 이 2차 질문의 정상 응답에서는 `answers.has_security_vulnerability.noul`을 읽는다. 값이 불리언이 아닌 0~1 숫자이고 실제 모델이 요청한 `jev-1.13.0`일 때만 `scored`로 기록한다. `Noul` 값은 **제시된 묶음에 구체적인 보안 취약점이 있는가**라는 질문의 모델 응답이며, 취약점 확인이나 안전 판정이 아니다.

아래는 저장할 **성공 기록의 형식 예시**다. 숫자는 설명용이며 실제 채점 결과가 아니다.

```json
{
  "group_id": "<소스 리비전과 state로 만든 해시>",
  "trial": 1,
  "state_sha256": "<state 해시>",
  "question_sha256": "<questions 해시>",
  "requested_model": "jev-1.13.0",
  "status": "scored",
  "score": 0.73,
  "actual_model": "jev-1.13.0",
  "usage": {"input_tokens": 1200, "output_tokens": 40},
  "elapsed_ms": 850,
  "http_attempts": 1,
  "raw_response": {"model": "jev-1.13.0", "answers": {"has_security_vulnerability": {"type": "noul", "noul": 0.73}}, "usage": {"input_tokens": 1200, "output_tokens": 40}}
}
```

API 오류, 타임아웃, 응답 구조 오류는 같은 `group_id`·`trial`·입력 해시와 함께 `status: "error"`, 오류 종류·HTTP 상태(있을 때)·시도 횟수·지연을 기록한다. 실패 기록에는 `score`를 두지 않는다. 실제 API가 입력 한도를 이유로 거부한 경우에도 입력을 축소하거나 다른 점수로 대체하지 않고 미평가로 남긴다. 전송 재시도는 **같은 `trial`**의 시도이며, 서로 다른 `trial`은 독립 Jev 요청이다. 실행을 재개할 때 기존 성공 기록의 해시·모델·질문을 검증하고 그 `group_id`·`trial`을 다시 채점하지 않는다.

```json
{
  "group_id": "<소스 리비전과 state로 만든 해시>",
  "trial": 1,
  "state_sha256": "<state 해시>",
  "question_sha256": "<questions 해시>",
  "requested_model": "jev-1.13.0",
  "status": "error",
  "error_kind": "http",
  "http_status": 503,
  "elapsed_ms": 1200,
  "http_attempts": 5
}
```

각 실행은 Git 제외된 `runs/<run-id>/`에 입력 스냅샷 해시와 질문·모델을 `manifest.json`으로 고정하고, 요청별 원시 응답을 `responses.jsonl`에 추가한다. 원본 응답, 사용 토큰, 오류와 재시도 기록은 이 파일에 남긴다. [`groups.jsonl`·`origins.jsonl`](direct-call-group-dry-run.md)은 묶음과 출발 함수의 대응 자료이며 모델 응답을 출발 함수별 독립 점수로 복제하지 않는다.

## 순위 출력

API 응답 자체는 순위나 버그 위치를 제공하지 않는다. 정상 응답이 모이면 별도 결과 파일에 `group_id`, 사용한 `trial`별 점수, 최종 정렬 점수, 순위와 상태를 기록한다. 실패·누락 묶음은 점수 0으로 바꾸지 않고 미평가로 보고한다. 동점은 `group_id` 오름차순으로 정렬한다. 현재 첫 채점을 한 번만 할지, [실험 설계](README.md)의 세 번 반복 제안을 채택할지와 반복 점수의 합산 규칙은 **실행 전에 확정할 제안**이다. 3차 분석에는 순위가 매겨진 묶음 ID와 원래 코드·관계 입력을 전달하며, Jev 응답에 없는 오류 설명이나 위치를 생성하지 않는다.

## 경계와 중복 처리

- 관계 그래프의 **연결 성분 전체를 묶음으로 삼지 않는다.** 이전 7-Zip 사전 점검의 선택 관계를 합치면 가장 큰 연결 성분에 함수 308개가 들어간다. 이는 하나의 요청으로 보낼 조사 대상이라고 보기 어렵다.
- 각 1차 통과 함수를 출발점으로 한 단계 직접 연결된 **모든 함수**를 묶는다. 겹치더라도 구성 함수나 관계가 다르면 별도 후보로 평가한다. 서로 다른 출발 함수가 정확히 같은 함수·관계·근거 묶음을 만들면 한 후보로 합쳐 한 번만 평가하고 모든 출발 함수 ID를 실행 기록에 연결한다.
- 묶음 동일성은 대상 스냅샷과 정규화한 `state` 바이트로 판정한다. 함수·관계 순서를 출발 함수에 의존하지 않게 고정하므로 같은 묶음은 같은 입력 해시를 갖는다.
- 입력 크기는 **생성 후 측정·기록만** 한다. 함수나 근거를 크기 때문에 제외하지 않는다. 실제 모델이 입력 한도를 이유로 거부하면 그 후보를 미평가로 기록한다.

[크기 제한 없이 다시 생성한 7-Zip 사전 점검](direct-call-group-dry-run.md)은 376개 출발 함수에서 중복을 제거해 367개 후보를 만들었다. 같은 후보는 9쌍이었다. 후보 크기의 최대값 51,287바이트는 관측값이며 구성이나 제외 기준으로 사용하지 않았다.

## 입력 생성 기록

묶음 ID와 출발 함수 ID들의 대응, 대상 스냅샷·함수 ID·코드 해시, 확인된 관계와 미해결 호출의 근거, 입력 해시·바이트 수, 모델·질문 버전, 원시 응답과 비용·오류를 모델 요청 밖에 둔다. 동일 묶음의 점수를 여러 출발 함수에 복사해 함수별 독립 점수처럼 보고하지 않는다. 여러 묶음에서 같은 버그 기전에 도달하더라도 기전은 한 번만 센다.
