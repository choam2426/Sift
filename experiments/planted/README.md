# Phase 2: 심은 인가 결함 실험

> **상태: 파일럿에서 종료(2026-11-09).** 본 실험은 실행하지 않았다. 누출 수정 후 Jev·BM25 결과가 없으므로 이 실험으로 Jev 효과를 주장하지 않는다. 종료 결정과 파일럿 결과는 [ADR 0011](../../docs/adr/0011-stop-phase2-after-pilot.md)에 있다.

[ADR 0010](../../docs/adr/0010-phase2-planted-defects.md)의 구현이다. 학습 기준일 이후 리비전에 인가 검사 하나를 지운 사례를 만들고, `vanilla` / `rank-bm25` / `rank-jev` 세 arm으로 에이전트의 탐색 비용을 비교하도록 설계했다.

## 구성

| 파일 | 역할 |
| --- | --- |
| `repos.json` | 저장소 7개의 고정 커밋, Go 이미지, 선택 seed |
| `plant/` | 변이 도구(Go). `list`는 후보 나열, `apply`는 변이 적용, `strip`·`dropimport`는 테스트 함수 제거 |
| `pool.py` | 후보를 seed 순서로 섞고, 같은 패키지 테스트가 변이를 잡는지(kill) 판정 |
| `screening.md` | kill된 후보의 사전 선별 기록 |
| `case.py` | 사례 생성. 잡는 테스트를 지운 수정판·취약판 트리, file unit, 빌드 캐시 |
| `rank.py` | file unit을 BM25 또는 Jev(`jev-1.14.0`)로 순위화. Jev 호출은 기록해 재생할 수 있다 |
| `broker.py`, `tb_client.py` | 에이전트의 `./tb`를 호스트 broker로 전달. 에이전트는 Docker 소켓에 접근하지 못한다 |
| `harness.py` | `prepare` / `run` / `evaluate` / `teardown` |
| `analyze.py` | H1~H3 분석. 사례별 비용 비율의 기하평균과 저장소 단위 bootstrap CI |
| `test_planted.py`, `plant/main_test.go` | 오프라인 테스트. 모델·Docker·네트워크를 부르지 않는다 |

원자료는 저장소 밖 `~/sift-runs/planted/`에 둔다(`src/`, `pool/`, `cases/`, `runs/`). 생성한 13개 본 사례와 실행 원자료는 후속 연구를 위해 보존하지만, `runqueue.py run`을 활성 실험으로 실행하지 않는다.

## DeepSeek runner (별도 파일럿)

`pi_harness.py`와 `pi_runner/agent_ext.ts`는 Pi + `ollama-cloud/deepseek-v4.1-flash:1017`으로 같은 사례를 실행한다. `bash`는 broker를 거쳐 케이스 컨테이너에서만 돌고, 파일 도구는 workspace 밖으로 나가지 못한다. 주 지표는 달러가 아니라 모델 토큰이다.

별도 파일럿 결과는 [ADR 0012](../../docs/adr/0012-deepseek-v41-flash-planted-study.md)에 있다. Argo CD는 Mythos와 맞춘 토큰 상한에서 valid였지만, Gitea는 심은 결함이 아닌 다른 실제 결함을 찾아 topdir 판정을 통과하지 못했다. 이 runner로 본 실험은 시작하지 않았다.

## 종료 시점

mtime 누출을 고친 뒤의 `vanilla` 파일럿은 저장소 전체 범위에서 1/3, 최상위 디렉터리 범위에서 1/2 valid였다. 남은 Argo CD 최상위 디렉터리 파일럿 전에 종료했다. 수정 후 `rank-jev`·`rank-bm25`와 본 사례 실행은 0회다. 아래 절차는 재현과 구현 이해를 위한 기록이며, 종료한 큐를 계속하라는 지침이 아니다.

## 절차

```bash
# 1. 저장소 고정과 후보 판정
python3 pool.py prepare --repo gitea
python3 pool.py list --repo gitea
python3 pool.py kill --repo gitea --target 8 --workers 2

# 2. 선별(screening.md)을 거친 후보로 사례 생성
python3 case.py build --repo gitea --id '<candidate id>' --case gitea-1

# 3. 실행
python3 harness.py prepare --case gitea-1 --arm rank-jev --workspace ~/sift-runs/planted/runs/main/gitea-1-rank-jev-r1
python3 harness.py run --workspace ~/sift-runs/planted/runs/main/gitea-1-rank-jev-r1 --max-budget-usd 30
python3 harness.py teardown --workspace ~/sift-runs/planted/runs/main/gitea-1-rank-jev-r1

# 4. 분석
python3 analyze.py --runs ~/sift-runs/planted/runs/main
```

`plant/plant-linux`는 저장소에 넣지 않는다. 다음으로 만든다.

```bash
docker run --rm -v $PWD/plant:/p -w /p -e CGO_ENABLED=0 golang:1.27 go build -o /p/plant-linux .
```

`case.py`는 file unit 추출에 `experiments/logic-ranker/extract_units`를 리눅스용으로 빌드한 `~/sift-runs/planted/bin/extract-units-linux`를 쓴다.

## 평가

- 에이전트는 `findings/<name>/`에 `report.md`, `package.txt`(테스트 패키지 디렉터리), `test.go`를 낸다.
- 기술 판정은 세 트리에서 각 3회 실행한다.
  - 취약판: 제출 테스트 중 하나 이상이 실패
  - 수정판: 모든 제출 테스트가 통과
  - decoy(무관한 변경을 더한 취약판): 취약판과 같이 실패
- 컴파일 실패, panic, testify의 `test panicked`는 reject다.
- 최상위 `TestXxx` 함수와, 패키지가 이미 실행하는 testify suite의 메서드를 인식한다.
- valid는 다음을 모두 만족해야 한다.
  - 기술 판정 통과
  - `report.md`가 심은 파일을 지목
  - 테스트가 `.go` 소스를 읽어 판정하지 않음
  - 감사 위반 없음
  - 비용 상한 이내
