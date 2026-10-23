from __future__ import annotations

import fcntl
import json
import os
import shutil
import stat
import subprocess
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "kubectl-ctxrm"


def write_config(
    path: Path,
    *,
    contexts: list[tuple[str, str, str]],
    clusters: list[str],
    users: list[str],
    current: str = "",
) -> bytes:
    data = {
        "apiVersion": "v1",
        "kind": "Config",
        "current-context": current,
        "contexts": [
            {"name": name, "context": {"cluster": cluster, "user": user}}
            for name, cluster, user in contexts
        ],
        "clusters": [
            {
                "name": name,
                "cluster": {
                    "server": f"https://{name}.invalid",
                    "insecure-skip-tls-verify": True,
                },
            }
            for name in clusters
        ],
        "users": [
            {"name": name, "user": {"token": f"secret-for-{name}"}}
            for name in users
        ],
    }
    content = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode()
    path.write_bytes(content)
    path.chmod(0o600)
    return content


def invoke(
    paths: list[Path],
    *arguments: str,
    explicit: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["KUBECONFIG"] = os.pathsep.join(str(path) for path in paths)
    if extra_env:
        env.update(extra_env)
    command = [str(TOOL), *arguments]
    if explicit is not None:
        command.extend(["--kubeconfig", str(explicit)])
    return subprocess.run(
        command,
        env=env,
        stdin=subprocess.DEVNULL,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def view(path: Path) -> dict:
    result = subprocess.run(
        ["kubectl", "--kubeconfig", str(path), "config", "view", "--raw", "-o", "json"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return json.loads(result.stdout)


def names(data: dict, plural: str) -> set[str]:
    return {entry["name"] for entry in data.get(plural, []) or []}


def backups(path: Path) -> list[Path]:
    return sorted(path.parent.glob(f"{path.name}.bak.*"))


def test_dry_run_is_byte_identical_and_creates_no_backup(tmp_path: Path) -> None:
    config = tmp_path / "config"
    original = write_config(
        config,
        contexts=[("dev", "dev-cluster", "dev-user")],
        clusters=["dev-cluster"],
        users=["dev-user"],
        current="dev",
    )

    result = invoke([config], "dev", "--dry-run")

    assert result.returncode == 0, result.stderr
    assert "DELETE context" in result.stdout
    assert "DELETE cluster" in result.stdout
    assert "DELETE user" in result.stdout
    assert "CLEAR  current-context" in result.stdout
    assert config.read_bytes() == original
    assert backups(config) == []


def test_unique_dependencies_and_current_context_are_removed(tmp_path: Path) -> None:
    config = tmp_path / "config"
    original = write_config(
        config,
        contexts=[
            ("dev", "dev-cluster", "dev-user"),
            ("prod", "prod-cluster", "prod-user"),
        ],
        clusters=["dev-cluster", "prod-cluster"],
        users=["dev-user", "prod-user"],
        current="dev",
    )

    result = invoke([config], "dev", "--yes")

    assert result.returncode == 0, result.stderr
    data = view(config)
    assert names(data, "contexts") == {"prod"}
    assert names(data, "clusters") == {"prod-cluster"}
    assert names(data, "users") == {"prod-user"}
    assert data.get("current-context", "") == ""
    prod_user = next(entry for entry in data["users"] if entry["name"] == "prod-user")
    assert prod_user["user"]["token"] == "secret-for-prod-user"
    assert stat.S_IMODE(config.stat().st_mode) == 0o600
    created_backups = backups(config)
    assert len(created_backups) == 1
    assert created_backups[0].read_bytes() == original


def test_shared_dependencies_are_kept(tmp_path: Path) -> None:
    config = tmp_path / "config"
    write_config(
        config,
        contexts=[
            ("dev", "shared-cluster", "shared-user"),
            ("prod", "shared-cluster", "shared-user"),
        ],
        clusters=["shared-cluster"],
        users=["shared-user"],
        current="prod",
    )

    result = invoke([config], "dev", "--yes")

    assert result.returncode == 0, result.stderr
    assert "KEEP   cluster" in result.stdout
    assert "KEEP   user" in result.stdout
    data = view(config)
    assert names(data, "contexts") == {"prod"}
    assert names(data, "clusters") == {"shared-cluster"}
    assert names(data, "users") == {"shared-user"}
    assert data.get("current-context") == "prod"


def test_cross_file_dependencies_are_deleted_and_each_file_is_backed_up(
    tmp_path: Path,
) -> None:
    context_file = tmp_path / "contexts"
    cluster_file = tmp_path / "clusters"
    user_file = tmp_path / "users"
    write_config(
        context_file,
        contexts=[("split", "split-cluster", "split-user")],
        clusters=[],
        users=[],
        current="split",
    )
    write_config(
        cluster_file,
        contexts=[],
        clusters=["split-cluster"],
        users=[],
    )
    write_config(
        user_file,
        contexts=[],
        clusters=[],
        users=["split-user"],
    )

    result = invoke([context_file, cluster_file, user_file], "split", "--yes")

    assert result.returncode == 0, result.stderr
    assert names(view(context_file), "contexts") == set()
    assert view(context_file).get("current-context", "") == ""
    assert names(view(cluster_file), "clusters") == set()
    assert names(view(user_file), "users") == set()
    assert len(backups(context_file)) == 1
    assert len(backups(cluster_file)) == 1
    assert len(backups(user_file)) == 1


def test_duplicate_context_across_files_fails_closed(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first_original = write_config(
        first,
        contexts=[("same", "a", "a")],
        clusters=["a"],
        users=["a"],
    )
    second_original = write_config(
        second,
        contexts=[("same", "b", "b")],
        clusters=["b"],
        users=["b"],
    )

    result = invoke([first, second], "same", "--yes")

    assert result.returncode == 1
    assert "defined in multiple files" in result.stderr
    assert first.read_bytes() == first_original
    assert second.read_bytes() == second_original
    assert backups(first) == []
    assert backups(second) == []


def test_current_context_scalar_in_another_file_is_cleared(tmp_path: Path) -> None:
    context_file = tmp_path / "context"
    current_file = tmp_path / "current"
    write_config(
        context_file,
        contexts=[("dev", "c", "u")],
        clusters=["c"],
        users=["u"],
    )
    write_config(
        current_file,
        contexts=[],
        clusters=[],
        users=[],
        current="dev",
    )

    result = invoke([context_file, current_file], "dev", "--yes")

    assert result.returncode == 0, result.stderr
    assert names(view(context_file), "contexts") == set()
    assert view(current_file).get("current-context", "") == ""
    assert len(backups(context_file)) == 1
    assert len(backups(current_file)) == 1


def test_explicit_file_disambiguates_duplicate_context(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    write_config(
        first,
        contexts=[("same", "a", "a")],
        clusters=["a"],
        users=["a"],
    )
    second_original = write_config(
        second,
        contexts=[("same", "b", "b")],
        clusters=["b"],
        users=["b"],
    )

    result = invoke([first, second], "same", "--yes", explicit=first)

    assert result.returncode == 0, result.stderr
    assert names(view(first), "contexts") == set()
    assert second.read_bytes() == second_original


def test_special_characters_in_context_name_are_exact_and_safe(tmp_path: Path) -> None:
    config = tmp_path / "config"
    target = "--dev.a/한 글 [1]"
    write_config(
        config,
        contexts=[(target, "cluster.with/slash", "사용자 name")],
        clusters=["cluster.with/slash"],
        users=["사용자 name"],
        current=target,
    )

    result = invoke([config], target, "--yes", "--no-backup")

    assert result.returncode == 0, result.stderr
    data = view(config)
    assert names(data, "contexts") == set()
    assert names(data, "clusters") == set()
    assert names(data, "users") == set()
    assert backups(config) == []


def test_missing_context_and_noninteractive_confirmation_do_not_modify(
    tmp_path: Path,
) -> None:
    config = tmp_path / "config"
    original = write_config(
        config,
        contexts=[("dev", "c", "u")],
        clusters=["c"],
        users=["u"],
    )

    missing = invoke([config], "absent", "--yes")
    no_confirmation = invoke([config], "dev")

    assert missing.returncode == 1
    assert "context not found" in missing.stderr
    assert no_confirmation.returncode == 1
    assert "rerun with --yes" in no_confirmation.stderr
    assert config.read_bytes() == original
    assert backups(config) == []


def test_symlink_cycle_reports_clean_error_without_traceback(tmp_path: Path) -> None:
    first = tmp_path / "cycle-a"
    second = tmp_path / "cycle-b"
    first.symlink_to(second)
    second.symlink_to(first)

    result = invoke([first], "dev", "--dry-run")

    assert result.returncode == 1
    assert "cannot resolve KUBECONFIG path" in result.stderr
    assert "Traceback" not in result.stderr


def test_snapshot_change_during_kubectl_view_fails_closed(tmp_path: Path) -> None:
    config = tmp_path / "config"
    write_config(
        config,
        contexts=[("dev", "old-cluster", "old-user")],
        clusters=["old-cluster"],
        users=["old-user"],
    )
    replacement = tmp_path / "replacement"
    replacement_bytes = write_config(
        replacement,
        contexts=[
            ("dev", "old-cluster", "old-user"),
            ("prod", "old-cluster", "prod-user"),
        ],
        clusters=["old-cluster"],
        users=["old-user", "prod-user"],
    )
    marker = tmp_path / "changed"
    fake_kubectl = tmp_path / "kubectl-race"
    fake_kubectl.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import os
            import subprocess
            import sys

            result = subprocess.run(
                [os.environ["REAL_KUBECTL"], *sys.argv[1:]],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            marker = os.environ["RACE_MARKER"]
            if "view" in sys.argv and not os.path.exists(marker):
                open(marker, "w").close()
                config_index = sys.argv.index("--kubeconfig") + 1
                os.replace(os.environ["RACE_REPLACEMENT"], sys.argv[config_index])
            sys.stdout.buffer.write(result.stdout)
            sys.stderr.buffer.write(result.stderr)
            sys.exit(result.returncode)
            """
        )
    )
    fake_kubectl.chmod(0o755)

    result = invoke(
        [config],
        "dev",
        "--yes",
        extra_env={
            "KUBECTL": str(fake_kubectl),
            "REAL_KUBECTL": shutil.which("kubectl") or "kubectl",
            "RACE_MARKER": str(marker),
            "RACE_REPLACEMENT": str(replacement),
        },
    )

    assert result.returncode == 1
    assert "changed while it was being read" in result.stderr
    assert config.read_bytes() == replacement_bytes
    assert backups(config) == []


def test_backup_publish_does_not_follow_dangling_symlink(tmp_path: Path) -> None:
    config = tmp_path / "config"
    write_config(
        config,
        contexts=[("dev", "c", "u")],
        clusters=["c"],
        users=["u"],
    )
    now = datetime.now(timezone.utc)
    victims: list[Path] = []
    for offset in range(-2, 31):
        timestamp = (now + timedelta(seconds=offset)).strftime("%Y%m%dT%H%M%SZ")
        victim = tmp_path / f"victim-{timestamp}"
        config.with_name(f"config.bak.{timestamp}").symlink_to(victim)
        victims.append(victim)

    result = invoke([config], "dev", "--yes")

    assert result.returncode == 0, result.stderr
    assert not any(victim.exists() for victim in victims)
    real_backups = [path for path in backups(config) if not path.is_symlink()]
    assert len(real_backups) == 1
    assert real_backups[0].name.endswith(".1")


def test_concurrent_prune_lock_fails_before_modification(tmp_path: Path) -> None:
    config = tmp_path / "config"
    original = write_config(
        config,
        contexts=[("dev", "c", "u")],
        clusters=["c"],
        users=["u"],
    )
    descriptor = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        result = invoke([config], "dev", "--yes")
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)

    assert result.returncode == 1
    assert "another ctxrm operation is active" in result.stderr
    assert config.read_bytes() == original
    assert backups(config) == []


def test_duplicate_dependency_definition_is_kept(tmp_path: Path) -> None:
    context_file = tmp_path / "context"
    cluster_a = tmp_path / "cluster-a"
    cluster_b = tmp_path / "cluster-b"
    write_config(
        context_file,
        contexts=[("dev", "duplicate", "unique-user")],
        clusters=[],
        users=["unique-user"],
    )
    write_config(cluster_a, contexts=[], clusters=["duplicate"], users=[])
    write_config(cluster_b, contexts=[], clusters=["duplicate"], users=[])

    result = invoke([context_file, cluster_a, cluster_b], "dev", "--yes")

    assert result.returncode == 0, result.stderr
    assert "duplicate definitions are ambiguous" in result.stdout
    assert names(view(cluster_a), "clusters") == {"duplicate"}
    assert names(view(cluster_b), "clusters") == {"duplicate"}
    assert names(view(context_file), "users") == set()
    assert backups(cluster_a) == []
    assert backups(cluster_b) == []


@pytest.mark.parametrize("flag", ["--dry-run", "--yes"])
def test_missing_kubeconfig_path_in_chain_is_reported_but_ignored(
    tmp_path: Path, flag: str
) -> None:
    config = tmp_path / "config"
    missing = tmp_path / "not-created"
    write_config(
        config,
        contexts=[("dev", "c", "u")],
        clusters=["c"],
        users=["u"],
    )

    result = invoke([missing, config], "dev", flag)

    assert result.returncode == 0, result.stderr
    assert "ignoring missing KUBECONFIG file" in result.stdout
