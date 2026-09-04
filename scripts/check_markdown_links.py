"""Validate repository-local links in Markdown files."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote

LINK_PATTERN = re.compile(r"!?\[[^\]]*]\((?P<target>[^)]+)\)")
EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "tel:", "data:")
EXCLUDED_DIRECTORY_NAMES = {
    ".git",
    ".pytest_cache",
    ".venv",
    "dist",
    "node_modules",
    "playwright-report",
    "target",
    "test-results",
    # Archived docs are frozen historical snapshots; their relative links to
    # paths that may have moved or been removed since are expected to break.
    "archive",
}


def markdown_files(repository_root: Path) -> tuple[Path, ...]:
    return tuple(
        path
        for path in repository_root.rglob("*.md")
        if not EXCLUDED_DIRECTORY_NAMES.intersection(path.parts)
    )


def local_target(markdown_file: Path, raw_target: str) -> Path | None:
    target = raw_target.strip().strip("<>")
    if not target or target.startswith("#") or target.startswith(EXTERNAL_PREFIXES):
        return None
    target_without_anchor = unquote(target.split("#", maxsplit=1)[0])
    if not target_without_anchor:
        return None
    return (markdown_file.parent / target_without_anchor).resolve()


def broken_links(repository_root: Path) -> tuple[str, ...]:
    failures: list[str] = []
    for markdown_file in markdown_files(repository_root):
        content = markdown_file.read_text(encoding="utf-8")
        for match in LINK_PATTERN.finditer(content):
            target = local_target(markdown_file, match.group("target"))
            if target is not None and not target.exists():
                relative_file = markdown_file.relative_to(repository_root)
                failures.append(f"{relative_file}: {match.group('target')}")
    return tuple(failures)


def main() -> int:
    repository_root = Path(__file__).resolve().parents[1]
    failures = broken_links(repository_root)
    if failures:
        print("Broken Markdown links:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print(f"Markdown links valid across {len(markdown_files(repository_root))} files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
