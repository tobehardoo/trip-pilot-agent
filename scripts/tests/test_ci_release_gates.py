from __future__ import annotations

import unittest
from pathlib import Path


class CiReleaseGatesTest(unittest.TestCase):
    def test_ci_runs_release_specific_regressions_and_benchmark(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("uv run python benchmarks/run_plan_evaluation.py", workflow)
        self.assertIn(
            "python -m unittest discover -s scripts/tests -p 'test_*.py' -v",
            workflow,
        )

    def test_python_coverage_gate_includes_guide_intelligence(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"
        ).read_text(encoding="utf-8")

        coverage_step = next(
            step
            for step in workflow.split("\n      - ")
            if "--cov=trip_agent.guide_intelligence" in step
        )
        for argument in (
            "--cov=trip_agent.retrieval",
            "--cov=trip_agent.acquisition",
            "--cov=trip_agent.guide_intelligence",
            "--cov-fail-under=80",
        ):
            self.assertIn(argument, coverage_step)

        self.assertNotIn(" tests/", coverage_step)
        self.assertEqual(workflow.count("uv run pytest"), 1)

    def test_compose_smoke_probes_both_web_and_api(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("http://127.0.0.1:8080/", workflow)
        self.assertIn("http://127.0.0.1:8080/api/health", workflow)
        self.assertIn("payload.get('status') == 'UP'", workflow)
        self.assertIn("payload.get('service') == 'travel-server'", workflow)

    def test_production_compose_allows_digest_pinned_images(self) -> None:
        repository_root = Path(__file__).resolve().parents[2]
        compose = (repository_root / "compose.prod.yaml").read_text(encoding="utf-8")
        workflow = (repository_root / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )

        for variable in (
            "POSTGRES_IMAGE",
            "REDIS_IMAGE",
            "RABBITMQ_IMAGE",
            "TRAVEL_SERVER_IMAGE",
            "AGENT_SERVICE_IMAGE",
            "WEB_IMAGE",
            "PROMETHEUS_IMAGE",
        ):
            self.assertIn(f"${{{variable}:-", compose, variable)

        self.assertIn("Validate immutable image overrides", workflow)
        self.assertIn(
            'digest_images="$(docker compose -f compose.prod.yaml config --images)"',
            workflow,
        )
        self.assertIn("grep -Ev '@sha256:[0-9a-f]{64}$'", workflow)

    def test_benchmark_idempotency_uuid_is_synthetic_and_precisely_allowlisted(
        self,
    ) -> None:
        repository_root = Path(__file__).resolve().parents[2]
        benchmark = (
            repository_root
            / "apps"
            / "agent-service"
            / "benchmarks"
            / "run_plan_evaluation.py"
        ).read_text(encoding="utf-8")
        gitleaks_ignore = (repository_root / ".gitleaksignore").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            '"idempotencyKey": "00000000-0000-4000-8000-000000000001"',
            benchmark,
        )
        self.assertIn(
            "56eee3cb7393c02874e3ffa47e346063069c51e4:"
            "apps/agent-service/benchmarks/run_plan_evaluation.py:"
            "generic-api-key:183",
            gitleaks_ignore,
        )


if __name__ == "__main__":
    unittest.main()
