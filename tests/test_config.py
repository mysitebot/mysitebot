import importlib


def test_settings_reads_llm_env(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_TEMPERATURE", "0.7")
    import agent.config as config
    importlib.reload(config)
    assert config.settings.llm_api_key == "test-key"
    assert config.settings.llm_temperature == 0.7
    assert config.settings.llm_model  # has a default
    assert config.settings.llm_base_url  # has a default
    assert config.settings.preview_base_url  # has a default


def test_config_has_no_production_validator(monkeypatch):
    # Importing agent config must NOT require ADMIN_*/JWT_SECRET — the whole
    # point of the standalone agent. Clear them and assert import succeeds.
    for var in ("ADMIN_USERNAME", "ADMIN_PASSWORD", "JWT_SECRET"):
        monkeypatch.delenv(var, raising=False)
    import agent.config as config
    importlib.reload(config)
    assert config.settings is not None
