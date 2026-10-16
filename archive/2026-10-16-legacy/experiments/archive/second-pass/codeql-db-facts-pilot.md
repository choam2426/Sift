# CodeQL DB 코드 사실 조회 국소 점검

> 2026-09-25 실행. 대상은 7-Zip 26.01의 `C/XzDec.c` **한 컴파일 단위**로 만든 기존 CodeQL C/C++ DB다. CodeQL CLI 2.27.1을 사용했다. 취약점 질의와 Jev 호출은 실행하지 않았다. 이 결과는 [2차 입력 설계 제안](codeql-evidence-proposal.md)의 추출 가능성 점검이며 버그 검출 결과가 아니다.

## 실행한 중립 질의

| 질의 | 조회한 사실 | 출력 행 |
|---|---|---:|
| [`source_field_accesses.ql`](codeql-pilot/cpp/source_field_accesses.ql) | 필드 선언·접근 위치·수정 위치 여부 | 1,097 |
| [`source_call_arguments.ql`](codeql-pilot/cpp/source_call_arguments.ql) | 정적으로 해석된 호출의 인자 표현식과 위치 | 249 |
| [`source_conditions.ql`](codeql-pilot/cpp/source_conditions.ql) | `if` 문 조건과 위치 | 261 |

행 수는 원본 코드의 고유 문장이나 실행 경로 수가 아니다. 매크로·AST 표현과 출력 열에 따라 같은 소스 위치가 여러 행일 수 있다. 원시 BQRS·CSV는 Git 밖 `/tmp/sift-source-{field-accesses,call-arguments,conditions}-2026-09-25.*`에 둔다.

## 원본과 대조한 결과

- `outWritten` 필드 접근은 [`MixCoder_Init`의 초기화](../../targets/7zip/C/XzDec.c#L536)와 [`MixCoder_Code`의 누적 및 사용](../../targets/7zip/C/XzDec.c#L632) 위치에 대응했다. 질의의 `isModified()`는 536·632행을 수정 위치, 642·648·649행을 비수정 위치로 표시했다. 복합 대입은 이전 값도 읽으므로 이 표식을 완전한 읽기·쓰기 분류로 해석하지 않는다.
- [`XzUnpacker_Code`의 1071행](../../targets/7zip/C/XzDec.c#L1071)은 `MixCoder_Code`의 첫 인자로, 1203행은 `XzDecMix_Init`의 첫 인자로 원본 표현식 `&p->decoder`를 전달한다. CodeQL 결과는 인자의 소스 범위를 제공했고, 실제 문자열은 그 범위의 원본 코드를 다시 읽어 확인했다. 같은 표현식이 보인다는 사실만으로 두 호출 시 같은 런타임 객체라고 단정하지 않는다.
- [`MixCoder_Code`의 637행](../../targets/7zip/C/XzDec.c#L637)에는 `p->numCoders == 1`, 648행에는 `wasFinished || (destFinish && p->outWritten == destLenOrig)` 조건이 나왔다. 이 질의는 조건 **위치**만 추출했으며 어떤 코드 블록·효과를 제어하는지까지 계산하지 않았다.
- 관련 [`CMixCoder` 선언](../../targets/7zip/C/Xz.h#L208)은 함수 본문 밖에 있다. 함수 본문만 보내면 필드 타입과 상태 구조가 빠진다.

## 동작 후보 예시와 남은 증명

사람이 원본을 읽으면 `XzUnpacker_Code`의 블록 처리 호출을 진입 맥락으로, `p->decoder`가 가리키는 `CMixCoder` 상태를 공통 객체로, 출력 버퍼·길이·상태 갱신을 관찰 효과로 **제안**할 수 있다. 이 동작에는 `XzDecMix_Init`과 `MixCoder_Init`의 초기화, `MixCoder_Code`의 출력 길이·누적 상태·분기, 관련 선언과 간접 `Code2` 호출을 함께 살펴야 한다. 이는 후보 경계의 **수작업 예시**이며 CodeQL이 이 전체 묶음을 자동 도출한 결과가 아니다.

자동 구성 전에 다음을 추가 확인해야 한다.

1. 호출 인자의 `&p->decoder`와 피호출 함수의 `CMixCoder *p`가 연결되는지, 중간 별칭과 다른 호출 맥락은 무엇인지.
2. 상태 필드의 정의·사용과 길이·버퍼 인자의 자료 의존 관계가 어느 범위까지 계산되는지.
3. 각 조건이 어떤 출력·상태 변경을 제어하는지. 반복 호출 가능성과 실제 반복 실행도 구분해야 한다.
4. `Code2` 같은 간접 호출, 외부 함수 계약, 빌드 옵션에서 미해결인 부분은 무엇인지.

따라서 현재 확인한 것은 **진입·상태·효과의 일부 소스 사실을 DB로 회수할 수 있다**는 점이다. 동작 경계 전체의 자동 구성과 Jev 입력의 충분성은 아직 검증되지 않았다.
