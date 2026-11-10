# Sift

**Status: concluded (2026-11-09).** This repository is the record of a finished exploratory study. It is not maintained.

## Summary (English)

Sift asked whether attaching **Jev** (TypeSafe's SystemOne ranker) to a strong coding agent lowers the cost of finding real vulnerabilities. Jev was used only as a candidate ranker; the agent investigated and wrote a test that had to fail on the vulnerable revision and pass on the fixed one.

The final study compared `vanilla` (agent alone) with `vanilla + Jev package` (a file-level code index plus Jev ranking) on four Go authorization bugs (Kite, Vikunja, Pocket ID, Arcane), three runs per arm, with all model costs included.

- **Jev found the entry to the search, not the answer.** In every case the fixed file or the route entry file was in Jev's top 4.
- **The saving grew with how long the agent would otherwise search.** Cost ratio (Jev / vanilla): Pocket ID 0.66, Arcane 0.81, Vikunja 0.92, Kite 1.03. Geometric mean 0.84. Jev's own fees were 1.1% of spend.
- **Verification failures cancelled most of the gain.** Valid findings were 12/12 for vanilla and 10/12 with Jev. Cost per valid finding: $2.57 vs $2.51. The two failures were a bad test and a sandbox-boundary violation, not search failures.
- **Conclusion:** search assistance helps on long searches, but the bottleneck for this workflow is turning a lead into a verified test.

These are exploratory results on four development cases, not a confirmatory claim. A confirmatory study was not run because only one post-training-cutoff Go case passed all eligibility gates. Full conclusion, limits, and what a follow-up study would need: [ADR 0009](docs/adr/0009-conclude-research-after-stage-0.md).

A later follow-up built 13 post-cutoff planted-defect cases to compare `vanilla`, BM25 ranking, and Jev ranking. It ended after the feasibility pilot because the model usage required to preserve the planned comparison exceeded the available budget. After fixing a location leak found in the pilot, no Jev or BM25 run was made, so the follow-up provides no new estimate of Jev's effect and does not change the conclusion above ([ADR 0011](docs/adr/0011-stop-phase2-after-pilot.md)).

A separate runner study used DeepSeek v4.1 Flash through Pi on the same planted cases. It also stopped after its pilot: the model found real, non-planted authorization bugs instead of the planted one in Gitea, so the pre-registered topdir validity rule could not be met. The Argo CD case was valid under a matched token budget, but the study provides no Jev estimate and does not change the conclusion above ([ADR 0012](docs/adr/0012-deepseek-v41-flash-planted-study.md)). The Claude pilot also produced one real authorization finding, which was reported privately; details are withheld.

The Grafana finding was reported through a private disclosure channel. Of the two Gitea findings, one was reported through a private security advisory and the other was submitted as a public fix PR. Advisory/PR IDs and technical details are kept outside this repository ([ADR 0013](docs/adr/0013-sift-closeout-and-byproducts.md)).

Project documents below are written in Korean.

## 요약

Sift는 **Jev(SystemOne)를 강한 코딩 에이전트에 붙이면 실제 취약점 발견의 비용 대비 성과가 좋아지는가**를 연구했다. Jev는 검증자가 아니라 후보 순위기로 썼고, 발견은 취약판에서 실패하고 수정판에서 통과하는 test로 판정했다.

최종 실험은 Go 인가 결함 개발 사례 4개에서 `vanilla`와 `vanilla + Jev package`(file 단위 code index + Jev 순위)를 arm당 3회 비교했다.

| 사례 | vanilla | Jev package | 비용 비율 | valid |
| --- | ---: | ---: | ---: | --- |
| Pocket ID | $3.823 | $2.513 | **0.657** | 3/3 → 2/3 |
| Arcane | $2.602 | $2.101 | **0.808** | 3/3 → 3/3 |
| Vikunja | $2.213 | $2.045 | 0.924 | 3/3 → 2/3 |
| Kite | $1.658 | $1.710 | 1.031 | 3/3 → 3/3 |

**결론: Jev는 탐색이 긴 문제에서 탐색 비용을 줄였지만, 이미 짧은 문제에서는 overhead였고, 발견을 검증 가능한 test로 만드는 단계의 실패가 이득을 대부분 상쇄했다.** valid finding당 비용은 $2.574 대 $2.511로 2.5% 차이였다.

개발 사례 4개의 탐색적 결과이며 confirmatory 주장이 아니다. 결론·한계·후속 연구 조건은 [ADR 0009](docs/adr/0009-conclude-research-after-stage-0.md)에 있다.

이후 학습 기준일 이후 리비전에 결함을 심은 13개 사례로 `vanilla` / BM25 / Jev를 독립 검증하려 했으나, 사전 설계를 유지하는 데 필요한 모델 사용량이 가용 예산을 넘어서 파일럿에서 종료했다. 누출 수정 후 Jev·BM25 실행과 본 실험은 없었으므로 Jev 효과의 새 추정치는 없고 위 결론도 바꾸지 않는다([ADR 0011](docs/adr/0011-stop-phase2-after-pilot.md)).

같은 심은 사례로 DeepSeek v4.1 Flash + Pi runner도 시험했으나 파일럿에서 종료했다. Gitea에서는 심은 결함이 아닌 다른 실제 인가 결함 후보 2건을 찾아 topdir 판정을 통과하지 못했고, Argo CD만 자원 일치 상한에서 valid였다. 이 두 후보는 pinned commit과 upstream main에서 HTTP 라우터 수준 재현과 최소 수정 검증을 마쳤다. 이 연구도 Jev 효과의 새 추정치를 주지 않으며 위 결론을 바꾸지 않는다([ADR 0012](docs/adr/0012-deepseek-v41-flash-planted-study.md)). Claude 파일럿에서는 실제 인가 결함 1건도 발견했다.

최종 제보 상태는 다음과 같다. Grafana 결함은 비공개 채널로 신고했다. Gitea 결함 2건 중 1건은 비공개 security advisory로, 1건은 공개 fix PR로 제출했다. 제보 ID·PR 번호·기술 상세는 저장소 밖에 둔다([ADR 0013](docs/adr/0013-sift-closeout-and-byproducts.md)).

## 저장소 구성

| 경로 | 내용 |
| --- | --- |
| [`docs/adr/`](docs/adr/) | 결정 기록 0001~0013. 연구의 경과, Phase 1 결론, 후속 파일럿 종료, 최종 byproduct 상태 |
| [`docs/jev-package-decision-memo.md`](docs/jev-package-decision-memo.md) | 2-arm 제품 비교 설계와 Stage 0 결과 분석 |
| [`results/`](results/) | 실행 46회의 비용·턴·판정·감사 표, Stage 0 Jev 순위 |
| [`experiments/logic-ranker/`](experiments/logic-ranker/) | Go 로직 버그 실험: route·unit 추출기, SSA call graph 보강, Jev 채점 |
| [`experiments/logic-ranker/e2e/`](experiments/logic-ranker/e2e/) | e2e harness: 격리 컨테이너, 취약·수정·decoy 판정, 감사, 통합 비용 상한 |
| [`experiments/planted/`](experiments/planted/) | 종료한 Phase 2 파일럿: 심은 인가 결함 사례·3-arm harness·오프라인 테스트 |
| [`testbed/`](testbed/) | 초기 C/C++ 메모리 안전성 파일럿의 testbed |
| [`DESIGN.md`](DESIGN.md) | 연구 설계 기록(2026-10-19 시점) |
| `archive/` | 2026-10-16 이전의 초기 시도. 경과 기록으로만 남긴다 |

## 재현에 필요한 것

- Claude Code CLI, Docker, Go 1.26/1.27, Python 3.13
- Jev API 키(`TYPESAFE_API_KEY`, `.env`에 둔다)
- 사례별 취약·수정 소스 트리. 저장소에 포함하지 않았다. 리비전은 [`experiments/logic-ranker/README.md`](experiments/logic-ranker/README.md)에 있다.

문서의 `~/sift-runs/...` 경로는 연구자 로컬의 원자료 위치이며 공개하지 않았다. 공개한 요약은 [`results/`](results/)에 있다.
