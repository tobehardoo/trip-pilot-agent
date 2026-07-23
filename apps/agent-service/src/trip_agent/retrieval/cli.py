"""Operator-facing import and search commands for the city knowledge store."""

import argparse
import asyncio
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Literal, Protocol
from urllib.parse import quote

import psycopg
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from trip_agent.retrieval.embeddings import (
    DashScopeEmbeddingProvider,
    EmbeddingProvider,
    EmbeddingProviderError,
    HashEmbeddingProvider,
)
from trip_agent.retrieval.evaluation import (
    KnowledgeRetrievalEvaluator,
    RetrievalEvaluationSuite,
    render_evaluation_report,
)
from trip_agent.retrieval.repository import (
    KnowledgeCitation,
    KnowledgeSearchRequest,
    PsycopgKnowledgeRepository,
)
from trip_agent.retrieval.service import KnowledgeImporter, KnowledgeImportResult


class KnowledgeSettings(BaseSettings):
    """Environment-backed settings with a safe explicit DSN override."""

    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=(".env", "../../.env"),
        extra="ignore",
        frozen=True,
    )

    knowledge_database_url: SecretStr | None = None
    knowledge_embedding_provider: Literal["demo", "dashscope"] = "demo"
    knowledge_embedding_dimensions: int = Field(default=1024, ge=1, le=4096)
    knowledge_embedding_model: str = "text-embedding-v4"
    dashscope_api_key: SecretStr | None = None
    dashscope_embedding_base_url: str = (
        "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    dashscope_embedding_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    knowledge_chunk_size: int = Field(default=1000, ge=128, le=4000)
    knowledge_chunk_overlap: int = Field(default=100, ge=0, le=1000)
    postgres_host: str = "localhost"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_db: str = "trip_pilot"
    postgres_user: str = "trip_pilot"
    postgres_password: SecretStr = SecretStr("replace-with-local-password")

    def database_url(self) -> str:
        if self.knowledge_database_url is not None:
            value = self.knowledge_database_url.get_secret_value().strip()
            if value:
                return value
        password = quote(self.postgres_password.get_secret_value(), safe="")
        return (
            f"postgresql://{quote(self.postgres_user, safe='')}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{quote(self.postgres_db, safe='')}"
        )


class KnowledgeSearchRepository(Protocol):
    async def search(self, request: KnowledgeSearchRequest) -> tuple[KnowledgeCitation, ...]: ...


def collect_markdown_files(path: Path) -> tuple[Path, ...]:
    """Return a deterministic list of Markdown files from a file or directory."""

    resolved = path.expanduser()
    if not resolved.exists():
        raise ValueError(f"knowledge path does not exist: {path}")
    if resolved.is_file():
        files = (resolved,) if resolved.suffix.casefold() == ".md" else ()
    else:
        files = tuple(sorted(item for item in resolved.rglob("*.md") if item.is_file()))
    if not files:
        raise ValueError(f"knowledge path contains no Markdown files: {path}")
    return files


def build_embedding_provider(settings: KnowledgeSettings) -> EmbeddingProvider:
    if settings.knowledge_embedding_provider == "demo":
        return HashEmbeddingProvider(dimensions=settings.knowledge_embedding_dimensions)
    if settings.knowledge_embedding_provider == "dashscope":
        key = settings.dashscope_api_key
        if key is None or not key.get_secret_value().strip():
            raise ValueError("DASHSCOPE_API_KEY is required for DashScope embeddings")
        return DashScopeEmbeddingProvider(
            api_key=key.get_secret_value(),
            base_url=settings.dashscope_embedding_base_url,
            model_name=settings.knowledge_embedding_model,
            dimensions=settings.knowledge_embedding_dimensions,
            timeout_seconds=settings.dashscope_embedding_timeout_seconds,
        )
    raise ValueError(
        f"unsupported knowledge embedding provider: {settings.knowledge_embedding_provider}"
    )


async def import_markdown_paths(
    paths: Iterable[Path],
    importer: KnowledgeImporter,
) -> tuple[KnowledgeImportResult, ...]:
    results: list[KnowledgeImportResult] = []
    for path in paths:
        results.append(await importer.import_markdown(path.read_text(encoding="utf-8")))
    return tuple(results)


def render_import_results(results: tuple[KnowledgeImportResult, ...]) -> str:
    return json.dumps(
        [result.model_dump(mode="json") for result in results],
        ensure_ascii=False,
        indent=2,
    )


def render_search_results(results: tuple[KnowledgeCitation, ...]) -> str:
    return json.dumps(
        [result.model_dump(mode="json") for result in results],
        ensure_ascii=False,
        indent=2,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="trip-agent-knowledge")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="apply knowledge schema migrations")

    import_command = commands.add_parser("import", help="import Markdown knowledge documents")
    import_command.add_argument("path", type=Path)

    search_command = commands.add_parser("search", help="search stored knowledge chunks")
    search_command.add_argument("query")
    search_command.add_argument("--city", required=True)
    search_command.add_argument("--limit", type=int, default=5)
    search_command.add_argument("--min-similarity", type=float, default=0.0)
    search_command.add_argument("--category")
    search_command.add_argument("--applicable-season")
    search_command.add_argument("--traveler-type")

    evaluate_command = commands.add_parser("evaluate", help="evaluate retrieval quality")
    evaluate_command.add_argument("suite", type=Path)
    evaluate_command.add_argument("--top-k", type=int, default=5)
    evaluate_command.add_argument("--minimum-recall", type=float, default=0.8)
    evaluate_command.add_argument("--minimum-mrr", type=float, default=0.7)
    return parser


async def run_command(args: argparse.Namespace, settings: KnowledgeSettings | None = None) -> str:
    settings = settings or KnowledgeSettings()
    repository = PsycopgKnowledgeRepository(settings.database_url())
    provider = build_embedding_provider(settings)

    if args.command == "migrate":
        await repository.migrate()
        return json.dumps({"status": "migrated"})
    if args.command == "import":
        paths = collect_markdown_files(args.path)
        await repository.migrate()
        importer = KnowledgeImporter(
            repository=repository,
            embedding_provider=provider,
            max_characters=settings.knowledge_chunk_size,
            overlap_characters=settings.knowledge_chunk_overlap,
        )
        return render_import_results(await import_markdown_paths(paths, importer))
    if args.command == "search":
        query_vector = (await provider.embed_texts((args.query,)))[0]
        request = KnowledgeSearchRequest(
            city=args.city,
            embedding=query_vector,
            limit=args.limit,
            min_similarity=args.min_similarity,
            category=args.category,
            applicable_season=args.applicable_season,
            traveler_type=args.traveler_type,
        )
        return render_search_results(await repository.search(request))
    if args.command == "evaluate":
        suite = RetrievalEvaluationSuite.load(args.suite)
        evaluator = KnowledgeRetrievalEvaluator(
            embedding_provider=provider,
            repository=repository,
        )
        report = await evaluator.evaluate(
            suite,
            top_k=args.top_k,
            minimum_recall=args.minimum_recall,
            minimum_mrr=args.minimum_mrr,
        )
        return render_evaluation_report(report)
    raise ValueError(f"unsupported knowledge command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        output = asyncio.run(run_command(args))
    except ValueError as error:
        print(json.dumps({"message": str(error), "status": "error"}, ensure_ascii=False))
        return 2
    except psycopg.Error:
        print(
            json.dumps(
                {"message": "knowledge database operation failed", "status": "error"},
                ensure_ascii=False,
            )
        )
        return 2
    except EmbeddingProviderError:
        print(
            json.dumps(
                {"message": "embedding provider operation failed", "status": "error"},
                ensure_ascii=False,
            )
        )
        return 2
    print(output)
    if args.command == "evaluate" and json.loads(output)["status"] != "PASSED":
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
