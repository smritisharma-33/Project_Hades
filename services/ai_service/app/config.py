from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    service_name: str = "ai-service"
    host: str = "0.0.0.0"
    port: int = 8002
    otel_exporter_otlp_endpoint: str = "http://otel-collector:4317"
    db_service_url: str = "http://db-service:8003"
    cache_service_url: str = "http://cache-service:8004"
    inference_min_latency_ms: int = 50
    inference_max_latency_ms: int = 150

    class Config:
        env_prefix = ""


settings = Settings()
