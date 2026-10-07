"""Разрешение корпоративного контакта не открывает путь клиентским адресам."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / ".githooks" / "privacy-check"


@pytest.fixture
def git_hook_env():
    git_exec_path = subprocess.run(
        ["git", "--exec-path"], check=True, capture_output=True, text=True
    ).stdout.strip()
    return {**os.environ, "PATH": f"{git_exec_path}{os.pathsep}{os.environ.get('PATH', '')}"}


@pytest.mark.parametrize("scope", ["index", "tree"])
@pytest.mark.parametrize(
    ("path", "content", "allowed"),
    [
        ("src/content/company.yaml", "    email: example@cinimex.ru\n", True),
        ("src/content/company.yaml", "    email: example@example.org\n", False),
        ("examples/assessments/demo.yaml", "    email: example@cinimex.ru\n", False),
        ("src/content/company.yaml", "    note: example@cinimex.ru\n", False),
    ],
)
def test_privacy_hook_only_allows_company_email_field(tmp_path, scope, path, content, allowed):
    git_exec_path = subprocess.run(
        ["git", "--exec-path"], check=True, capture_output=True, text=True
    ).stdout.strip()
    env = {**os.environ, "PATH": f"{git_exec_path}{os.pathsep}{os.environ.get('PATH', '')}"}
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    target = tmp_path / path
    target.parent.mkdir(parents=True)
    target.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "--", path], cwd=tmp_path, check=True)
    result = subprocess.run(
        ["sh", str(HOOK), scope], cwd=tmp_path, env=env, capture_output=True, text=True
    )
    assert (result.returncode == 0) is allowed, result.stdout + result.stderr
    if not allowed:
        assert "адрес электронной почты" in result.stderr


@pytest.mark.parametrize("extension", ["pptx", "potx"])
def test_privacy_hook_blocks_presentation_files(tmp_path, extension):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    git_exec_path = subprocess.run(
        ["git", "--exec-path"], check=True, capture_output=True, text=True
    ).stdout.strip()
    env = {**os.environ, "PATH": f"{git_exec_path}{os.pathsep}{os.environ.get('PATH', '')}"}
    name = f"client.{extension}"
    (tmp_path / name).write_bytes(b"synthetic file")
    subprocess.run(["git", "add", "--", name], cwd=tmp_path, check=True)
    result = subprocess.run(
        ["sh", str(HOOK)], cwd=tmp_path, env=env, capture_output=True, text=True
    )
    assert result.returncode != 0
    assert "бинарный формат" in result.stderr


@pytest.mark.parametrize("scope", ["index", "tree"])
@pytest.mark.parametrize(
    ("path", "allowed"),
    [
        ("clients/invented-client/02-presentation/deck.json", False),
        ("clients/invented-client/README.md", False),
        ("docs/client-projects/invented-client/spec.md", False),
        ("docs/client-projects/README.md", False),
        ("clients/README.md", True),
        ("clients/.gitkeep", True),
    ],
)
def test_privacy_hook_blocks_client_folders_even_when_forced(
    tmp_path, git_hook_env, scope, path, allowed
):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    target = tmp_path / path
    target.parent.mkdir(parents=True)
    target.write_text("Invented fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "-f", "--", path], cwd=tmp_path, check=True)
    result = subprocess.run(
        ["sh", str(HOOK), scope],
        cwd=tmp_path,
        env=git_hook_env,
        capture_output=True,
        text=True,
    )
    assert (result.returncode == 0) is allowed, result.stderr
    if not allowed:
        assert "материалы реального клиента" in result.stderr


def history_git(root, *args):
    return subprocess.run(
        [
            "git",
            "-c",
            "user.name=Privacy test",
            "-c",
            "user.email=privacy@example.invalid",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.mark.parametrize(
    "path",
    ["clients/invented-client/spec.md", "docs/client-projects/invented-client/spec.md"],
)
def test_pre_push_blocks_client_file_deleted_in_later_commit(tmp_path, git_hook_env, path):
    history_git(tmp_path, "init", "-q", "-b", "main")
    hook_dir = tmp_path / ".githooks"
    hook_dir.mkdir()
    shutil.copy2(HOOK, hook_dir / "privacy-check")
    (hook_dir / "privacy-check").chmod(0o755)
    target = tmp_path / path
    target.parent.mkdir(parents=True)
    target.write_text("Invented fixture\n", encoding="utf-8")
    history_git(tmp_path, "add", "--", path)
    history_git(tmp_path, "commit", "-qm", "Add invented fixture")
    history_git(tmp_path, "rm", "--", path)
    history_git(tmp_path, "commit", "-qm", "Remove invented fixture")
    head = history_git(tmp_path, "rev-parse", "HEAD")
    clean_tree = subprocess.run(
        ["sh", str(HOOK), "tree"],
        cwd=tmp_path,
        env=git_hook_env,
        capture_output=True,
        text=True,
    )
    assert clean_tree.returncode == 0
    result = subprocess.run(
        ["sh", str(HOOK.parent / "pre-push"), "origin"],
        cwd=tmp_path,
        env=git_hook_env,
        input=f"refs/heads/main {head} refs/heads/main {'0' * 40}\n",
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert path in result.stderr


def test_pre_push_blocks_local_history_branch(tmp_path, git_hook_env):
    history_git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "README.md").write_text("Invented fixture\n", encoding="utf-8")
    history_git(tmp_path, "add", "--", "README.md")
    history_git(tmp_path, "commit", "-qm", "Initial fixture")
    head = history_git(tmp_path, "rev-parse", "HEAD")
    result = subprocess.run(
        ["sh", str(HOOK.parent / "pre-push"), "origin"],
        cwd=tmp_path,
        env=git_hook_env,
        input=f"refs/heads/local/session {head} refs/heads/local/session {'0' * 40}\n",
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "локальная история не публикуется" in result.stderr
