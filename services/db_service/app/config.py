from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    service_name: str = "db-service"
    host: str = "0.0.0.0"
    port: int = 8003
    otel_exporter_otlp_endpoint: str = "http://otel-collector:4317"
    db_path: str = "/app/data/hades.db"

    class Config:
        env_prefix = ""


settings = Settings()
