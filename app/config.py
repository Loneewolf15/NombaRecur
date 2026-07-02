from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_env: str = "sandbox"
    app_secret_key: str
    database_url: str = "sqlite:///./nombarecur.db"

    # Nomba credentials
    nomba_account_id: str
    nomba_client_id: str
    nomba_client_secret: str
    nomba_webhook_secret: str = "NombaHackathon2026"

    # Nomba API URLs
    nomba_base_url: str = "https://sandbox.nomba.com"
    nomba_auth_url: str = "https://sandbox.nomba.com/v1/auth/token/issue"

    # Encryption
    fernet_key: str

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
