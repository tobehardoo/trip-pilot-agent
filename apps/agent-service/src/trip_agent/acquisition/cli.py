"""CLI for validating controlled official knowledge sources."""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from trip_agent.acquisition.registry import SourceCatalog


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trip-agent-acquisition")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="validate source registry TOML files")
    validate.add_argument("directory", type=Path)
    args = parser.parse_args(argv)

    try:
        if args.command != "validate":
            raise ValueError(f"unsupported acquisition command: {args.command}")
        catalog = SourceCatalog.load_directory(args.directory)
    except ValueError as error:
        print(json.dumps({"message": str(error), "status": "error"}, ensure_ascii=False))
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
