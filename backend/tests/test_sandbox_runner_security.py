import subprocess
from pathlib import Path

import pytest

from app.core.config import settings
from app.sandbox.runner import SandboxService


def test_workspace_copy_does_not_dereference_or_expose_symlinks(monkeypatch, tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    outside_secret = tmp_path / "outside-secret.txt"
    outside_secret.write_text("HOST_SECRET_123", encoding="utf-8")
    (source / "leak.txt").symlink_to(outside_secret)
    monkeypatch.setattr(settings, "sandbox_workspace_dir", str(tmp_path / "sandboxes"))

    sandbox = SandboxService()
    workspace = sandbox.create_workspace(run_id="run-symlink", source_path=str(source))

    assert not (workspace / "leak.txt").exists()
    assert sandbox.list_files(workspace=workspace) == []

    # A patch or tool must not be able to reintroduce a readable symlink either.
    (workspace / "leak.txt").symlink_to(outside_secret)
    assert sandbox.list_files(workspace=workspace) == []
    with pytest.raises(PermissionError, match="Symbolic links"):
        sandbox.read_file(workspace=workspace, file_path="leak.txt")


def test_git_diff_includes_new_files_and_replays_complete_patch(monkeypatch, tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    run_git(source, "init")
    run_git(source, "config", "user.email", "test@example.com")
    run_git(source, "config", "user.name", "CodeMate Test")
    (source / "existing.txt").write_text("before\n", encoding="utf-8")
    run_git(source, "add", "existing.txt")
    run_git(source, "commit", "-m", "baseline")

    (source / "existing.txt").write_text("after\n", encoding="utf-8")
    (source / "new.txt").write_text("new content\n", encoding="utf-8")
    run_git(source, "add", "--intent-to-add", "new.txt")
    proposed_patch = run_git(source, "diff", "--binary", "--no-ext-diff").stdout
    run_git(source, "reset", "--hard", "HEAD")
    run_git(source, "clean", "-fd")
    (source / "baseline-untracked.txt").write_text("keep untracked\n", encoding="utf-8")

    monkeypatch.setattr(settings, "sandbox_workspace_dir", str(tmp_path / "sandboxes"))
    sandbox = SandboxService()
    workspace = sandbox.create_workspace(run_id="run-new-file", source_path=str(source))

    assert sandbox.apply_patch(workspace=workspace, diff=proposed_patch)["ok"] is True
    final_diff = sandbox.git_diff(workspace=workspace)

    assert "diff --git a/existing.txt b/existing.txt" in final_diff
    assert "diff --git a/new.txt b/new.txt" in final_diff
    assert "new file mode" in final_diff
    assert "baseline-untracked.txt" not in final_diff
    run_git(source, "apply", "--check", input_text=final_diff)
    run_git(source, "apply", input_text=final_diff)
    assert (source / "existing.txt").read_text(encoding="utf-8") == "after\n"
    assert (source / "new.txt").read_text(encoding="utf-8") == "new content\n"


def test_apply_patch_repairs_demo_hunk_counts(monkeypatch, tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    run_git(source, "init")
    (source / "cart.js").write_text(
        "export function coupon(subtotal, amount) {\n"
        "  // Keep checkout totals valid.\n"
        "  return subtotal - amount;\n"
        "}\n",
        encoding="utf-8",
    )
    run_git(source, "add", "cart.js")
    run_git(source, "commit", "-m", "baseline")
    malformed_patch = """diff --git a/cart.js b/cart.js
--- a/cart.js
+++ b/cart.js
@@ -1,5 +1,5 @@
 export function coupon(subtotal, amount) {
   // Keep checkout totals valid.
-  return subtotal - amount;
+  return Math.max(0, subtotal - amount);
 }
"""

    monkeypatch.setattr(settings, "sandbox_workspace_dir", str(tmp_path / "sandboxes"))
    workspace = SandboxService().create_workspace(run_id="run-malformed", source_path=str(source))

    result = SandboxService().apply_patch(workspace=workspace, diff=malformed_patch)

    assert result["ok"] is True
    assert result["patch_normalized"] is True
    assert "Math.max(0, subtotal - amount)" in (workspace / "cart.js").read_text(encoding="utf-8")


def test_apply_patch_rejects_mismatched_hunk_that_may_be_truncated(monkeypatch, tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    run_git(source, "init")
    (source / "cart.js").write_text("const total = subtotal - amount;\n", encoding="utf-8")
    run_git(source, "add", "cart.js")
    run_git(source, "commit", "-m", "baseline")
    truncated_patch = """diff --git a/cart.js b/cart.js
--- a/cart.js
+++ b/cart.js
@@ -1,2 +1,2 @@
-const total = subtotal - amount;
+const total = Math.max(0, subtotal - amount);
"""

    monkeypatch.setattr(settings, "sandbox_workspace_dir", str(tmp_path / "sandboxes"))
    workspace = SandboxService().create_workspace(run_id="run-truncated", source_path=str(source))

    result = SandboxService().apply_patch(workspace=workspace, diff=truncated_patch)

    assert result["ok"] is False
    assert result["exit_code"] == 128
    assert "may be truncated" in result["stderr"]
    assert (workspace / "cart.js").read_text(encoding="utf-8") == "const total = subtotal - amount;\n"


def run_git(
    repository: Path,
    *arguments: str,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        input=input_text,
        capture_output=True,
        text=True,
        check=True,
    )
