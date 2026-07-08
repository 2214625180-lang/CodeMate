from pathlib import Path

from app.core.config import settings

IGNORED_DIRS = {"node_modules", "dist", "build", ".next", "coverage", ".git"}
IGNORED_FILENAMES = {".env"}
IGNORED_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".ico",
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".mp3",
    ".wav",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".7z",
    ".lock",
}

LANGUAGE_BY_SUFFIX = {
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".py": "python",
    ".vue": "vue",
}


def detect_language(path: Path) -> str | None:
    return LANGUAGE_BY_SUFFIX.get(path.suffix.lower())


def should_ignore_path(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)

    if any(part in IGNORED_DIRS for part in relative.parts):
        return True

    if path.name in IGNORED_FILENAMES or path.name.startswith(".env."):
        return True

    if path.suffix.lower() in IGNORED_SUFFIXES:
        return True

    if path.is_file() and path.stat().st_size > settings.max_file_size_bytes:
        return True

    return False


def iter_source_files(root: Path) -> list[Path]:
    source_files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if should_ignore_path(path, root):
            continue
        if detect_language(path) is None:
            continue
        source_files.append(path)
    return sorted(source_files)
