from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    service_name: str = "gateway"
    host: str = "0.0.0.0"
    port: int = 8000
    auth_service_url: str = "http://auth:8001"
    ai_service_url: str = "http://ai-service:8002"
    otel_exporter_otlp_endpoint: str = "http://otel-collector:4317"

    class Config:
        env_prefix = ""


settings = Settings()
