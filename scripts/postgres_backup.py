"""Binary-safe PostgreSQL backup and restore through the production Compose stack."""

import argparse
import subprocess
from pathlib import Path

def compose_command(env_file: Path, project_name: str | None) -> tuple[str, ...]:
    command = ["docker", "compose"]
    if project_name:
        command.extend(("-p", project_name))
    command.extend(("-f", "compose.prod.yaml", "--env-file", str(env_file)))
    return tuple(command)


def backup(
    destination: Path,
    database: str,
    user: str,
    env_file: Path,
    project_name: str | None,
) -> None:
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as output:
        subprocess.run(
            (
                *compose_command(env_file, project_name),
                "exec", "-T", "postgres", "pg_dump", "-U", user, "-d", database, "-Fc",
            ),
            check=True,
            stdout=output,
        )


def restore(
    source: Path,
    database: str,
    user: str,
    env_file: Path,
    project_name: str | None,
) -> None:
    source = source.resolve(strict=True)
    with source.open("rb") as backup_input:
        subprocess.run(
            (
                *compose_command(env_file, project_name),
                "exec",
                "-T",
                "postgres",
                "pg_restore",
                "-U",
                user,
                "-d",
                database,
                "--clean",
                "--if-exists",
            ),
            check=True,
            stdin=backup_input,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("backup", "restore"))
    parser.add_argument("path", type=Path)
    parser.add_argument("--database", default="trip_pilot")
    parser.add_argument("--user", default="trip_pilot")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--project-name")
    args = parser.parse_args()
    if args.operation == "backup":
        backup(args.path, args.database, args.user, args.env_file, args.project_name)
    else:
        restore(args.path, args.database, args.user, args.env_file, args.project_name)


if __name__ == "__main__":
    main()
