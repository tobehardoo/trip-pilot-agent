"""CLI for validating controlled official knowledge sources."""

import argparse
import asyncio
import json
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import quote

import psycopg
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from trip_agent.acquisition.freshness import FreshnessReportService, render_freshness_report
from trip_agent.acquisition.registry import SourceCatalog
from trip_agent.acquisition.repository import PsycopgAcquisitionRepository


class AcquisitionSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=(".env", "../../.env"),
        extra="ignore",
        frozen=True,
    )

    knowledge_database_url: SecretStr | None = None
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="trip-agent-acquisition")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="validate source registry TOML files")
    validate.add_argument("directory", type=Path)
    freshness = commands.add_parser("freshness", help="report source verification freshness")
    freshness.add_argument("directory", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        catalog = SourceCatalog.load_directory(args.directory)
        if args.command == "freshness":
            repository = PsycopgAcquisitionRepository(AcquisitionSettings().database_url())
            report = asyncio.run(FreshnessReportService(repository=repository).generate(catalog))
            print(render_freshness_report(report))
            return 0
        if args.command != "validate":
            raise ValueError(f"unsupported acquisition command: {args.command}")
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

    resource_count = sum(len(source.resource_urls) for source in catalog.sources)
    print(
        json.dumps(
            {
                "resource_count": resource_count,
                "source_count": len(catalog.sources),
                "status": "valid",
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
