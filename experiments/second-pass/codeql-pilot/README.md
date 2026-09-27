# CodeQL 호출 관계 파일럿

> 상태: 2026-09-24 **실행 완료한 도구 확인**. CodeQL을 A 실험의 관계 추출기로 사용하는 결정은 [ADR 0006](../../../docs/adr/0006-codeql-source-relation-experiment.md)에 기록했다. 2026-09-25에는 2차 점수 대상을 함수 묶음 전체로 [변경](../../../docs/adr/0007-second-pass-scores-related-code-group.md)했다. 대상 리비전, CodeQL 버전, 빌드 옵션 또는 질의가 바뀌면 아래 결과를 다시 확인한다.

## 목적과 실행 조건

2차 입력에 넣을 관계를 C, C++, Rust, Go, Python에서 같은 도구로 추출할 수 있는지 확인했다. CodeQL CLI **2.27.1**로 각 대상의 로컬 데이터베이스를 만들고 이 디렉터리의 질의를 실행했다. 원본 데이터베이스, BQRS, CSV는 Git에서 제외된 `../runs/codeql-pilot-2026-09-24/`에 있다. 설치한 CodeQL 번들은 저장소 밖 `/tmp/sift-codeql-2.27.1/codeql/`에 있다. 대상은 각자의 공개 소스 라이선스가 있는 스냅샷이다. [CodeQL CLI 사용 조건](https://github.com/github/codeql-cli-binaries/blob/main/LICENSE.md)

| 대상과 고정 리비전 | DB 생성 | 질의에서 확인한 호출 근거 | 질의 결과 행 |
|---|---|---|---:|
| 7-Zip 26.01 C, `8c63d71ff886bda90c86db28466287f977374237` | `C/XzDec.c` 한 컴파일 단위, Clang 수동 빌드 | `XzUnpacker_Code → MixCoder_Code`, `C/XzDec.c:1071` | 정적 대상 115, 미해결 호출 34 |
| TinyXML2 10.0.0 C++, `321ea883b7190d4e85cae5512a12e5eaa8f8731f` | `tinyxml2.cpp` 한 컴파일 단위, Clang++ 수동 빌드 | `XMLDocument::Parse → XMLNode::ParseDeep`, `tinyxml2.cpp:2575` | 정적 대상 589 |
| tar 0.4.44 Rust, `0671e117756b3daf9d6e5951b22c39a516e5fd53` | `none`, Rust 1.98.1·Cargo | `unpack → unpack_dir`, `src/entry.rs:499,622` | 정적 대상 180 |
| go-jose v4.0.0 Go, `2658f467ede28af28a7883041677ff460dda3f69` | 자동 빌드, Go 1.27.1 | `decompress → inflate`, `encoding.go:82` | 선언된 대상 51 |
| urllib3 2.5.0 Python, `aaab4eccc10c965897540b21e15f11859d0b62e7` | `none`, Python 3 | `DeflateDecoder.decompress → DeflateDecoder.decompress`, `src/urllib3/response.py:86` | 추론된 대상 41, 미해결 호출 206 |

행 수는 각 질의가 **표에 적힌 한 파일**에서 출력한 수다. 내장 함수·외부 함수와 반복 호출을 포함한다. 언어마다 해석 방식이 다르므로 이 수를 완전성이나 언어 간 성능 비교로 쓰지 않는다. Python의 41행은 호출 대상이 추론된 **관계 행**이며 고유 호출 지점 수가 아니다. `getACall()` 기반 질의는 실행 시 가능한 대상을 근사한다. Go의 `getTarget()`은 선언된 대상이고 인터페이스 호출의 실제 대상과 다를 수 있다. Rust의 `getStaticTarget()`도 정적 대상이다. C++의 가상 호출도 `getTarget()`만으로 실행 시 구현을 확정할 수 없다. [Python 함수 질의](https://codeql.github.com/docs/codeql-language-guides/functions-in-python/), [Go 호출 그래프](https://codeql.github.com/docs/codeql-language-guides/codeql-library-for-go/#call-graph), [C/C++ 호출 대상](https://codeql.github.com/codeql-standard-libraries/cpp/semmle/code/cpp/exprs/Call.qll/predicate.Call%24FunctionCall%24getTarget.0.html), [Rust 호출 대상](https://codeql.github.com/codeql-standard-libraries/rust/codeql/rust/elements/internal/CallImpl.qll/predicate.CallImpl%24Impl%24Call%24getARuntimeTarget.0.html)

## 미해결 관계

- 7-Zip `MixCoder_Code`의 `IStateCoder.Code2` 호출(`C/XzDec.c:610`, `:731`)과 `Filter` 호출(`:647`)은 `cpp/unresolved_calls_7zip.ql`에 나타났다. 대상 함수 대입이 코드에 있다는 사실만으로 **호출 시 대상**이 확정되지는 않는다.
- urllib3의 `self._decoder.decompress(data)`(`src/urllib3/response.py:510`)와 `_flush_decoder`의 같은 형태 호출(`:530`)은 `python/unresolved_calls.ql`에 나타났다. 대상 메서드를 추론한 41행에는 이 호출이 없다.

따라서 지금의 출력은 **2차 입력에 바로 넣을 완성 그래프가 아니다.** 질의 결과에는 동명이인 함수의 정의 위치가 없고, 대상 스냅샷의 함수 ID와도 아직 결합하지 않았다. `static_target` 또는 `inferred_target`을 곧바로 `direct_call`·`resolved_indirect_call`로 바꾸면 잘못된 관계를 보낼 수 있다. A용 추출기를 만들 때는 정의 위치로 함수를 식별하고, 원본 호출 줄을 대조하며, 실제 대상이 입증되지 않은 호출은 `unresolved`로 남겨야 한다. 필드 쓰기·읽기와 동일 객체 연결도 이 파일럿에서는 검증하지 않았다. 이 제한은 [2차 입력 제안](../input-v1.md)의 근거 규칙을 유지한다.

## 재현 범위

`cpp/`, `rust/`, `go/`, `python/`의 `qlpack.yml`은 이번 번들에 포함된 라이브러리 버전을 고정한다. 각 `.ql` 파일은 위 표의 파일만 선택한다. DB 생성에는 다음 설정을 사용했다.

```text
7-Zip:    codeql database create DB --language=cpp --source-root=targets/7zip --command='/usr/bin/clang -std=c99 -c C/XzDec.c -o /tmp/sift-codeql-7zip-xzdec.o'
TinyXML2: codeql database create DB --language=cpp --source-root=targets/tinyxml2-10.0.0 --command='/usr/bin/clang++ -std=c++11 -c tinyxml2.cpp -o /tmp/sift-codeql-tinyxml2.o'
tar-rs:   codeql database create DB --language=rust --build-mode=none --source-root=targets/tar-0.4.44
go-jose:  codeql database create DB --language=go --source-root=targets/go-jose-v4.0.0
urllib3:  codeql database create DB --language=python --build-mode=none --source-root=targets/urllib3-2.5.0
```

로컬 Clang의 한 컴파일 단위만 분석한 C/C++ 결과를 프로젝트 전체의 관계 범위로 해석하지 않는다. 전체 범위를 만들려면 실제 빌드 설정을 반영해 각 컴파일 단위를 추출해야 한다. [CodeQL의 빌드 방식](https://docs.github.com/en/code-security/concepts/code-scanning/codeql/codeql-for-compiled-languages)

2026-09-25에는 7-Zip의 **1차 범위 C 파일 55개**를 별도 CodeQL DB로 만들고 정의 위치·호출 간선·미해결 호출 질의를 실행했다. 그 결과와 376개 앵커의 Jev 호출 전 입력은 [직접 호출 입력 사전 점검](../direct-call-dry-run.md)에 있다. 이 전체 범위 점검의 컴파일 구성도 기본 Clang 한 가지이며 조건부 코드의 모든 구성을 대표하지 않는다.
