from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    service_name: str = "cache-service"
    host: str = "0.0.0.0"
    port: int = 8004
    otel_exporter_otlp_endpoint: str = "http://otel-collector:4317"
    redis_url: str = "redis://redis:6379"

    class Config:
        env_prefix = ""


settings = Settings()
