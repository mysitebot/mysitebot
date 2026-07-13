import os
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Dotenv load-order contract (leaf config): load a local .env if present so
# the OSS CLI works without exporting vars, but with override=False so
# already-exported vars (from the shell, tests, or a HOSTING app's config —
# api.core.config loads .env with override=True before importing this module)
# always take precedence over what this call would set.
load_dotenv(override=False)


class Settings(BaseModel):
    """Minimal settings the standalone agent needs. Deliberately carries NO
    production-secret validation — importing this never requires admin creds or
    a JWT secret, so the CLI runs on a Gemini key alone."""
    llm_api_key: str = Field(default_factory=lambda: os.environ.get("LLM_API_KEY", ""))
    llm_base_url: str = Field(default_factory=lambda: os.environ.get("LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"))
    llm_model: str = Field(default_factory=lambda: os.environ.get("LLM_MODEL", "gemini-2.5-flash-lite"))
    llm_model_thinking: str = Field(default_factory=lambda: os.environ.get("LLM_MODEL_THINKING", "gemini-2.5-flash"))
    llm_temperature: float = Field(default_factory=lambda: float(os.environ.get("LLM_TEMPERATURE", "0.3")))
    llm_max_output_tokens: int = Field(default_factory=lambda: int(os.environ.get("LLM_MAX_OUTPUT_TOKENS", "8192")))
    # Used by LocalGitProvider to build the preview URL. api sets this to its ACCOUNT_BASE_URL.
    preview_base_url: str = Field(default_factory=lambda: os.environ.get("PREVIEW_BASE_URL", os.environ.get("ACCOUNT_BASE_URL", "http://localhost:8000")))


settings = Settings()
