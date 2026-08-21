"""TDD for b14lib docker helper hardening.

Requirements:
- docker_checked() success returns stdout+stderr
- non-zero exit raises redacted RuntimeError (no password/token in message)
- TimeoutExpired is re-raised as RuntimeError with category and container
- wait_healthy_or_raise() success, timeout, and non-healthy handling
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


class DockerCheckedTest(unittest.TestCase):
    def _run(self, result):
        return mock.patch.object(b14lib.subprocess, "run", return_value=result)

    def test_success_returns_combined_output(self):
        result = subprocess.CompletedProcess(
            args=["docker", "ps"], returncode=0, stdout="ok", stderr=""
        )
        with self._run(result):
            out = b14lib.docker_checked(
                ["docker", "ps"], category="docker ps", container="my-container", timeout=30
            )
        self.assertEqual(out, "ok")

    def test_non_zero_raises_redacted_runtime_error(self):
        result = subprocess.CompletedProcess(
            args=["docker", "stop", "c"], returncode=1, stdout="", stderr="error details"
        )
        with self._run(result), self.assertRaises(RuntimeError) as ctx:
                b14lib.docker_checked(
                    ["docker", "stop", "c"],
                    category="docker stop",
                    container="trip-pilot-b14-acceptance-rabbitmq-1",
                )
        msg = str(ctx.exception)
        self.assertIn("docker stop", msg)
        self.assertIn("container=trip-pilot-b14-acceptance-rabbitmq-1", msg)
        self.assertIn("exit=1", msg)
        self.assertNotIn("PGPASSWORD", msg)
        self.assertNotIn("RABBITMQ_PASSWORD", msg)

    def test_timeout_reraised_with_category_and_container(self):
        def raise_timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout", 0))

        with (
            mock.patch.object(b14lib.subprocess, "run", side_effect=raise_timeout),
            self.assertRaises(RuntimeError) as ctx,
        ):
            b14lib.docker_checked(
                ["docker", "exec", "c", "sleep", "10"],
                category="docker exec",
                container="my-container",
                timeout=5,
            )
        msg = str(ctx.exception)
        self.assertIn("docker exec", msg)
        self.assertIn("container=my-container", msg)
        self.assertIn("timed out", msg.lower())

    def test_wait_healthy_or_raise_success(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if len(calls) == 1:
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0, stdout="starting\n", stderr=""
                )
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="healthy\n", stderr=""
            )

        with (
            mock.patch.object(b14lib.subprocess, "run", side_effect=fake_run),
            mock.patch("time.sleep", return_value=None),
        ):
            b14lib.wait_healthy_or_raise("my-container", timeout=10)
        self.assertEqual(len(calls), 2)

    def test_wait_healthy_or_raise_timeout_raises(self):
        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="starting\n", stderr=""
            )

        with (
            mock.patch.object(b14lib.subprocess, "run", side_effect=fake_run),
            mock.patch("time.sleep", return_value=None),
            self.assertRaises(RuntimeError) as ctx,
        ):
            b14lib.wait_healthy_or_raise(
                "trip-pilot-b14-acceptance-agent-service-1", timeout=1
            )
        msg = str(ctx.exception)
        self.assertIn("trip-pilot-b14-acceptance-agent-service-1", msg)
        self.assertIn("not healthy", msg.lower())

    def test_secret_value_redacted_from_stderr_snippet(self):
        """Q2: a secret VALUE inside stderr must be scrubbed from the error,
        even though the label stays for debuggability.  This used to be a fake
        green via ``msg.replace("mySecret", "")`` which masked the leak."""
        result = subprocess.CompletedProcess(
            args=["docker", "exec", "c", "psql"],
            returncode=1,
            stdout="",
            stderr='FATAL: password mySecret123 authentication failed',
        )
        with (
            self._run(result),
            self.assertRaises(RuntimeError) as ctx,
        ):
            b14lib.docker_checked(
                ["docker", "exec", "c", "psql"],
                category="psql",
                container="postgres",
            )
        msg = str(ctx.exception)
        self.assertNotIn("mySecret123", msg, "secret value must not leak via stderr")
        self.assertIn("password", msg, "the label may stay for debuggability")

    def test_secret_value_redacted_for_token_and_key_labels(self):
        self.assertEqual(
            b14lib._redact_secrets("token abc123 used"),
            "token <redacted> used",
        )
        self.assertEqual(
            b14lib._redact_secrets("api_key=my-key-42 ok"),
            "api_key <redacted> ok",
        )
        self.assertNotIn("my-key-42", b14lib._redact_secrets("api_key=my-key-42"))

    def test_docker_legacy_still_exists(self):
        self.assertTrue(hasattr(b14lib, "docker"))
        self.assertTrue(hasattr(b14lib, "wait_healthy"))


if __name__ == "__main__":
    unittest.main()
