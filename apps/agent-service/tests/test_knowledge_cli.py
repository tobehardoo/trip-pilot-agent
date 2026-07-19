import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from trip_agent.retrieval.cli import (
    KnowledgeSettings,
    build_embedding_provider,
    build_parser,
    collect_markdown_files,
    import_markdown_paths,
    render_import_results,
    run_command,
)
from trip_agent.retrieval.repository import KnowledgeSearchRequest
from trip_agent.retrieval.service import KnowledgeImportResult


def test_collect_markdown_files_is_recursive_sorted_and_rejects_empty(tmp_path: Path) -> None:
    (tmp_path / "z.md").write_text("z", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "a.md").write_text("a", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("ignored", encoding="utf-8")

    assert collect_markdown_files(tmp_path) == (nested / "a.md", tmp_path / "z.md")

    with pytest.raises(ValueError, match="no Markdown"):
        collect_markdown_files(tmp_path / "ignored.txt")


def test_knowledge_settings_keeps_database_password_out_of_repr() -> None:
    settings = KnowledgeSettings(
        knowledge_database_url="postgresql://user:password@localhost:5432/db",
        knowledge_embedding_dimensions=32,
    )

    assert settings.database_url() == "postgresql://user:password@localhost:5432/db"
    assert "postgresql://user:password@localhost:5432/db" not in repr(settings)
    assert build_embedding_provider(settings).dimensions == 32


@dataclass
class RecordingImporter:
    calls: list[str] = field(default_factory=list)

    async def import_markdown(self, markdown: str) -> KnowledgeImportResult:
        self.calls.append(markdown)
        return KnowledgeImportResult(
            document_id=f"doc-{len(self.calls)}",
            version=1,
            chunk_count=2,
            status="created",
        )


def test_import_markdown_paths_reads_utf8_and_renders_json(tmp_path: Path) -> None:
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    first.write_text("第一份", encoding="utf-8")
    second.write_text("第二份", encoding="utf-8")
    importer = RecordingImporter()

    results = asyncio.run(import_markdown_paths((first, second), importer))

    assert [*importer.calls] == ["第一份", "第二份"]
    rendered = json.loads(render_import_results(results))
    assert rendered[0]["document_id"] == "doc-1"
    assert rendered[1]["status"] == "created"


@dataclass
class RecordingRepository:
    migrate_calls: int = 0
    search_requests: list[KnowledgeSearchRequest] = field(default_factory=list)

    async def migrate(self) -> None:
        self.migrate_calls += 1

    async def save_document(self, document: object, chunks: tuple[object, ...]) -> str:
        return "created"

    async def search(self, request: KnowledgeSearchRequest) -> tuple[object, ...]:
        self.search_requests.append(request)
        return ()


def test_run_command_dispatches_migrate_import_and_search(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = tmp_path / "guangzhou.md"
    document.write_text(
        """+++
document_id = "guangzhou-cli"
city = "广州"
category = "culture"
title = "广州文化"
source_url = "https://example.com/guangzhou"
source_name = "测试来源"
collected_at = "2026-07-19T08:00:00+08:00"
reliability_level = "CURATED"
version = 1
+++

# 文化

广州文化资料。""",
        encoding="utf-8",
    )
    repository = RecordingRepository()
    monkeypatch.setattr(
        "trip_agent.retrieval.cli.PsycopgKnowledgeRepository",
        lambda database_url: repository,
    )
    settings = KnowledgeSettings(
        knowledge_database_url="postgresql://user:password@localhost:5432/db",
        knowledge_embedding_dimensions=32,
    )

    migrate_args = build_parser().parse_args(["migrate"])
    assert json.loads(asyncio.run(run_command(migrate_args, settings))) == {"status": "migrated"}

    import_args = build_parser().parse_args(["import", str(document)])
    imported = json.loads(asyncio.run(run_command(import_args, settings)))
    assert imported[0]["document_id"] == "guangzhou-cli"
    assert repository.migrate_calls == 2

    search_args = build_parser().parse_args(
        ["search", "广州文化", "--city", "广州", "--limit", "2"]
    )
    assert json.loads(asyncio.run(run_command(search_args, settings))) == []
    assert repository.search_requests[0].city == "广州"
    assert repository.search_requests[0].limit == 2
