"""B14 acceptance harness db() helper must fail loudly, never silently.

A non-zero psql exit (wrong role, missing table, syntax error) used to
return an empty string — the scenario harness could mistake that for
"query returned no rows" and mark S079-style DB assertions green by
accident.  This suite locks in the fixed contract:

1. non-zero exit  -> redacted RuntimeError
2. zero exit      -> stdout rows
3. credentials    -> read from the container's own POSTGRES_USER/DB env
                      (via psql -U "$POSTGRES_USER"), never from the host
                      env file, never echoed as plaintext in the command.
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

_ACCEPTANCE_DIR = Path(__file__).resolve().parents[1] / "acceptance" / "b14"
sys.path.insert(0, str(_ACCEPTANCE_DIR))

import b14lib  # noqa: E402


class B14DbHelperTest(unittest.TestCase):
    """db() must raise on failure and use container-side credentials."""

    def _patch_psql(self, returncode: int, stdout: str, stderr: str = ""):
        result = subprocess.CompletedProcess(
            args=["docker"], returncode=returncode, stdout=stdout, stderr=stderr
        )
        return mock.patch.object(b14lib.subprocess, "run", return_value=result)

    def test_nonzero_psql_exit_raises_redacted_runtime_error(self) -> None:
        """A failing psql must never look like an empty result."""
        with (
            self._patch_psql(
                returncode=2,
                stdout="",
                stderr='psql: FATAL:  role "postgres" does not exist\n',
            ),
            self.assertRaises(RuntimeError) as ctx,
        ):
            b14lib.db("SELECT 1")
        message = str(ctx.exception)
        self.assertIn("psql failed", message)
        self.assertIn("role", message)
        self.assertNotIn("PGPASSWORD", message)
        self.assertNotIn("password", message.lower())

    def test_zero_exit_returns_rows(self) -> None:
        with self._patch_psql(returncode=0, stdout="PLANNING_COMPLETED\n"):
            self.assertEqual(b14lib.db("SELECT event_type FROM t"), "PLANNING_COMPLETED")

    def test_credentials_come_from_container_env_not_host(self) -> None:
        """The command must use $POSTGRES_USER/$POSTGRES_DB inside the
        container — no host-env-guessed user and no plaintext password."""
        captured: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            captured.append(cmd)
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="1\n", stderr=""
            )

        with mock.patch.object(b14lib.subprocess, "run", side_effect=fake_run):
            b14lib.db("SELECT 1")

        self.assertEqual(len(captured), 1)
        script = captured[0][5]  # the sh -c payload, not the container name
        self.assertIn("$POSTGRES_USER", script)
        self.assertIn("$POSTGRES_DB", script)
        self.assertIn("ON_ERROR_STOP=1", script)
        self.assertNotIn("PGPASSWORD", script)
        self.assertNotIn("postgres", script)  # no host-guessed role inside the psql call


if __name__ == "__main__":
    unittest.main()
