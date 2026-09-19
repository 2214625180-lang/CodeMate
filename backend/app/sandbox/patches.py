import re
from dataclasses import dataclass


class InvalidUnifiedDiffError(ValueError):
    """Raised when a generated patch cannot be repaired without guessing content."""


@dataclass(frozen=True, slots=True)
class NormalizedPatch:
    content: str
    repaired_hunks: int


_HUNK_HEADER = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$"
)


def normalize_unified_diff_hunks(diff: str) -> NormalizedPatch:
    """Validate hunk bodies and repair only demonstrably wrong line counts.

    LLMs occasionally emit a complete hunk with a stale count in its header.
    Recomputing that count is deterministic when the hunk ends with unchanged
    context. A mismatched hunk ending on a change line may be truncated, so it
    is rejected instead of being turned into an apparently valid patch.
    """

    lines = diff.splitlines(keepends=True)
    normalized: list[str] = []
    repaired_hunks = 0
    index = 0
    saw_file_header = False

    while index < len(lines):
        line = lines[index]
        if line.startswith("diff --git "):
            saw_file_header = True
            normalized.append(line)
            index += 1
            continue
        if _starts_file_header(lines, index):
            saw_file_header = True
            normalized.append(line)
            index += 1
            continue

        header_text = line.rstrip("\r\n")
        if not header_text.startswith("@@ "):
            normalized.append(line)
            index += 1
            continue

        if not saw_file_header:
            raise InvalidUnifiedDiffError("hunk appears before a file header")
        match = _HUNK_HEADER.fullmatch(header_text)
        if match is None:
            raise InvalidUnifiedDiffError(f"invalid hunk header: {header_text}")

        body_start = index + 1
        body_end = body_start
        while body_end < len(lines):
            candidate = lines[body_end]
            if (
                candidate.startswith("diff --git ")
                or candidate.startswith("@@ ")
                or _starts_file_header(lines, body_end)
            ):
                break
            body_end += 1

        body = lines[body_start:body_end]
        old_count, new_count, last_change_index = _count_hunk_lines(body)
        declared_old_count = int(match.group(2) or "1")
        declared_new_count = int(match.group(4) or "1")

        if (declared_old_count, declared_new_count) != (old_count, new_count):
            has_trailing_context = any(
                body_line.startswith(" ") for body_line in body[last_change_index + 1 :]
            )
            if last_change_index < 0 or not has_trailing_context:
                raise InvalidUnifiedDiffError(
                    "hunk line counts are wrong and the hunk has no trailing context; "
                    "the generated patch may be truncated"
                )
            newline = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
            suffix = match.group(5)
            line = (
                f"@@ -{match.group(1)},{old_count} +{match.group(3)},{new_count} @@"
                f"{suffix}{newline}"
            )
            repaired_hunks += 1

        normalized.append(line)
        normalized.extend(body)
        index = body_end

    return NormalizedPatch(content="".join(normalized), repaired_hunks=repaired_hunks)


def _starts_file_header(lines: list[str], index: int) -> bool:
    return (
        lines[index].startswith("--- ")
        and index + 1 < len(lines)
        and lines[index + 1].startswith("+++ ")
    )


def _count_hunk_lines(body: list[str]) -> tuple[int, int, int]:
    old_count = 0
    new_count = 0
    last_change_index = -1

    for index, line in enumerate(body):
        if line.startswith(" "):
            old_count += 1
            new_count += 1
        elif line.startswith("-"):
            old_count += 1
            last_change_index = index
        elif line.startswith("+"):
            new_count += 1
            last_change_index = index
        elif line.startswith("\\ No newline at end of file"):
            continue
        else:
            rendered = line.rstrip("\r\n")
            raise InvalidUnifiedDiffError(f"invalid line in hunk: {rendered!r}")

    return old_count, new_count, last_change_index
