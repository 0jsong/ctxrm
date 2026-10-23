# ctxrm

[English](README.md) | 한국어

컨텍스트 이름 하나를 기준으로 kubeconfig에서 다음 항목을 안전하게 정리하는 로컬
`kubectl` 플러그인입니다.

1. 대상 `context` 삭제
2. 다른 context가 더 이상 참조하지 않는 경우에만 관련 `cluster` 삭제
3. 다른 context가 더 이상 참조하지 않는 경우에만 관련 `user` 삭제
4. 대상이 활성 context이면 dangling 값이 남지 않도록 `current-context` 해제

실제 Kubernetes API에는 연결하지 않으며 로컬 kubeconfig 파일만 다룹니다.

## 설치

Python 3.10 이상과 `kubectl`이 필요합니다. 별도 Python 패키지는 필요하지 않습니다.
Linux에서 검증했으며, `fcntl` directory lock을 사용하므로 Windows 네이티브 실행은
지원하지 않습니다. macOS 호환성은 아직 검증하지 않았습니다.

```bash
git clone https://github.com/0jsong/ctxrm.git
cd ctxrm
mkdir -p "$HOME/.local/bin"
install -m 0755 kubectl-ctxrm "$HOME/.local/bin/kubectl-ctxrm"
export PATH="$HOME/.local/bin:$PATH"
kubectl ctxrm --version
kubectl plugin list
```

새 셸에서도 사용하려면 `PATH` 설정을 `~/.bashrc` 또는 `~/.zshrc`에 추가하십시오.
저장소를 clone한 뒤에는 `make install`로도 설치할 수 있습니다.

다음처럼 실행합니다. `k`가 `kubectl`의 alias이면 `k ctxrm`으로 줄일 수 있습니다.

```bash
kubectl ctxrm test-context --dry-run
kubectl ctxrm test-context
```

비대화형 환경에서는 명시적으로 승인해야 합니다.

```bash
kubectl ctxrm test-context --yes
```

특정 파일 하나만 대상으로 삼으려면:

```bash
kubectl ctxrm test-context \
  --kubeconfig ~/.kube/config \
  --dry-run
```

## 안전 정책

활성 context를 제거했다면 다음 사용할 context를 명시적으로 선택하십시오.

```bash
kubectl config use-context remaining-context
```

- 기본 실행도 먼저 계획을 출력한 뒤 확인을 받습니다.
- `--dry-run`은 파일과 백업을 전혀 만들지 않습니다.
- 변경 파일마다 `config.bak.YYYYMMDDTHHMMSSZ` 형식의 백업을 남깁니다.
- 모든 변경을 임시 복사본에 먼저 적용하고 `kubectl config view`로 검증한 다음
  원본과 교체합니다.
- 계획을 만든 후 원본 파일이 바뀌면 중단합니다.
- 같은 디렉터리에서 동시에 실행되는 이 도구끼리는 directory lock으로 직렬화하며,
  이미 실행 중이면 원본을 건드리지 않고 재시도를 요청합니다.
- cluster 또는 user를 다른 context가 공유하면 그 항목은 `KEEP`합니다.
- cluster 또는 user가 여러 물리 파일에 같은 이름으로 중복 정의돼 있으면
  모호하므로 해당 dependency는 `KEEP`합니다.
- context 자체가 여러 물리 파일에 중복 정의돼 있으면 중단합니다. 이 경우
  `--kubeconfig FILE`로 정리할 물리 파일을 명시하십시오.

`KUBECONFIG`가 여러 경로를 포함하면 각 파일을 따로 읽어서, 파일을 가로지르는
cluster/user 참조까지 확인합니다. 존재하지 않는 경로는 kubectl의 merge 규칙처럼
무시하지만 계획에 경고로 표시합니다.

검사 범위는 `--kubeconfig FILE` > `KUBECONFIG` > `~/.kube/config` 순서입니다.
`--kubeconfig FILE`을 사용하면 해당 파일 하나만 검사하므로, 다른 파일과 공유하는
항목을 보호하려면 관련 파일을 모두 `KUBECONFIG`에 포함하고 이 옵션을 생략하십시오.
directory lock은 이 도구의 동시 실행을 막습니다. 다른 편집기나 kubectl의 쓰기 작업은
이 lock을 사용하지 않으므로 작업 중 파일을 동시에 편집하지 마십시오.

백업에도 원본과 동일한 인증정보가 포함되므로 kubeconfig와 같은 수준으로
보호해야 합니다. 필요하다면 성공 후 백업을 남기지 않는 `--no-backup`을 사용할 수
있습니다. 이 옵션에서도 실행 중 rollback용 임시 복사본은 사용합니다.

삭제에는 kubectl의 기본 kubeconfig writer를 사용하므로 YAML 주석과 항목 순서 등
표현 형식은 다시 정렬될 수 있습니다. 기본 백업은 변경 전 원문을 그대로 보존합니다.
여러 물리 파일의 최종 교체는 파일별 atomic replace와 실패 시 rollback을 사용하지만,
프로세스가 강제 종료되는 상황까지 포함한 단일 cross-file transaction은 아닙니다.
교체 순서는 `current-context` 해제, context 삭제, orphan dependency 삭제 순으로 잡아
중간 종료 시 살아 있는 context가 먼저 삭제된 dependency를 가리킬 위험을 줄입니다.

## 예시

공유하지 않는 항목은 함께 제거됩니다.

```text
Plan for context "kind-test":
  DELETE context "kind-test" @ /home/me/.kube/config
  DELETE cluster "kind-test" @ /home/me/.kube/config (orphan after context removal)
  DELETE user    "kind-test" @ /home/me/.kube/config (orphan after context removal)
  CLEAR  current-context @ /home/me/.kube/config
```

공유 항목은 남습니다.

```text
KEEP   user "shared-user" (still used by "production" @ /home/me/.kube/config)
```

## 테스트

테스트는 실제 사용자 kubeconfig와 완전히 분리된 임시 fixture만 사용합니다.

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest -q
```

Python 패키지 의존성은 개발·테스트에만 필요합니다. GitHub Actions는 Python 3.10과
3.12에서 동일한 fixture 테스트를 실행합니다.

## 업데이트 및 제거

업데이트는 clone한 저장소에서 `git pull --ff-only` 후 설치 명령을 다시 실행하십시오.
제거하려면 설치한 `~/.local/bin/kubectl-ctxrm` 파일을 삭제하면 됩니다.

Krew 기본 인덱스에는 아직 등록하지 않았으며 위 수동 설치 방식을 사용합니다.

## 라이선스

[MIT](LICENSE)
