"""BYOK provider-credential resolution (env default, user config wins)."""

from __future__ import annotations

from types import SimpleNamespace

from trip_agent.providers.credentials import (
    AMAP,
    KNOWLEDGE,
    WEATHER,
    ProviderCredentials,
    command_credential_overrides,
    env_credentials,
    merge_credentials,
    resolve_user_credentials,
)


class _FakeStore:
    def __init__(self, rows: dict[str, str]):
        self._rows = rows
        self.calls: list[str] = []

    def fetch(self, owner_id: str) -> tuple[tuple[str, str], ...]:
        self.calls.append(owner_id)
        return tuple((p, k) for p, k in self._rows.items() if k)


def _stub_settings(**kwargs) -> SimpleNamespace:
    base = dict(
        amap_web_service_key=SimpleNamespace(get_secret_value=lambda: "env-amap"),
        dashscope_api_key=SimpleNamespace(get_secret_value=lambda: "env-dashscope"),
        dashscope_embedding_base_url="https://env.example/v1",
        knowledge_embedding_model="env-model",
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


class TestEnvCredentials:
    def test_defaults_pulled_from_settings_and_environment(self, monkeypatch):
        monkeypatch.setenv("QWEATHER_API_KEY", "env-qweather")
        settings = _stub_settings()
        creds = env_credentials(settings)  # type: ignore[arg-type]
        assert creds.amap_key == "env-amap"
        assert creds.dashscope_key == "env-dashscope"
        assert creds.dashscope_base_url == "https://env.example/v1"
        assert creds.dashscope_model == "env-model"
        assert creds.qweather_key == "env-qweather"

    def test_missing_env_keys_become_none(self, monkeypatch):
        monkeypatch.delenv("QWEATHER_API_KEY", raising=False)
        settings = _stub_settings(
            amap_web_service_key=None, dashscope_api_key=None, dashscope_embedding_base_url=""
        )
        creds = env_credentials(settings)  # type: ignore[arg-type]
        assert creds.amap_key is None
        assert creds.dashscope_key is None
        assert creds.qweather_key is None


class TestMergeCredentials:
    def test_user_wins_over_environment(self):
        env = ProviderCredentials(amap_key="env", dashscope_key="env-dash", dashscope_model="env-m")
        user = ProviderCredentials(amap_key="user")
        merged = merge_credentials(env, user)
        assert merged.amap_key == "user"
        # absent user value falls back to env
        assert merged.dashscope_key == "env-dash"
        assert merged.dashscope_model == "env-m"

    def test_empty_user_keeps_env_unchanged(self):
        env = ProviderCredentials(amap_key="env")
        assert merge_credentials(env, ProviderCredentials()).amap_key == "env"


class TestCommandCredentialOverrides:
    def test_empty_command_returns_empty(self):
        command = SimpleNamespace(payload=SimpleNamespace(credential_overrides=None))
        creds = command_credential_overrides(command)
        assert creds.has_user_overrides() is False

    def test_amap_and_knowledge_overrides_mapped(self):
        command = SimpleNamespace(
            payload=SimpleNamespace(
                credential_overrides={
                    AMAP: SimpleNamespace(api_key="amap-k", api_base_url=None, model=None),
                    KNOWLEDGE: SimpleNamespace(
                        api_key="dash-k", api_base_url="https://u.example/v1", model="m1"
                    ),
                }
            )
        )
        creds = command_credential_overrides(command)
        assert creds.amap_key == "amap-k"
        assert creds.dashscope_key == "dash-k"
        assert creds.dashscope_base_url == "https://u.example/v1"
        assert creds.dashscope_model == "m1"
        assert creds.has_user_overrides() is True

    def test_blank_api_key_is_ignored(self):
        command = SimpleNamespace(
            payload=SimpleNamespace(
                credential_overrides={
                    WEATHER: SimpleNamespace(api_key="  ", api_base_url=None, model=None)
                }
            )
        )
        creds = command_credential_overrides(command)
        assert creds.qweather_key is None
        assert creds.has_user_overrides() is False


class TestResolveUserCredentials:
    def test_no_owner_returns_env_unchanged(self):
        env = ProviderCredentials(amap_key="env")
        out = resolve_user_credentials("postgresql://x", None, env=env, store=_FakeStore({}))
        assert out == env

    def test_user_amap_and_knowledge_applied(self):
        env = ProviderCredentials(amap_key="env", dashscope_key="env-dash")
        store = _FakeStore({AMAP: "user-amap", KNOWLEDGE: "user-dash", WEATHER: "user-w"})
        out = resolve_user_credentials("postgresql://x", "user-1", env=env, store=store)
        assert out.amap_key == "user-amap"
        assert out.dashscope_key == "user-dash"
        assert out.qweather_key == "user-w"
        assert store.calls == ["user-1"]

    def test_unknown_provider_row_is_ignored(self):
        env = ProviderCredentials(amap_key="env")
        store = _FakeStore({"NOPE": "x"})
        out = resolve_user_credentials("postgresql://x", "u", env=env, store=store)
        assert out.amap_key == "env"