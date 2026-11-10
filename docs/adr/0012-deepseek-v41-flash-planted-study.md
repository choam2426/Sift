# ADR 0012: DeepSeek v4.1 Flash로 planted-defect 실험을 별도로 실행한다

- 날짜: 2026-11-09
- 상태: **파일럿 종료(중단).** 자원 일치 상한으로 다시 실행했지만, Gitea repo와 topdir 모두 심은 결함이 아닌 다른 실제 결함을 제출해 topdir 2/2가 불가능해졌다. 본 실험은 시작하지 않는다.
- 관련: [ADR 0010](0010-phase2-planted-defects.md)(사례·절차), [ADR 0011](0011-stop-phase2-after-pilot.md)(Claude 종료)

## 맥락

[ADR 0011](0011-stop-phase2-after-pilot.md)은 Claude 사용량 때문에 Phase 2를 파일럿에서 종료했다. 사용자는 다른 모델로 같은 사례·하네스를 시험해 보자고 했고, Pi에서 `ollama-cloud/deepseek-v4.1-flash:1017`을 사용할 수 있음을 확인했다.

모델이 바뀌면 Jev 효과의 질문도 바뀐다. 이 연구의 질문은 다음과 같다.

> **Jev 또는 BM25 순위가 DeepSeek v4.1 Flash의 심은 인가 결함 탐색 비용을 줄이는가?**

Claude 결과와 DeepSeek 결과를 한 표에 합치지 않는다. 모델·토큰 회계·runner 경계가 다르기 때문이다.

## 결정

### 1. 모델과 실행 설정

- 모델: `ollama-cloud/deepseek-v4.1-flash:1017`
- thinking: `medium` (파일럿과 본 실험 동일)
- runner: Pi 1.5.0, `--mode json`, 확장 `experiments/planted/pi_runner/agent_ext.ts`
- 실행 그룹: `~/sift-runs/planted/runs/ds41/` (Claude 결과와 분리)
- Pi의 `write`/`edit`/`read`는 workspace 안으로 제한하고, `bash`는 broker를 거쳐 케이스 컨테이너 안에서만 실행한다. 에이전트가 작성한 코드는 호스트에서 실행되지 않는다.
- 웹 도구는 주지 않는다. Pi 프로세스 자체는 모델 API에 접근하지만, 에이전트의 도구에는 네트워크 경로가 없다.

### 2. 주 지표는 모델 토큰이다

Pi/Ollama 응답의 달러 비용은 0으로 보고된다. Claude의 `total_cost_usd`와 비교할 수 없으므로, 이 연구의 주 지표를 다음과 같이 정의한다.

- **run tokens** = 모든 assistant 메시지의 `usage.totalTokens` 합. `input`, `output`, `cacheRead`, `cacheWrite`를 포함한다.
- **censoring**: valid 실행은 실제 토큰, invalid 실행은 상한 토큰으로 계산한다([ADR 0007](0007-three-arm-ranker-evaluation-after-independent-review.md) 결정 4와 같은 원칙).
- Jev의 입력 토큰과 달러 비용은 별도로 기록한다. 에이전트 토큰과 합치지 않는다.
- H1·H2의 판정 기준은 토큰 비율에 그대로 적용한다: H1 < 0.90, H2 < 0.95, CI 상한 < 1.0. H3는 저장소 크기 기울기와 대형 ≤ 0.80을 본다.

### 3. 파일럿

- 사례: `pilot-gitea`(대형), `pilot-argocd`(중형). **Grafana는 파일럿과 본 실험에서 제외한다.** 파일럿 중 발견된 Grafana의 실제 인가 결함이 심은 결함과 무관한 교란으로 작용했고, 그 결함은 별도 VDP로 신고했다. 중립화 패치를 적용하기 전에는 Grafana를 다시 쓰지 않는다.
- `vanilla` 2회, 저장소 전체 범위. 상한은 아래 §3.1의 Mythos 사용량과 같게 한다. 벽시계 상한 4시간.
  - 최초 상한 10M과 15M 실행은 예비 기록이다. Gitea는 10M/90턴에서 상한에 걸려 심은 파일을 읽지 못했고, Argo CD는 10M/79턴과 15M/110턴에서 상한에 걸렸다. 두 번 모두 심은 guard를 지목했지만 테스트를 제출하지 못했다.
- 판정: 2/2 valid면 저장소 전체 범위로 고정. 1/2 이하면 topdir로 좁혀 같은 사례를 다시 실행한다. topdir에서도 2/2가 아니면 본 실험을 보류한다.
- 파일럿 결과로 바꿀 수 있는 것은 범위 문구, 상한, 반복 수, harness 결함뿐이다. 질문·arm·가설은 바꾸지 않는다.

### 3.1 자원 일치: Mythos가 쓴 토큰을 DeepSeek 상한으로

Mythos 파일럿의 `stream.jsonl`에서 assistant 메시지 usage를 합산했다. cache read가 대부분을 차지하므로 달러 비용과 같지는 않지만, 같은 사례에 투입한 모델 처리량의 가장 가까운 비교값이다.

| 사례 | 범위 | Mythos tokens | DeepSeek 상한 |
| --- | --- | ---: | ---: |
| pilot-argocd | repo | 71,402,001 | 72,000,000 |
| pilot-gitea | repo | 112,276,855 | 112,000,000 |
| pilot-gitea | topdir | 63,658,305 | 64,000,000 |
| pilot-grafana | topdir | 140,327,292 | 제외 |

DeepSeek의 토큰 회계는 Pi `usage.totalTokens` 합이고, Mythos는 assistant 이벤트의 input·cache_creation·cache_read·output 합이다. 둘 다 cache read를 포함한다. 상한은 이 표의 값으로 고정하고, 파일럿 결과를 본 뒤 본 실험 상한을 별도로 정한다.

### 3.2 harness 수정 (파일럿 재개 전)

- `bash` 도구가 `/gocache`와 `/go/pkg/mod`를 직접 읽는 명령을 거부한다.
- Pi TASK에 "컴파일 아티팩트·빌드 캐시를 역분석하지 말고 소스를 읽으라"는 규칙을 넣는다.
- agent cache의 `/src` 경로와 런타임 `/src/<repo>` 경로가 달라 중복 엔트리가 생기는 문제는 남는다. 캐시 읽기를 막았으므로 이번 파일럿에서는 영향이 없지만, 본 실험 전에 같은 경로로 재생성한다.

### 4. 본 실험 (실행하지 않음)

파일럿이 topdir 2/2에 도달하지 못해 이 절은 실행하지 않았다. 아래는 기록용 계획이다.

- 사례: 기존 13개 중 Grafana 2개를 뺀 11개.
- arm: `vanilla`, `rank-bm25`, `rank-jev` (ADR 0010과 같다).
- 반복 수: 파일럿의 토큰 분포와 완주 가능성을 본 뒤, 본 실행 전에 이 ADR에 추가한다. 기본 후보는 2회다.
- 상한: 파일럿에서 성공한 실행의 토큰 분포를 보고, 본 실행 전에 고정한다.
- 순서: `runqueue.py`와 같은 블록 무작위화. 블록마다 모든 (사례, arm)을 한 번씩.
- 중단 규칙: 파일럿 미달, 상한 때문에 유효 실행이 대부분 잘리는 경우, 또는 가용 실행량으로 완주할 수 없을 때 시작하지 않는다.
- 규모 점검: 11개 사례 × 3arm × 2회 = 66회다. 자원 일치 상한 64–112M tokens/run을 적용하면 4.2B–7.4B tokens가 필요하다. 이 규모는 파일럿에서 완주 가능성과 자원 한도를 확인한 뒤에만 시작한다.

### 5. 사전 smoke (증거 아님)

Gotify `smoke-gotify` 사례에서 어댑터와 평가기를 점검했다.

- 26턴, 1,156,131 tokens, 132초, `valid=True`
- 심은 결함 `api/message.go`의 `CreateMessage` 소유권 검사 누락을 찾고, 취약판 실패·수정판 통과·decoy 실패하는 테스트를 제출했다.
- 이 실행은 runner 경계와 평가 연결을 확인하기 위한 것이며, Jev 효과의 증거로 쓰지 않는다.

## 파일럿 기록 (2026-11-09)

| 사례 | 범위 | 상한 | 토큰 | 턴 | 첫 읽기 | 결과 |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| pilot-gitea | repo | 10M | 10,016,149 | 90 | — | no-finding, cap |
| pilot-argocd | repo | 10M | 10,028,139 | 79 | 8 | no-finding, cap. 심은 `ActionOverride` guard를 지목한 뒤 중단 |
| pilot-argocd | repo | 15M | 15,169,546 | 110 | 4 | no-finding, cap. 심은 guard를 다시 지목했으나 `/gocache` 역분석에 예산을 씀 |
| pilot-argocd | repo | 72M | 14,125,340 | 104 | 4 | **valid**, 캐시 차단 후 완주 |
| pilot-gitea | repo | 112M | 63,122,477 | 176 | 14 | rejected: 비심은 실제 결함 1건을 제출 |
| pilot-gitea | topdir | 64M | 46,980,296 | 154 | 21 | rejected: 비심은 실제 결함 1건을 제출 |

repo 범위는 **1/2 valid**다. Argo CD는 캐시 차단 후 14.1M에서 valid finding을 냈고, Gitea는 63.1M에서 심은 파일을 읽었지만 다른 실제 결함을 제출해 rejected됐다(수정판에서도 그 결함은 남아 있으므로 테스트가 실패한다). 규칙에 따라 topdir로 좁혔지만, Gitea topdir에서도 다른 실제 결함을 제출해 rejected됐다. 따라서 topdir 2/2는 불가능하고, 본 실험은 시작하지 않는다.

### 관찰: 빌드 캐시 탐색

두 번째 Argo CD 실행(15M)은 `/gocache`의 사전 빌드 아카이브와 현재 빌드를 비교해 고정 소스를 복원하려 했다. agent cache는 vuln 트리로 만들어지므로 고정 소스가 들어 있지는 않았지만, 캐시는 `/src`에서, 런타임 소스는 `/src/<repo>`에서 빌드되어 같은 패키지의 중복 엔트리가 생겼고, 모델은 이를 단서로 오인했다. 이 탐색은 26분과 수백만 토큰을 썼다.

다음 실행을 한다면 (1) agent cache를 런타임과 같은 `/src/<repo>` 경로로 다시 만들고, (2) `bash`에서 `/gocache`와 `/go/pkg/mod`를 직접 읽는 명령을 차단하고, (3) TASK에 "컴파일 아티팩트를 역분석하지 말고 소스를 읽으라"는 규칙을 넣는다. 이는 파일럿 결과로 바꿀 수 있는 harness 결함 범위다.

## 부산물

- **Grafana (Claude 파일럿):** 실제 인가 결함 1건을 발견해 비공개 VDP로 신고했다. 상세 내용·PoC·제출 ID는 embargo 때문에 저장소에 기록하지 않는다.
- **Gitea (DeepSeek 파일럿):** 심은 결함이 아닌 실제 결함 후보 2건을 발견했다. 2026-11-09에 pinned commit과 upstream `main`에서 독립 재현하고, HTTP 라우터 수준 재현과 최소 수정 검증까지 마쳤다. 1건은 비공개 security advisory로 제보했고, 1건은 공개 fix PR로 올렸다. 파일·경로·PoC·수정 내용은 저장소에 기록하지 않고, 상세 내용은 저장소 밖 비공개 패키지와 공개 PR에 둔다. 최종 상태는 [ADR 0013](0013-sift-closeout-and-byproducts.md)에 있다.
- **Argo CD:** 심은 `ActionOverride` guard를 찾아 valid. 이 연구의 유일한 파일럿 valid다. 심은 결함이므로 부산물이 아니라 연구 결과다.

## 종료 결정

**본 실험을 시작하지 않는다.** 파일럿의 topdir 판정이 2/2에 도달할 수 없기 때문이다.

- Argo CD: 캐시 차단 + 72M 상한에서 14.1M tokens, 104턴, **valid**. 심은 `ActionOverride` guard를 찾아 테스트까지 제출했다.
- Gitea repo: 112M 상한에서 63.1M tokens, 176턴, rejected. **다른 실제 결함**을 제출했다. 그 결함은 수정판에도 남아 있어 테스트가 양쪽에서 실패한다.
- Gitea topdir: 64M 상한에서 47.0M tokens, 154턴, rejected. **또 다른 실제 결함**을 제출했다.

DeepSeek Flash는 실제 결함을 찾는 능력이 있다. Gitea 후보 2건은 독립 재현과 최소 수정으로 확인했다. 그러나 이 benchmark의 평가는 **심은 결함 하나**만 인정하므로, 코드베이스에 있는 다른 실제 결함을 찾으면 invalid가 된다. topdir를 좁혀도 `services/` 안에 다른 실제 결함이 있어 교란이 사라지지 않았다. 이것은 탐색 예산이나 Jev 효과의 문제가 아니라 **사례·평가 설계와 모델의 탐색 목표가 맞지 않는 문제**다.

따라서 이 연구는 Jev, BM25, vanilla의 상대 성능에 대해 아무 결론도 내지 않는다. H1·H2·H3는 미평가다. Phase 1의 결론([ADR 0009](0009-conclude-research-after-stage-0.md))도 바뀌지 않는다.

### 재개 조건

1. 심은 결함 외에 경쟁하는 실제 결함이 적은 사례 집합을 새로 고른다.
2. 또는 평가가 "심은 결함"이 아니라 "수정 가능한 실제 결함"을 인정하도록 바뀐다. 이 경우 사례별 수정 오라클을 새로 정의해야 한다.
3. 또는 task를 특정 파일·함수로 더 좁혀 다른 결함을 탐색할 여지를 줄인다. 다만 이는 난이도와 Jev 순위의 의미를 바꾼다.
4. 위 중 하나를 택한 뒤, 사례 수·arm·반복·상한을 새 프로토콜로 다시 고정한다.

## 한계

- 모델이 다르므로 Claude Phase 1·2와 직접 비교할 수 없다.
- DeepSeek의 토큰 회계는 제공자 usage에 의존한다. 모델·서비스가 바뀌면 재현성이 달라진다.
- Pi는 Claude Code식 샌드박스가 없다. 이 연구는 bash를 broker로 프록시하고 파일 도구를 경로 제한해 경계를 만든다. 호스트에서 실행되는 Pi 프로세스 자체의 신뢰는 전제한다.
- 파일 도구와 bash의 경로 시점이 다르다(`src/<repo>/...` vs 모듈 루트). runner가 `src/<repo>` 경로를 번역하고, findings는 두 위치를 병합한다.
- Grafana 제외로 대형 저장소 표본이 Gitea 하나로 줄어 H3의 크기 조절 검정력이 약하다.
- 토큰은 달러 비용이 아니다. 캐시 읽기 단가가 다르면 실제 비용 순서와 다를 수 있다.

## 종료 후

이 연구는 파일럿에서 종료했다. 결과는 `ds41` 그룹에만 두고 Claude 결과와 합치지 않는다. 재개하려면 위의 재개 조건을 먼저 충족하고 새 프로토콜을 사전 등록한다. 이 ADR의 H1·H2·H3는 미평가로 남긴다.
