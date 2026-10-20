from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """
    Configurações da aplicação, carregadas do .env (ou variáveis de ambiente
    reais, quando rodando em container/produção).
    """

    shared_dir: str = "/app/data"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    public_base_url: str = "http://localhost:8000"

    max_upload_bytes: int = Field(default=10 * 1024 * 1024, gt=0)
    max_request_bytes: int = Field(default=11 * 1024 * 1024, gt=0)
    max_report_bytes: int = Field(default=10 * 1024 * 1024, gt=0)
    report_max_cells: int = Field(default=50_000, gt=0)
    zip_max_entries: int = Field(default=200, gt=0)
    zip_max_uncompressed_bytes: int = Field(default=32 * 1024 * 1024, gt=0)
    zip_max_ratio: int = Field(default=200, gt=0)
    monitor_max_log_bytes: int = Field(default=8 * 1024 * 1024, gt=0)
    monitor_max_records: int = Field(default=50_000, gt=0)
    monitor_processing_seconds: float = Field(default=15, gt=0)
    monitor_max_concurrent: int = Field(default=2, gt=0)
    db_connect_timeout_seconds: int = Field(default=15, gt=0)
    db_query_timeout_seconds: int = Field(default=60, gt=0)
    db_max_rows: int = Field(default=10_000, gt=0)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
