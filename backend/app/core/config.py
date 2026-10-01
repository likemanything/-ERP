from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置，全部可通过环境变量（前缀 ERP_）或 .env 文件覆盖。"""

    model_config = SettingsConfigDict(env_prefix="ERP_", env_file=".env", extra="ignore")

    app_name: str = "云帆ERP"
    env: str = "dev"  # dev / test / prod
    debug: bool = False

    database_url: str = "sqlite:///./erp.db"
    db_echo: bool = False

    secret_key: str = "change-me-in-production-please-use-a-long-random-string"
    # Fernet key（urlsafe base64 32 bytes），用于加密店铺授权凭证；为空则由 secret_key 派生
    encryption_key: str = ""
    access_token_expire_minutes: int = 60 * 12
    refresh_token_expire_days: int = 14

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"])

    # 是否允许公开注册新企业（SaaS 模式）
    allow_registration: bool = True

    # 新企业默认配置
    default_base_currency: str = "CNY"
    default_timezone: str = "Asia/Shanghai"

    # 后台同步任务
    worker_poll_seconds: int = 30

    # 静态前端目录（生产环境由后端托管构建后的前端）
    frontend_dist: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
