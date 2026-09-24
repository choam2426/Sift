# 1차 Jev 입력 범위 실험

실험을 바탕으로 합의한 1차 기본안은 [ADR 0004](../../docs/adr/0004-first-pass-function-triage.md)에 기록했다. 함수 본문만 `Is this function worth a security researcher's time to inspect further for bugs?`라는 단일 `Noul` 질문으로 평가하고, 첫 구현은 `Noul ≥ 0.60`을 통과시킨다. 아래의 다른 질문·입력 형식은 기본안에 이르기까지 비교한 실험 후보이며, 제품에서 채택한 설정이 아니다.

이 실험은 [2차 분석 구조 비교](../second-pass/README.md)에 앞서, Jev가 각 함수를 평가할 때 받을 코드 범위를 정한다. 제품의 전제인 **모든 유닛 평가**는 유지한다. 함수 일부만 보여주는 방식도 빠진 부분이 없도록 처리해야 한다.

## 확보한 용량 근거

`data/7zip.c.functions.jsonl`의 함수 602개에 대응하는 `data/7zip.c.memory.scores.jsonl`에는 응답 602개와 오류 0개가 있다. 가장 긴 함수는 19,835자이고, 대응 요청의 입력 사용량은 6,518토큰이다. 이 산출물은 **7-Zip C 함수가 Jev 요청 한도에 들어가는지** 확인하는 근거다. 당시 질문과 입력 형식을 완전히 재구성할 수 없으므로 입력 범위별 판단 품질을 비교하는 근거로 재사용하지 않는다.

TypeSafe의 [모델 문서](https://docs.typesafe.ai/models)에 따르면 `jev-1.13.0`의 한도는 요청 전체 64k토큰, `state`와 가장 긴 질문의 합 32k토큰이다(2026-09-23 확인). 따라서 64k 전체를 함수 코드에 쓸 수 있다고 계산하지 않는다. 함수 전체를 기본 후보로 두고, 한도를 넘는 사례가 나오면 그 사례에 한해 빠짐없이 분할하는 방식을 시험한다.

## 초기 비교 가설

**함수 전체만 제공**할 때와 **함수 전체에 직접 사용하는 타입·상수·매크로 선언을 더할** 때 유망한 함수의 순위가 달라지는가? 다른 함수 본문을 따라가는 분석은 2차 실험에서 다룬다. 모델 질문과 대상 함수는 두 방식에서 동일하게 유지한다.

## 초기 질문과 출력 기록 초안

### Jev에 묻는 것

초기 실험에서는 각 함수에 `Noul` 질문 하나를 보내고 Jev의 `criteria.true`와 `criteria.false`로 선별 경계를 적는 안을 비교했다. 아래 문구는 채택한 질문이 아닌 실험용 초안이다. [공식 API 스키마](https://api.typesafe.ai/openapi.json)

```json
{
  "type": "noul",
  "instructions": "Should this function be selected for further security investigation? Judge only from the code shown.",
  "criteria": {
    "true": "Select when a concrete operation or decision could lead to a security-relevant failure if an assumption about input, bounds, state, permissions, ownership, or error handling is wrong. The related code may be needed to check that assumption. A confirmed bug is not required.",
    "false": "Do not select only because the function is long, complex, has a security-related name, or calls a potentially dangerous API. Select false when the shown behavior has no concrete security-relevant failure mechanism or unresolved safety condition."
  }
}
```

`true`는 **확인할 만한 실패 기전이나 전제가 보인다**는 뜻이다. Jev의 `noul` 값은 이 기준에 대한 모델 응답이며 실제 버그 확률, 취약점 심각도, finding 근거가 아니다. 정상적인 경계 검사까지 과도하게 올리거나 다른 함수에 숨어 있는 버그를 놓치는지는 라벨 사례에서 확인한다. Jev는 설명문과 코드 위치를 반환하지 않는다. [질문 형식](https://docs.typesafe.ai/primitives)

한 질문으로 여러 종류의 버그를 놓친다면 비교 후보로 **보안상 중요한 동작이 있는가**와 **의심스러운 조건·전제가 있는가**를 각각 별도 요청에서 묻는다. 점수를 곧바로 합치거나 두 값 모두 높아야 통과시키지는 않는다. 같은 통과량에서 실제 버그 도달률이 개선되는지 확인한 뒤 결합 규칙을 고른다. 여러 수준의 `Score`도 별도 비교 후보로 둔다.

### Sift가 기록하는 것

Jev 응답을 함수 ID와 결합해 아래처럼 **함수당 한 기록**을 남긴다. `input_hash`는 실제 보낸 입력 전체의 해시다. `model`에는 별칭 대신 응답에 나온 실제 버전을 기록한다.

```json
{
  "unit_id": "7zip:C/XzDec.c:580:MixCoder_Code",
  "snapshot_id": "<target-revision>",
  "input_profile": "function-body-v1",
  "input_hash": "<sha256>",
  "question_id": "<question-version>",
  "model": "jev-1.13.0",
  "status": "scored",
  "answer": {"type": "noul", "noul": 0.89},
  "usage": {"input_tokens": 1840, "output_tokens": 20}
}
```

숫자는 저장 형식의 예시이며 이 질문으로 다시 측정한 값이 아니다. 원시 API 응답도 실험 산출물에 보관해 정규화 오류를 추적한다. 오류·한도 초과는 별도 `status`와 오류 종류로 기록하고, 점수 0으로 바꾸지 않는다. 재시도 후에도 실패하면 해당 유닛을 미평가로 보고한다.

## 채택한 추출 규칙

추출기는 버전이 붙은 기준 `review-worth-v1: noul >= 0.60`을 **성공적으로 평가된 모든 함수**에 적용한다. 통과한 함수의 ID와 점수를 2차 분석 대상으로 내보내고, 점수 내림차순으로 정렬한다. 동점이면 유닛 ID로 순서를 고정한다. 2차는 ID로 원본 코드와 관계를 조회한다. Jev가 반환하지 않은 이유나 위치를 1차 결과에 만들어 넣지 않는다.

`0.60`은 [소스 코드 사례의 점수 분포](declarations/README.md)에서 고른 첫 구현값이며 일반적인 최적값이나 버그 확률이 아니다. 기준에는 모델 버전, 질문 버전, 입력 범위와 코드 표현(소스·디컴파일)을 함께 기록한다. 이 중 하나가 바뀌면 기존 임계값을 그대로 적용하지 않고 확인한다. 선별 기준과 1차 원시 기록을 분리해 두면 임계값을 바꾸어도 Jev 호출을 반복하지 않고 재선별할 수 있다.

## 입력과 실행

- 초기 7-Zip 입력인 `data/*.jsonl`은 로컬에서 생성해 Git에서 제외했다. 따라서 `compare_questions.py`의 7-Zip 부분은 이 저장소만 복제해서 재실행할 수 없다. 이후 파일 전체 표본은 원본 URL과 파일 해시를 [`contrast_holdout.json`](contrast_holdout.json)에 고정했다. 원시 API 응답은 모두 Git에서 제외하고 집계와 해석을 이 문서와 하위 실험 문서에 남겼다.
- 로컬 7-Zip에서 알려진 버그 관련 함수 2개, 길이 상위 함수 4개, 길이가 다른 비교 함수 4개를 고정 표본으로 뽑는다. 버그 관련 함수와 비교 함수 일부에는 수정 버전의 대응 함수도 포함한다. 각 방식을 같은 표본에 한 번씩 적용한다.
- 이 소수 표본은 입력 형식, 맥락 증가량, 점수 변화와 비용을 확인하는 파일럿이다. 버그 도달률의 일반적인 우열은 다른 버그 기전과 디컴파일 사례를 추가해 확인한다.
- 정답 라벨과 패치 차이는 모델 입력에서 제외한다. 각 실행은 대상 리비전, 함수 ID, 실제 제공한 코드 위치, 모델·질문·설정, 응답, 사용량, 지연·오류를 기록한다. 원시 산출물은 Git에서 제외한 `experiments/first-pass/runs/<run-id>/`에 둔다.

## 판정

같은 통과량에서 알려진 버그 관련 함수의 순위 변화를 살핀다. 한도 초과·입력 누락·평가 실패, 함수당 토큰·시간도 함께 본다. 수정 버전의 점수가 낮아야 한다고 가정하지 않는다. Jev는 버그 확증보다 조사 가치의 선별에 쓰기 때문이다.

입력 방식마다 점수 분포가 달라질 수 있으므로 **동일한 숫자 임계값만으로 성능을 비교하지 않는다.** 먼저 동일한 통과량에서 순위와 버그 도달률을 보고, 선택한 방식의 점수 임계값은 별도 사례에서 보정한다. 그 임계값을 통과한 함수만 2차로 추출한다.

실행 전 고정할 값은 직접 맥락의 한도, 통과량, 비교 함수의 선정 방식, 모델 질문이다. 7-Zip 사례는 실행 절차를 점검하는 데 쓰고, 채택은 다른 버그 기전과 디컴파일 사례를 확인한 뒤 결정한다. 결과와 채택 이유는 `../../docs/adr/`에 기록한다.

### 다른 버그 기전의 확인 표본

7-Zip 결과를 본 뒤 질문을 조정했으므로 7-Zip만으로 질문을 고르지 않는다. `question-pilot-v3`의 여덟 질문은 [`compare_questions.py`](compare_questions.py)에 고정하고, 새 프로젝트의 응답을 보기 전에 다음 비교 규칙을 정한다.

- 7-Zip: 취약 버전 함수 16개 중 상위 6개. 버그 관련 함수 두 개는 같은 오류 기전에 속하므로 하나의 사례로 센다.
- curl: 8.3.0의 `do_SOCKS5`와 검토한 SOCKS 송수신 함수 두 개 중 상위 1개. 8.4.0의 같은 함수는 별도 짝으로만 본다. [curl 보안 공지](https://curl.se/docs/CVE-2023-38545.html)
- Etherpad: 1.6.2의 `apiCaller`, 단순 버전 응답 핸들러, 라벨을 보류한 오류 보고 핸들러 중 상위 1개. 1.6.4의 `apiCaller`는 별도 짝으로만 본다. [GitHub Security Lab 분석](https://securitylab.github.com/research/etherpad-reflected-file-download/)

각 사례에서 알려진 버그 함수가 예산 안에 들어왔는지, 검토 비버그·미검토 함수가 몇 개 들어왔는지 각각 표시한다. 짝인 수정 함수는 독립된 비버그 사례로 세지 않는다. curl의 송수신 함수는 요청 길이보다 더 읽거나 쓰지 않는 IO 계약을 전제로, Etherpad의 버전 응답 핸들러는 고정된 서버 값을 반환하는 동작만 확인한 제한적 비교군이다. 원본 함수 범위와 해시는 [`extra_samples.json`](extra_samples.json)에 고정한다. 새 표본의 점수를 보고 질문 문구나 상위 개수를 바꾸지 않는다.

## 질문 파일럿 결과 — 2026-09-23

[`compare_questions.py`](compare_questions.py)로 7-Zip 함수 10개와 수정 버전의 대응 함수 2개를 평가했다. 알려진 버그 관련 함수 2개, 길이 상위 함수 4개, 길이 구간별 비교 함수 4개를 사용했다. 동일한 함수 본문을 `jev-1.13.0`에 주고 `combined`(위의 기준), `operation`(보안상 중요한 동작), `assumption`(확인할 전제)을 한 요청에서 함께 물었다. 요청 12건 모두 성공했고 입력 사용량 합계는 38,843토큰이었다. 원시 응답은 Git에서 제외한 `runs/question-pilot-v1/`에 있다.

| 질문 | `MixCoder_Code` 순위 | `XzUnpacker_Code` 순위 |
|---|---:|---:|
| `combined` | 7/10 | 3/10 |
| `operation` | 8/10 | 2/10 |
| `assumption` | 5/10 | 6/10 |

순위는 취약 버전 함수 10개 안에서 매긴 것이다. `combined` 점수는 `MixCoder_Code`에서 취약 버전 0.82·수정 버전 0.83, `XzUnpacker_Code`에서 0.87·0.86이었다. 이는 질문이 **조사 가치**를 묻고 버그 여부를 판별하지 않는다는 설계와 맞지만, 한 버그 기전의 사례만으로 일반화할 수 없다. 길이별 비교 함수는 버그가 없다고 라벨링하지 않았으므로 정밀도도 계산하지 않는다. 세 질문 중 어느 것을 쓸지는 다른 버그 기전과 검토된 비버그 사례에서 같은 통과량으로 비교해야 한다.

### 비버그 비교군 추가 — 2026-09-23

같은 요청 형식으로 함수 6개를 추가했다. 아래의 비버그 라벨은 **표에 적은 동작과 확인한 호출 조건에서 결함이 없다는 제한된 판단**이다. 코드베이스 전체에 버그가 없다는 뜻은 아니다. 라벨은 모델 입력에 넣지 않았다.

| 함수 | 확인한 조건 | `combined` | `operation` | `assumption` |
|---|---|---:|---:|---:|
| `CrcCalc` | 주어진 버퍼를 `CrcUpdate`로 전달하고 CRC 값을 변환 | 0.32 | 0.57 | 0.68 |
| `SzFree` | 유효한 할당 포인터에 대한 정상 해제 래퍼 | 0.52 | 0.92 | 0.77 |
| `ThreadNextGroup_Init` | `numGroups == 0`을 보정한 뒤 나머지 연산 | 0.32 | 0.36 | 0.52 |
| `TestSignatureCandidate` | 호출자가 고정 길이 헤더를 읽은 뒤 비교 함수에 전달 | 0.46 | 0.75 | 0.78 |
| `Xz_ReadHeader` | 정해진 길이만큼 읽었는지 검사한 뒤 헤더를 파싱 | 0.76 | 0.92 | 0.69 |
| `FileSeqInStream_Read` | 읽기 결과를 전달하고 오류를 반환하는 래퍼 | 0.64 | 0.79 | 0.73 |

취약 버전 함수 16개 중 상위 6개를 통과시킨다면 `combined`와 `operation`은 알려진 버그 관련 함수 2개 중 1개, `assumption`은 2개를 포함한다. 세 질문 모두 이 비버그 비교군 6개는 상위 6개에 넣지 않았다. 전체 18건 모두 응답했고 입력 사용량 합계는 43,012토큰이었다. 다만 다른 8개 함수는 버그 여부가 검토되지 않았고 알려진 버그 기전도 하나라, `assumption`을 채택하거나 정밀도 수치로 일반화할 근거는 아직 부족하다.

### 직접적인 버그 질문 추가 — 2026-09-23

같은 18개 함수에 `bug_likely_plain`("Is this function likely to contain a security-relevant implementation bug?")과 `bug_likely_criteria`(같은 뜻에 구체적 결함의 참·거짓 기준을 덧붙인 질문)를 추가해 다섯 질문을 한 요청에서 비교했다. 18건 모두 응답했고 입력 사용량 합계는 45,172토큰이었다. 원시 응답은 `runs/question-pilot-v2/`에 있다.

| 질문 | `MixCoder_Code` 순위 | `XzUnpacker_Code` 순위 | 상위 6개에 든 검토 비버그 함수 |
|---|---:|---:|---:|
| `combined` | 7/16 | 3/16 | 0/6 |
| `operation` | 10/16 | 2/16 | 0/6 |
| `assumption` | 5/16 | 6/16 | 0/6 |
| `bug_likely_plain` | 4/16 | 6/16 | 0/6 |
| `bug_likely_criteria` | 5/16 | 6/16 | 0/6 |

두 직접 질문 모두 이 표본에서는 버그 관련 함수 2개를 상위 6개에 넣었다. 하지만 `bug_likely_plain` 점수는 `MixCoder_Code`의 취약·수정 버전이 모두 0.67이고, `XzUnpacker_Code`도 모두 0.62였다. **질문을 버그 가능성으로 바꿔도 이 숫자를 실제 버그 존재 확률로 읽을 수 없다.** 검토 비버그 함수는 낮게 나왔지만, 다른 버그 기전이 있는 함수에서 같은 순위를 유지하는지 확인해야 한다.

### 질문·사례 확장 결과 — 2026-09-23

`question-pilot-v3`에서는 질문을 여덟 개로 늘리고 7-Zip 18개, curl 4개, Etherpad 4개 함수를 같은 방식으로 평가했다. 요청 26건 모두 성공했고 입력 사용량 합계는 63,366토큰이었다. 새 사례의 버그 근거는 [curl 보안 공지](https://curl.se/docs/CVE-2023-38545.html)와 [Etherpad 연구 기록](https://securitylab.github.com/research/etherpad-reflected-file-download/)에 있다. 원시 응답과 입력 원문은 Git에서 제외한 `runs/question-pilot-v3/`에 보관했다.

이 묶음 요청은 탐색 기록으로 보관한다. 이후 비교는 질문별 독립 요청으로 다시 실행했다. 스크립트는 이미 성공한 입력만 건너뛰며 입력·질문 해시와 모델이 달라지면 같은 실행 디렉터리를 재사용하지 않는다.

| 질문 | 7-Zip 상위 6/16 | curl 상위 1/3 | Etherpad 상위 1/3 | 도달한 독립 버그 기전 |
|---|---|---|---|---:|
| `combined` | 도달 | 도달 | 미도달 | 2/3 |
| `operation` | 도달 | 도달 | 미도달 | 2/3 |
| `assumption` | 도달 | 도달 | 미도달 | 2/3 |
| `bug_likely_plain` | 도달 | 도달 | 미도달 | 2/3 |
| `bug_likely_criteria` | 도달 | 도달 | 미도달 | 2/3 |
| `review_worth_plain` | 도달 | 도달 | 도달 | 3/3 |
| `bug_visible` | 도달 | 도달 | 미도달 | 2/3 |
| `bug_if_context` | 미도달 | 도달 | 미도달 | 1/3 |

7-Zip의 버그 관련 함수 두 개는 **한 기전**으로 세었다. curl과 Etherpad의 수정 함수는 독립 비버그로 세지 않고 짝 비교에만 썼다. `review_worth_plain`의 Etherpad 취약 함수 점수는 0.81, 아직 라벨을 정하지 않은 오류 보고 핸들러는 0.80이었다. 다른 일곱 질문은 이 미검토 핸들러를 취약 함수보다 높게 보았다. 따라서 해당 핸들러를 거짓 양성이라고 부르거나 이 표본으로 정밀도를 계산하지 않는다. `bug_if_context`는 7-Zip의 검토 비버그 함수 두 개를 상위 6개에 넣었다.

직접적인 버그 질문의 7-Zip 우위는 다른 버그 기전에서 유지되지 않았다. `review_worth_plain`만 첫 실행에서 세 사례에 도달했지만 Etherpad 차이는 0.01이었다. 같은 두 Etherpad 함수를 세 번씩 추가 호출하자 `apiCaller`와 미검토 오류 보고 핸들러의 순서가 한 번 뒤집혔다(0.79/0.80, 0.80/0.79, 0.80/0.79). 이 여섯 추가 호출은 위 26건의 토큰 합계에 포함되지 않는다. **3/3 도달은 안정적인 우위가 아니다.** 어떤 질문도 채택하지 않는다. 다음 비교에는 디컴파일된 코드와 역할·길이가 비슷한 검토 함수를 추가해야 한다.

### 두 신호의 결합 재생

`question-pilot-v3` 응답을 다시 사용해 `review_worth_plain`과 `bug_likely_plain`의 산술 평균과 최댓값으로 순위를 매겼다. Jev를 다시 호출하지 않았고, 위에서 고정한 프로젝트별 상위 개수를 그대로 썼다.

| 순위 신호 | 도달한 독립 버그 기전 | Etherpad `apiCaller` 순위 |
|---|---:|---:|
| 조사 가치만 | 3/3 | 1/3 |
| 직접 버그 질문만 | 2/3 | 2/3 |
| 두 값의 평균 | 2/3 | 2/3 |
| 두 값의 최댓값 | 2/3 | 2/3 |

미검토 Etherpad 오류 보고 함수의 버그 질문 점수가 높아 단순 결합에서는 `apiCaller`가 밀렸다. 두 `Noul` 값의 평균·최댓값은 **버그 확률이 아니라 임의의 순위 규칙**이다. 이 표본의 점수를 본 뒤 가중치를 조정하지 않는다.

### 단일 질문 융합안

두 출력값을 계산으로 섞는 방식과 별개로, **버그 의심과 조사 가치를 하나의 판단으로 묻는** `bug_worth_single`을 시험한다.

> Is this function likely enough to contain or enable a security-relevant implementation bug that a researcher should inspect its related code?

`true`는 코드에 보이는 구체적 실수·확인되지 않은 전제가 보안 문제로 이어질 만해 관련 코드를 확인할 가치가 있는 경우다. `false`는 복잡하거나 보안상 중요한 함수라는 사실 외에 버그를 의심할 이유가 보이지 않는 경우다. 위의 26개 함수와 고정된 프로젝트별 상위 개수를 그대로 사용하고, 결과를 본 뒤 문구·예산을 바꾸지 않는다. Jev 값은 여전히 실제 버그 확률이 아니다.

### 질문별 독립 요청

[공식 문서](https://docs.typesafe.ai/primitives)는 같은 요청의 질문들을 독립적으로 평가한다고 설명한다. 이 실험에서는 비교 조건을 단순하게 고정하기 위해 융합안과 앞의 여덟 질문을 **각각 요청 하나에 질문 하나**로 다시 평가한다. 기존 `question-pilot-v1`~`v3` 결과는 탐색 기록으로만 사용한다. 실행 이름은 `isolated-<question-name>`이며, 같은 입력·모델·프로젝트별 상위 개수를 사용한다.

### 확장 표본과 비교 규칙

독립적인 취약점 기전을 세 개 추가한다. [curl CVE-2023-38546](https://curl.se/docs/CVE-2023-38546.html)은 핸들 복제 중 쿠키 파일 상태가 잘못 전달되는 사례, [curl CVE-2023-46218](https://curl.se/docs/CVE-2023-46218.html)은 대소문자가 섞인 쿠키 도메인이 PSL 검사를 우회하는 사례, [node-tmp CVE-2026-49982](https://github.com/raszi/node-tmp/security/advisories/GHSA-7c78-jf6q-g5cm)는 비문자열 경로 옵션이 검사와 경로 생성에서 다르게 해석되는 사례다. 각 취약 함수와 수정 함수, 같은 버전의 제한적으로 검토한 비교 함수 하나, 미검토 함수 하나를 [`expanded_samples.json`](expanded_samples.json)에 원본 URL·줄 범위·SHA-256으로 고정한다. 수정 함수는 독립된 음성 사례로 세지 않는다.

이 세 사례의 점수를 보기 전에 순위 예산을 고정한다. 수정 버전 함수는 순위에서 제외한다. 동점은 유닛 ID 오름차순으로 정렬한다.

| 취약 버전 코드 묶음 | 함수 수 | 통과량 | 독립 취약점 기전 |
|---|---:|---:|---:|
| 7-Zip | 16 | 6 | 1 |
| curl 8.3.0 (SOCKS와 핸들 복제) | 6 | 2 | 2 |
| curl 8.4.0 (쿠키 도메인) | 3 | 1 | 1 |
| Etherpad 1.6.2 | 3 | 1 | 1 |
| node-tmp 0.2.6 | 3 | 1 | 1 |

따라서 알려진 취약점 **6개 기전 중 예산 안에 도달한 수**와 미검토 함수·제한적 비버그 비교 함수의 선별 수를 따로 기록한다. `curl_easy_reset`은 핸들 초기화 동작, `Curl_cookie_cleanup`은 쿠키 해제 동작, `_getRelativePathSync`는 문자열 경로를 정규화한 뒤 범위를 검사하는 동작만 비버그 비교 대상으로 검토했다. 그 밖의 결함 가능성까지 부정하는 라벨은 아니다. `dupset`, `Curl_cookie_getlist`, `_randomChars`에는 음성 라벨을 주지 않는다. 새 질문 문구와 통과량은 확장 결과에 맞춰 바꾸지 않는다.

확장 실행은 `SIFT_SAMPLE_SET=expanded SIFT_QUESTION_SET=isolated-<question-name> python3 experiments/first-pass/compare_questions.py expanded-<question-name>`으로 수행한다. 기존 26개 실행은 `SIFT_SAMPLE_SET=pilot`으로 고정되어 확장 결과와 섞이지 않는다. 이 표본도 취약점 중심으로 구성한 파일럿이므로 일반적인 재현율·정밀도를 추정하지 않는다.

### 독립 요청과 확장 표본 결과

9개 질문을 각각 **요청 하나에 질문 하나**로 보냈다. 확장 실행은 질문당 38개 함수·38개 요청이며 모두 `jev-1.13.0`에서 채점됐다. 수정 함수 7개는 순위 대상에서 제외했다. 아래 수치는 위에서 고정한 다섯 코드 묶음과 통과량을 적용한 결과다. 기존 26개 표본을 독립 요청으로 다시 평가한 원시 결과는 `runs/isolated-<question-name>/`, 확장 결과는 `runs/expanded-<question-name>/`에 있다. 두 실행 모두 `runs/`에서 Git 제외된다.

| 질문 | 도달한 취약점 기전 | 통과한 제한적 비버그 비교 함수 | 통과한 미검토 함수 |
|---|---:|---:|---:|
| `bug_worth_single` (버그 의심과 조사 가치 융합) | 5/6 | 0 | 5 |
| `review_worth_plain` (조사 가치) | 5/6 | 0 | 6 |
| `bug_likely_plain` (버그 가능성) | 4/6 | 0 | 6 |
| `bug_likely_criteria` | 4/6 | 0 | 6 |
| `bug_visible` | 4/6 | 0 | 6 |
| `operation` | 4/6 | 0 | 7 |
| `combined` | 3/6 | 0 | 8 |
| `assumption` | 3/6 | 0 | 7 |
| `bug_if_context` | 1/6 | 3 | 7 |

융합 질문은 curl의 핸들 복제 취약 함수를 8.3.0 묶음에서 3위로 매겨 상위 2개 예산에서 놓쳤다. `review_worth_plain`은 이 함수를 포함했지만 node-tmp의 `_assertPath`를 같은 묶음에서 3위로 매겨 놓쳤다. 두 질문 모두 첫 확장 실행에서는 Etherpad `apiCaller`를 미검토 `jsErrorRoute`보다 0.01 높게 매겼다. 두 질문을 각각 두 번 더 독립 실행하자 융합 질문의 도달 수는 **5, 4, 5/6**, 조사 가치 질문은 **5, 5, 4/6**이었다. 융합 질문의 미도달 실행에서는 두 함수가 0.85로 동점이어서 유닛 ID 정렬에 따라 `jsErrorRoute`가 선택됐다. 조사 가치 질문의 미도달 실행에서는 `jsErrorRoute` 점수가 더 높았다. 26개 표본의 선행 독립 실행에서도 이 두 함수의 점수 차이가 0.00~0.02 안에서 흔들렸다.

동일한 함수 묶음·통과량에 **함수 길이(`code_chars`) 내림차순**만 적용한 기준선도 **5/6** 기전에 도달했다. node-tmp만 놓치고 제한적 비버그 비교 함수 한 개를 선별했다. 따라서 두 Jev 질문의 5/6만으로는 길이 기준보다 취약점 도달이 개선됐다고 말할 수 없다. 이 예산은 수정 함수를 제외한 31개 중 11개를 통과시키므로 실제 코드베이스의 임계값·통과율도 검증하지 않는다.

새 취약 함수와 수정 함수의 융합 질문 점수도 가까웠다: `curl_easy_duphandle` 0.71/0.72, `Curl_cookie_add` 0.79/0.78, `_assertPath` 0.77/0.72(취약/수정). `review_worth_plain`은 각 쌍에서 0.84/0.84, 0.88/0.88, 0.54/0.54였다. 이는 이 질문의 순위가 패치의 존재를 직접 판별한다는 근거가 아니라는 뜻이다. **5/6은 질문 채택 근거로 부족하다.** 서로 다른 결함을 놓치는지, 함수 본문 밖 맥락을 주면 나아지는지, 디컴파일 코드에서도 작동하는지를 다음 표본에서 확인해야 한다.

### 판정 명제와 의문문의 비교 설계

선별에 사용할 판단을 먼저 고정한다: **보여준 코드에는 보안 관련 구현 오류를 의심할 구체적인 근거가 있다.** `false`는 제공된 코드에서 그런 근거를 찾지 못했다는 뜻이며 안전성 확인이 아니다. [Noul 문서](https://docs.typesafe.ai/primitives/noul)는 `instructions`에 판단할 진술문 또는 예/아니오 의문문을 허용한다. 따라서 의미가 같은 아래 두 문장만 바꿔 문장 형식의 영향을 탐색한다. 두 요청의 `criteria.true`·`criteria.false`는 [`compare_questions.py`](compare_questions.py)에서 동일하다.

| 실행 이름 | `instructions` |
|---|---|
| `concrete_suspicion_statement` | `The shown code provides a concrete reason to suspect a security-relevant implementation error.` |
| `concrete_suspicion_question` | `Does the shown code provide a concrete reason to suspect a security-relevant implementation error?` |

각 질문을 확장 표본 38개에 **요청당 하나씩 세 번** 평가한다. 취약 버전 31개 함수의 다섯 묶음·상위 개수·동점 규칙은 위 확장 실험과 동일하게 유지한다. 수정 함수는 순위에 넣지 않는다. 주요 관찰값은 반복별 6개 취약점 기전의 도달 여부와 함수 길이 기준선 5/6 대비 차이이며, 선별된 제한적 비버그·미검토 함수도 따로 기록한다. 진술문이 세 반복 모두 의문문과 같거나 더 많은 기전에 도달하고 적어도 한 반복에서 더 많이 도달할 때만 **문장 형식의 우위 후보**로 본다. 그렇지 않으면 이 표본에서 우열 미확정이다. 같은 여섯 사례의 반복을 독립 취약점 사례로 늘려 세지 않으며, 이 표본으로 제품 질문을 확정하지 않는다.

### 판정 명제 비교 결과

두 문장 형식의 3회 실행은 모두 함수 38개씩 정상 채점됐다(총 228개 독립 요청). 원시 응답은 Git에서 제외한 `runs/judgment-concrete_suspicion_<statement|question>-<1|2|3>/`에 있다. 수정 함수 7개를 제외한 31개에 위의 동일한 통과량을 적용했다.

| 신호 | 반복 1 | 반복 2 | 반복 3 | 선별된 제한적 비버그 함수 |
|---|---:|---:|---:|---:|
| 판정 명제 진술문 | 4/6 | 4/6 | 4/6 | 매회 0 |
| 의미가 같은 의문문 | 4/6 | 4/6 | 4/6 | 매회 0 |
| 함수 길이 내림차순 | 5/6 | — | — | 1 |

두 문장 형식은 **세 번 모두 동일한 함수 집합**을 선별했다. 각 실행에서 7-Zip, curl SOCKS, curl 쿠키 도메인, node-tmp 기전에 도달했고, curl 핸들 복제 함수는 6개 중 3위로 상위 2개 예산에서, Etherpad `apiCaller`는 3개 중 2위로 상위 1개 예산에서 놓쳤다. 선별된 미검토 함수는 각 실행에서 6개다. 점수의 절댓값은 두 문장 사이에서 조금 달랐으나 같은 척도로 가정해 직접 비교하지 않는다.

**진술문 자체의 우위는 관찰되지 않았다.** 새 판정은 길이 기준보다 알려진 기전 한 개를 덜 찾았다. 이는 제공된 함수 본문에서 *구체적 의심 근거*를 요구한 기준의 결과일 수 있으며, 의문문 문법의 문제라고 해석할 수 없다. 이미 보면서 설계한 6개 기전의 개발 표본 결과라 다른 코드베이스로 일반화하지 않는다.

### 새 파일 전체 표본

이전 질문 개발에 쓰지 않은 취약점 6개와 해당 소스 파일의 함수 277개를 대상으로 한 단일 대조 판단 질문 비교는 [별도 실험 기록](contrastive/README.md)에 있다. 질문별로 독립 요청을 세 번씩 실행하고 동일한 상위 10% 예산에서 단순 조사 가치, 구체적 오류 의심, 함수 길이와 비교했다.

같은 파일·질문에서 대상 함수 본문에 파일 내부 선언만 추가한 비교는 [입력 범위 실험](declarations/README.md)에 있다. 이 실험은 다른 함수 본문을 1차에 넣지 않아 2차 분석과 경계를 유지한다.
