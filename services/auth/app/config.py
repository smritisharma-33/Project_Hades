from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    service_name: str = "auth"
    host: str = "0.0.0.0"
    port: int = 8001
    otel_exporter_otlp_endpoint: str = "http://otel-collector:4317"

    # Demo credentials
    valid_api_keys: str = "hades-key-001,hades-key-002,hades-key-003"
    valid_tokens: str = "hades-token-001,hades-token-002,hades-token-003"

    class Config:
        env_prefix = ""


settings = Settings()
