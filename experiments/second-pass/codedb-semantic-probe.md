# CodeQL 의미 관계 추가 국소 실험

> 2026-09-26 실행한 **탐색 실험**. 7-Zip 26.01의 고정 소스 리비전 `8c63d71ff886bda90c86db28466287f977374237`, CodeQL CLI 2.27.1의 기존 C 55파일 DB, `jev-1.13.0`을 사용했다. [이전 상태 객체 파일럿](codedb-state-pilot.md)의 입력과 질문을 비교 기준으로 삼았다. 원시 입력·응답은 Git 제외된 `runs/codedb-state-pilot-2026-09-26-v7/`과 `runs/codedb-decoder-semantics-2026-09-26-v1/`에 있다. 전체 A 기준선이나 일반적인 후보 생성 규칙의 검증 결과는 아니다.

## 무엇을 추가했나

[중립 CodeQL 질의](codeql-pilot/cpp/pilot_local_value_steps.ql)로 함수 내부의 가능한 값 흐름, [제어 흐름 질의](codeql-pilot/cpp/pilot_guarded_effects.ql)와 [분기 포함 질의](codeql-pilot/cpp/pilot_branch_effects.ql)로 조건과 효과의 관계를 추출했다. `GuardCondition.controls`는 특정 조건 평가가 기본 블록의 실행을 제어하는 관계이고, 분기 포함은 구문상의 포함 관계다. 둘 다 실행 시 도달성이나 취약성의 증명은 아니다. [CodeQL의 자료 흐름 설명](https://codeql.github.com/docs/codeql-language-guides/analyzing-data-flow-in-cpp/), [가드 라이브러리 설명](https://codeql.github.com/docs/codeql-language-guides/using-the-guards-library-in-cpp/)

`p->decoder`에서는 `MixCoder_Code`의 `p->outBuf` 조건→`Code2` 호출, `p->numCoders == 1` 조건→`*destLen` 대입, 648행의 복합 조건→649행 `processed` 대입을 확인했다. 값 흐름은 632행의 `destLen2`→638행 출력, 649행 대입 값→652행 출력 등 **가능한 함수 내부 흐름**으로 표시했다. [간접 호출 인자 질의](codeql-pilot/cpp/pilot_indirect_call_arguments.ql)는 610·731행의 `Code2` 호출에 전달된 인자와 위치를 복원했다. [함수 포인터 대입 질의](codeql-pilot/cpp/pilot_function_pointer_writes.ql)는 `XzBcFilterState_Code2`, `Lzma2State_Code2` 대입 위치를 찾았다. 해당 함수 본문은 국소 입력에 추가했지만, 두 함수 중 어느 것이 실제 호출되는지는 입증하지 않았고 **가능한 대입 근거**로 명시했다.

## 입력 한도와 채점 결과

공식 [TypeSafe 모델 문서](https://docs.typesafe.ai/models)는 `jev-1.13.0`의 **요청 전체 64k토큰**과 별도로 **`state`+가장 긴 질문 32k토큰** 한도를 명시한다. 이번 요청은 질문 하나뿐이다. HTTP 400의 `max_tokens_exceeded` 오류에는 실제 사용 토큰 수가 없으므로 실패 요청의 정확한 토큰 수는 알 수 없다. JSON 바이트 수를 토큰 한도로 해석하지 않는다.

| 입력 | `p->decoder` state 바이트 | Jev 입력 토큰 | 결과 |
|---|---:|---:|---:|
| 기존 본문·위치 사실 | 48,335 | 22,059 | Noul `0.28` |
| 상태·출력 효과에 닿는 관계를 넓게 추가 | 69,357 | 미반환 | HTTP 400 `max_tokens_exceeded` |
| 관찰한 출력 경로 4개 값 관계·3개 조건 관계, `Code2` 인자 2곳·가능한 대입 2곳·가능 구현 2개 본문 | 54,534 | 24,629 | Noul `0.19` |

넓은 버전은 [보강 입력 생성기](augment_codedb_pilot.py)로 만들었다. `p->decoder`에서는 기존 전체 본문 10개를 그대로 두고 제어 관계 119개(약 7.7KB), 값 간선 122개(약 6.6KB), 간접 호출 지원 함수 본문 4개(약 4.8KB) 등을 추가했다. 다른 네 후보는 모두 채점됐지만 `p->decoder`만 입력 한도로 거절됐다. 이 차이는 **함수 크기로 제외한 결과가 아니라 추가한 관계의 양** 때문에 생겼다. 성공한 네 후보의 입력 토큰은 각각 `p->block` 17,783, `p->check` 14,081, `p->sha` 20,587, `p->streamFlags` 12,178이었다.

[집중 입력 생성기](build_decoder_semantics_probe.py)는 기존 함수 본문 10개와 질문을 유지하고, 위에 열거한 소수의 원본 위치 근거를 추가했다. Jev 요청은 기존과 동일한 [채점 스크립트](score_codedb_pilot.py)로 한 번 실행했다. 점수는 `0.28`에서 `0.19`로 내려갔다. 값·제어 관계와 가능한 구현을 **함께** 추가했고 반복은 1회이므로 하락 원인을 특정할 수 없다. 이 입력은 관찰된 코드 경로를 사람이 골랐으며 일반 후보 생성 규칙이 아니다. 알려진 사례에 맞춘 입력의 점수를 A 기준선 성능으로 세지 않는다.

## 해석

이번 결과는 CodeQL DB에서 구조화한 의미 근거를 Jev 입력에 넣을 수 있음을 보여준다. 그러나 이 한 후보의 단일 점수에서는 취약성 신호가 개선되지 않았고, 간선을 많이 붙이는 방식은 `state` 32k 한도와 관련 없는 코드가 판단을 흐릴 위험이 있다. [TypeSafe의 긴 상태 주의](https://docs.typesafe.ai/model-jaggedness/jev-1.13)도 관련성 낮은 정보의 영향을 설명한다. 다음 설계에서는 **후보 동작의 관찰 효과와 연결되는 최소한의 근거를 재현 가능한 일반 규칙으로 고르는 방법**을 별도 사례에서 검증해야 한다. 원본 함수 본문을 크기로 제외하거나 잘라서 이 문제를 숨기지 않는다.

## 단순 입력 재시험

사용자 지적에 따라 같은 날 [간단한 입력 생성기](build_lean_codedb_pilot.py)로 **기존 다섯 후보의 전체 함수 본문을 그대로 유지**하고, Jev 입력에서는 이미 본문에 있는 조건 82개·필드 접근 89개 같은 위치 목록을 제거했다. `p->decoder` 예시에서 유지한 필드는 `operation`, 전체 `functions`, 관련 선언·매크로, 함수 사이 직접 호출과 인자, 미해결 호출 위치다. CodeQL은 여전히 후보와 연결 관계를 만드는 데 사용했다. 기존 질문·모델로 후보당 독립 요청 1회씩 채점했다.

| 상태 객체 | 기존 입력 토큰 → 간단한 입력 토큰 | 기존 Noul → 간단한 입력 Noul |
|---|---:|---:|
| `p->block` | 12,281 → 5,282 | 0.34 → 0.36 |
| `p->streamFlags` | 7,346 → 4,258 | 0.31 → 0.29 |
| `p->decoder` | 22,059 → 9,243 | 0.28 → 0.26 |
| `p->check` | 9,249 → 5,190 | 0.27 → 0.26 |
| `p->sha` | 15,755 → 6,795 | 0.24 → 0.22 |

다섯 요청의 입력 토큰 합계는 66,690에서 **30,768**로 줄었다. 원시 입력·응답은 Git 제외된 `runs/codedb-lean-pilot-2026-09-26-v1/`에 있다. `p->decoder`는 새 입력에서도 상위 2개에 들지 않았으므로 **중복 목록 제거만으로 후보 순위 문제가 해결되지는 않았다.** 각 값은 1회 응답이며 차이의 안정성을 아직 측정하지 않았다. 이 간단한 표현은 현재 **다음 입력 설계의 제안**이며 A 기준선 입력으로 합의하거나 전체 사례에 적용한 것은 아니다.
