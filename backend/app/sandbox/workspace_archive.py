import base64
import hashlib
import io
import tarfile
from pathlib import Path


class WorkspaceArchiveError(ValueError):
    pass


def create_archive(workspace: Path, *, max_bytes: int, max_files: int) -> tuple[str, str]:
    stream = io.BytesIO()
    count = 0
    total_size = 0
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        for path in sorted(workspace.rglob("*")):
            if path.is_symlink():
                raise WorkspaceArchiveError(f"Workspace symlink is forbidden: {path.name}")
            relative = path.relative_to(workspace)
            if any(part == ".git" for part in relative.parts):
                continue
            if not (path.is_file() or path.is_dir()):
                raise WorkspaceArchiveError(f"Unsupported workspace entry: {relative}")
            count += 1
            if count > max_files:
                raise WorkspaceArchiveError("Workspace contains too many entries")
            if path.is_file():
                total_size += path.stat().st_size
                if total_size > max_bytes:
                    raise WorkspaceArchiveError("Workspace content exceeds the size limit")
            archive.add(path, arcname=relative.as_posix(), recursive=False)
            if stream.tell() > max_bytes:
                raise WorkspaceArchiveError("Workspace archive exceeds the size limit")
    payload = stream.getvalue()
    if len(payload) > max_bytes:
        raise WorkspaceArchiveError("Workspace archive exceeds the size limit")
    return base64.b64encode(payload).decode("ascii"), hashlib.sha256(payload).hexdigest()


def extract_archive(
    encoded: str,
    destination: Path,
    *,
    expected_sha256: str,
    max_bytes: int,
    max_files: int,
) -> None:
    try:
        payload = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise WorkspaceArchiveError("Workspace archive is not valid base64") from exc
    if len(payload) > max_bytes:
        raise WorkspaceArchiveError("Workspace archive exceeds the size limit")
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise WorkspaceArchiveError("Workspace archive digest mismatch")
    destination.mkdir(parents=True, exist_ok=False)
    root = destination.resolve()
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        members = archive.getmembers()
        if len(members) > max_files:
            raise WorkspaceArchiveError("Workspace archive contains too many entries")
        if sum(member.size for member in members if member.isfile()) > max_bytes:
            raise WorkspaceArchiveError("Workspace archive expands beyond the size limit")
        for member in members:
            if member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
                raise WorkspaceArchiveError("Workspace archive contains an unsafe entry")
            target = (root / member.name).resolve()
            try:
                target.relative_to(root)
            except ValueError as exc:
                raise WorkspaceArchiveError("Workspace archive path escapes its root") from exc
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise WorkspaceArchiveError("Workspace archive file is unreadable")
            with target.open("wb") as output:
                output.write(source.read())
            target.chmod(member.mode & 0o755)
