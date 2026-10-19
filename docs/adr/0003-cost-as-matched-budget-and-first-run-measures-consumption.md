# ADR 0003: 비용을 핵심 통제 변수로 두고, 첫 실행은 소비량을 잰다

- 날짜: 2026-10-16
- 상태: 채택
- 관련: [ADR 0001](0001-jev-collaboration-research-charter.md), [ADR 0002](0002-cybergym-images-as-shared-testbed.md)

## 맥락

활성 설계의 연구 질문은 같은 예산에서 조건을 비교하는 것이다. 예산을 무엇으로 재고 얼마로 둘지, 회계 방식은 미정이었다.

비슷한 벤치마크의 관행을 확인했다.

- CyberGym은 모든 에이전트에 과제당 100 iteration을 걸고, 설정을 맞춰 에이전트당 평균 약 2달러가 되게 했다. 100스텝 안에 풀 수 있는 과제 대부분이 끝난다고 분석했다. 실행 시간 제한은 없다. 제출 양식은 과제당 평균 비용(USD)과 평균 소요 시간(초)을 함께 보고하게 한다.
- Cybench는 반복 횟수로 제한한다. SWE-agent는 인스턴스당 비용 상한을 쓰며 기본값은 3달러다.

즉 관행은 반복 횟수 상한과 과제당 몇 달러의 비용 상한이고, 시간은 상한이 아니라 보고 항목이다.

## 결정

1. **상한은 금전 비용 하나다.** 반복 횟수는 Jev 호출이 섞이면 조건 간 비교가 되지 않는다. 실행 시간은 상한으로 두지 않고 기록한다. Jev가 돈과 시간을 다르게 바꾸는지는 기록된 소요 시간으로 본다. 반복 횟수와 소요 시간은 CyberGym 양식처럼 함께 기록한다.
2. **첫 단독 실행은 상한을 정하는 실행이 아니라 소비량을 재는 실행이다.** 30달러는 안전장치로만 건다. 이 값은 관행의 과제당 몇 달러보다 크다. Mythos 5.1은 저 논문들의 모델보다 토큰당 3배 이상 비싸고, Claude Code는 OpenHands 100 iteration보다 훨씬 많이 읽기 때문이다. 가격 차이만 반영하면 CyberGym의 2달러는 7달러 안팎에 해당한다. 거친 환산이다.
3. **본 비교의 과제당 비용 상한은 첫 실행들의 소비량을 보고 고정한다.** 단독 실행이 보통 자연스럽게 끝나는 수준으로 두고, 그 뒤에는 바꾸지 않는다.
4. 실행기(`testbed.py run`)는 모델 식별자, effort, 상한, 비용, 턴 수, 토큰 사용량, 소요 시간, 빌드·실행 시간을 실행 기록에 남긴다. 상한과 effort는 실행마다 명시적으로 지정한다.
5. **비용의 단위는 Claude Code가 정가 기준으로 추정한 값이다.** 상한도 그 값에 걸린다. 개발 머신은 구독 인증으로 돌므로 실제 청구와 다르지만, 정가 추정치는 인증 방식과 무관하게 같은 양을 같은 값으로 재므로 조건 간 비교에 적합하다. CyberGym도 보고 비용을 추정치로 두고 있다. 실행기는 시간으로 세션을 끊지 않으므로, 토큰을 쓰지 않은 채 멈춘 세션은 사람이 중단한다.

## 재검토 조건

첫 실행들의 소비량 확인 후 본 비교 상한을 정할 때, 모델 가격이 바뀔 때, 전향적 평가 설계 시.

## 출처

- CyberGym 논문(arXiv:2506.02548v3) 실험 설정: "a maximum of 100 iterations per task", "an average cost of approximately $2.0 per task for each agent". https://arxiv.org/abs/2506.02548
- CyberGym SUBMISSION.md: 비용과 소요 시간 보고 의무, 예시 값 4.75 USD, 620초. https://github.com/sunblaze-ucb/cybergym/blob/main/SUBMISSION.md
- Cybench `run_benchmark.py`의 `--max_iterations`. https://github.com/andyzorigin/cybench
- SWE-agent `per_instance_cost_limit` 기본값 3.0. https://github.com/SWE-agent/SWE-agent/blob/main/sweagent/agent/models.py
- Claude Mythos 5.1 가격: 입력 10달러, 출력 50달러, 캐시 읽기 0.25달러(1M 토큰당). https://platform.claude.com/docs/en/models/mythos-5-1/overview
