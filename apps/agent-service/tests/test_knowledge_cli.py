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
    main,
    render_import_results,
    run_command,
)
from trip_agent.retrieval.embeddings import (
    DashScopeEmbeddingProvider,
    EmbeddingProviderError,
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

    async def search_distinct_documents(
        self, request: KnowledgeSearchRequest
    ) -> tuple[object, ...]:
        return await self.search(request)


def test_embedding_factory_requires_a_dashscope_key_for_real_vectors() -> None:
    with pytest.raises(ValueError, match="DASHSCOPE_API_KEY"):
        build_embedding_provider(
            KnowledgeSettings(
                _env_file=None,
                knowledge_embedding_provider="dashscope",
                dashscope_api_key=None,
            )
        )

    provider = build_embedding_provider(
        KnowledgeSettings(
            _env_file=None,
            knowledge_embedding_provider="dashscope",
            dashscope_api_key="local-test-key",
            dashscope_embedding_base_url="https://dashscope.example/compatible-mode/v1",
            knowledge_embedding_dimensions=1024,
        )
    )

    assert isinstance(provider, DashScopeEmbeddingProvider)
    assert provider.model_name == "text-embedding-v4"
    assert provider.dimensions == 1024


def test_run_command_dispatches_migrate_import_and_search(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
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

    suite = tmp_path / "evaluation.toml"
    suite.write_text(
        """
suite_id = "cli-evaluation"
version = 1
as_of = 2026-07-23
[corpus_versions]
guangzhou-cli = 1
[[cases]]
case_id = "culture"
query = "广州文化"
city = "广州"
expected_document_ids = ["guangzhou-cli"]
""",
        encoding="utf-8",
    )
    evaluate_args = build_parser().parse_args(
        ["evaluate", str(suite), "--top-k", "3"]
    )
    evaluated = json.loads(asyncio.run(run_command(evaluate_args, settings)))
    assert evaluated["status"] == "DEMO_ONLY"
    assert evaluated["top_k"] == 3
    assert repository.migrate_calls == 2

    monkeypatch.setenv(
        "KNOWLEDGE_DATABASE_URL",
        "postgresql://user:password@localhost:5432/db",
    )
    assert main(["evaluate", str(suite), "--top-k", "3"]) == 3
    cli_report = json.loads(capsys.readouterr().out)
    assert cli_report["status"] == "DEMO_ONLY"

    assert main(["evaluate", str(tmp_path / "missing.toml")]) == 2
    cli_error = json.loads(capsys.readouterr().out)
    assert cli_error["status"] == "error"
    assert "password" not in json.dumps(cli_error)

    class FailingEmbeddingProvider:
        model_name = "failing-real-model"
        dimensions = 32

        async def embed_texts(self, texts):
            raise EmbeddingProviderError("secret provider response")

    monkeypatch.setattr(
        "trip_agent.retrieval.cli.build_embedding_provider",
        lambda configured_settings: FailingEmbeddingProvider(),
    )
    assert main(["evaluate", str(suite)]) == 2
    provider_error = json.loads(capsys.readouterr().out)
    assert provider_error == {
        "message": "embedding provider operation failed",
        "status": "error",
    }
    assert "secret" not in json.dumps(provider_error)
