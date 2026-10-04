"""Exercise the workflow's remote release guard against real local Git repos."""
import os
from pathlib import Path
import subprocess

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / '.github/workflows/tests.yml'


def git(directory, *arguments):
    result = subprocess.run(
        ['git', *arguments], cwd=directory, check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


@pytest.fixture
def checkout(tmp_path):
    remote = tmp_path / 'remote'
    remote.mkdir()
    git(remote, 'init', '-b', 'main')
    git(remote, 'config', 'user.name', 'Synthetic Tester')
    git(remote, 'config', 'user.email', 'tester@example.invalid')
    git(remote, 'commit', '--allow-empty', '-m', 'Release source')
    commit = git(remote, 'rev-parse', 'HEAD')
    git(remote, 'tag', '-a', 'v0.1.1', '-m', 'Release candidate')
    local = tmp_path / 'checkout'
    git(tmp_path, 'clone', str(remote), str(local))
    # Reproduce actions/checkout converting the local annotated ref to a commit.
    git(local, 'update-ref', 'refs/tags/v0.1.1', commit)
    return local, remote, commit


def verify(local, commit):
    workflow = yaml.safe_load(WORKFLOW.read_text())
    step = next(
        step for step in workflow['jobs']['draft-release']['steps']
        if step.get('name') == 'Verify remote annotated tag and main'
    )
    return subprocess.run(
        ['bash', '-e', '-c', step['run']], cwd=local,
        env={**os.environ, 'RELEASE_TAG': 'v0.1.1', 'SOURCE_COMMIT': commit},
        capture_output=True, text=True,
    )


def test_remote_annotated_tag_passes_despite_checkout_flattening(checkout):
    local, _, commit = checkout
    assert git(local, 'cat-file', '-t', 'refs/tags/v0.1.1') == 'commit'
    result = verify(local, commit)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'Verified remote v0.1.1' in result.stdout


def test_remote_lightweight_tag_is_rejected(checkout):
    local, remote, commit = checkout
    git(remote, 'tag', '-d', 'v0.1.1')
    git(remote, 'tag', 'v0.1.1')
    result = verify(local, commit)
    assert result.returncode != 0
    assert 'Remote release tag must be annotated' in result.stdout


def test_moved_remote_tag_is_rejected(checkout):
    local, remote, commit = checkout
    git(remote, 'commit', '--allow-empty', '-m', 'Different source')
    git(remote, 'tag', '-f', '-a', 'v0.1.1', '-m', 'Moved tag')
    result = verify(local, commit)
    assert result.returncode != 0
    assert 'differs from tested commit' in result.stdout


def test_tagged_commit_outside_main_is_rejected(checkout):
    local, remote, _ = checkout
    git(remote, 'checkout', '-b', 'unmerged')
    git(remote, 'commit', '--allow-empty', '-m', 'Unmerged source')
    commit = git(remote, 'rev-parse', 'HEAD')
    git(remote, 'tag', '-f', '-a', 'v0.1.1', '-m', 'Unmerged tag')
    result = verify(local, commit)
    assert result.returncode != 0
    assert 'not on origin/main' in result.stdout
