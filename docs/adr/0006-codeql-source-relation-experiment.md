# 소스 관계 추출 실험에는 CodeQL을 사용한다

> 재검토 상태: 2026-09-27 [ADR 0014](0014-python-asyncio-and-code-lookup.md)에서 제품의 코드 조회는 tree-sitter로 구현하고 CodeQL은 관계 추출의 비교 기준으로만 쓰기로 했다.

> 재검토 상태: 2026-09-25 현재 아래 **직접 호출만 쓰는 첫 A 기준선**은 CodeQL 데이터베이스의 의미 관계를 충분히 사용하지 못한다는 지적에 따라 실행을 보류했다. CodeQL 데이터베이스를 코드 사실의 출처로 쓰고 취약성 판단은 Jev가 수행하는 [새 대안](../../experiments/archive/second-pass/codeql-evidence-proposal.md)의 후보 경계와 입출력을 검토한다. 아래 내용은 당시 결정과 파일럿의 기록이다.

2026-09-24 현재 A 기준선의 **소스 코드 관계 추출 실험**에는 CodeQL CLI 2.27.1을 사용한다. [지원 언어](https://docs.github.com/en/code-security/concepts/code-scanning/codeql/codeql-code-scanning)에 현재 사례인 C/C++, Rust, Go, Python이 모두 포함되고, [로컬 파일럿](../../experiments/archive/second-pass/codeql-pilot/README.md)에서 다섯 스냅샷의 데이터베이스와 위치가 있는 호출 관계를 실제로 얻었다. 언어별 도구를 먼저 따로 만드는 것보다 공통 도구에서 얻는 근거와 누락을 측정하기에 적합하다.

이 결정은 **A의 실험 도구 선택**이다. CodeQL 결과를 완전하거나 확정적인 실행 관계 그래프로 취급하지 않는다. 파일럿에서 7-Zip의 함수 포인터와 urllib3의 동적 메서드 호출은 미해결로 남았다. C/C++의 [`getTarget()`](https://codeql.github.com/codeql-standard-libraries/cpp/semmle/code/cpp/exprs/Call.qll/predicate.Call%24Call%24getTarget.0.html)은 정적으로 해석한 호출 대상을 제공하며 변수 호출에는 대상이 없다. 정적 대상 또는 추론된 후보를 2차 입력의 `direct_call`·`resolved_indirect_call`로 표시하려면 호출 지점의 실제 대상과 원본 근거를 별도로 확인한다. 연결하지 못한 호출은 `unresolved`로 기록한다. 필드 흐름과 동일 객체 관계도 별도 검증 전에는 넣지 않는다.

2026-09-25에 [7-Zip 직접 호출 사전 점검](../../experiments/archive/second-pass/direct-call-dry-run.md) 결과를 검토하고, **첫 A 기준선은 원본 호출 위치를 확인한 직접 호출 관계만 사용**하기로 했다. CodeQL은 관계 후보와 소스 위치를 제공하고, 출발 함수별 묶음 구성과 Jev의 재평가는 Sift가 수행한다. 사전 점검에서 376개 출발 함수 중 297개에는 관련 함수가 붙었고 79개에는 붙지 않았다. 알려진 버그의 필수 줄은 적어도 한 이전 입력에 포함됐다. 따라서 첫 A의 순위·버그 도달·누락 원인을 측정한 뒤, 간접 호출이나 필드 흐름을 추가한다면 별도 입력 버전으로 검증한다. CodeQL의 [데이터 흐름 경로 질의](https://codeql.github.com/docs/writing-codeql-queries/creating-path-queries/)는 시작점·끝점과 흐름 단계의 별도 정의가 필요하며, 현재 직접 호출 질의가 이를 대신하지 않는다. [2차 평가 단위와 묶음 경계](0007-second-pass-scores-related-code-group.md)에 맞춘 `state` 구조와 질문은 실행 전에 확정한다.

[CodeQL CLI 약관](https://github.com/github/codeql-cli-binaries/blob/main/LICENSE.md)은 OSI 승인 라이선스의 공개 소스 분석을 허용하지만 비공개 코드베이스 및 자동 분석에는 조건을 둔다. 이번에는 라이선스가 확인된 공개 소스 스냅샷을 수동 분석했다. 제품 기본 도구로 채택하거나 비공개 대상·자동 실행으로 범위를 넓히기 전에는 기술적 누락과 사용 조건을 다시 검토한다. CodeQL 버전, 대상 리비전 또는 빌드 설정이 바뀌어도 파일럿을 다시 확인한다.
