from interviewbot.config import Settings


def test_settings_default_to_local_llama_31():
    settings = Settings()

    assert settings.llm_provider == "openai_compat"
    assert settings.llm_base_url == "http://localhost:11434/v1/"
    assert settings.llm_api_key == "ollama"
    assert settings.llm_model == "llama3.1:8b"
