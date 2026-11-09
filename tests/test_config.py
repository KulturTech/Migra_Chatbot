from interviewbot.config import Settings


def test_settings_from_env_defaults_to_local_llama_31(monkeypatch):
    for key in ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL", "LLM_TIMEOUT_SECONDS"):
        monkeypatch.delenv(key, raising=False)
    settings = Settings.from_env(dotenv=None)

    assert settings.llm_provider == "openai_compat"
    assert settings.llm_base_url == "http://localhost:11434/v1/"
    assert settings.llm_api_key == "ollama"
    assert settings.llm_model == "llama3.1:8b"
    assert settings.llm_timeout_seconds == 180.0
