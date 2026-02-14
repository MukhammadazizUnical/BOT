from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "send-bot-python"
    app_env: str = "development"
    port: int = 3010
    bot_role: str = "app"

    tg_bot_token: str = ""
    tg_api_id: int = 0
    tg_api_hash: str = ""
    tg_manual_video_id: str = ""
    tg_announce_sticker_id: str = ""

    database_url: str = "postgresql+asyncpg://postgres:1111@localhost:5432/tgbot"
    redis_url: str = "redis://localhost:6379/0"
    upstash_redis_rest_url: str = ""
    upstash_redis_rest_token: str = ""

    broadcast_concurrency: int = 8
    broadcast_job_attempts: int = 3
    broadcast_job_backoff_ms: int = 5000
    broadcast_user_lock_ttl_ms: int = 600000

    broadcast_per_account_concurrency: int = 1
    broadcast_attempts_per_job: int = 2
    broadcast_continuation_base_delay_ms: int = 1500
    broadcast_continuation_jitter_ms: int = 1500

    telegram_per_account_mpm: int = 6
    telegram_per_account_min_delay_ms: int = 3500
    telegram_global_mps: int = 125
    telegram_slowmode_default_seconds: int = 300

    broadcast_max_retries: int = 3
    broadcast_retry_base_ms: int = 2000
    broadcast_retry_max_ms: int = 120000
    broadcast_retry_jitter_ratio: float = 0.2

    broadcast_inflight_stuck_ms: int = 300000
    broadcast_retry_storm_threshold: int = 100
    broadcast_stuck_inflight_threshold: int = 100
    broadcast_queue_lag_alert_ms: int = 180000

    remote_groups_cache_ttl_ms: int = 60000
    remote_groups_min_refresh_ms: int = 180000
    remote_groups_failure_cooldown_ms: int = 120000

    scheduler_check_interval_ms: int = 5000
    scheduler_early_factor: float = 0.96
    scheduler_max_due_per_tick: int = 500
    scheduler_jitter_max_ms: int = 15000


settings = Settings()
