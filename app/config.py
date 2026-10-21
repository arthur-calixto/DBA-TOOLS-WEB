from cryptography.fernet import Fernet
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Configurações da aplicação, carregadas do .env (ou variáveis de ambiente
    reais, quando rodando em container/produção).
    """

    shared_dir: str = "/app/data"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    # Quando vazio, a proteção CSRF valida a origem contra o Host da própria
    # requisição, permitindo homologação em endereços internos sem hardcode.
    public_base_url: str = ""

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

    # Opcional nesta etapa: sem DATABASE_URL a aplicação continua usando os
    # cadastros JSON compartilhados existentes.
    database_url: str | None = None
    db_pool_size: int = Field(default=5, gt=0)
    db_max_overflow: int = Field(default=5, ge=0)
    db_pool_timeout_seconds: int = Field(default=30, gt=0)
    db_pool_recycle_seconds: int = Field(default=1800, gt=0)

    auth_enabled: bool = False
    auth_session_key: str | None = None
    auth_cookie_name: str = "dba_tools_session"
    auth_cookie_max_age_seconds: int = Field(default=30 * 24 * 3600, gt=0)
    auth_cookie_renew_threshold_seconds: int = Field(default=7 * 24 * 3600, gt=0)
    auth_cookie_secure: bool = False
    auth_cookie_samesite: str = "lax"
    csrf_enabled: bool = True

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def validate_auth_configuration(self):
        if self.auth_enabled:
            if not self.database_url:
                raise ValueError("DATABASE_URL é obrigatória quando AUTH_ENABLED está ativo")
            if not self.auth_session_key:
                raise ValueError("AUTH_SESSION_KEY é obrigatória quando AUTH_ENABLED está ativo")
            try:
                Fernet(self.auth_session_key.encode("ascii"))
            except Exception as exc:
                raise ValueError("AUTH_SESSION_KEY inválida") from exc
        if self.auth_cookie_samesite not in {"lax", "strict", "none"}:
            raise ValueError("AUTH_COOKIE_SAMESITE inválido")
        if self.auth_cookie_samesite == "none" and not self.auth_cookie_secure:
            raise ValueError("AUTH_COOKIE_SECURE é obrigatório com SameSite=None")
        return self


settings = Settings()
