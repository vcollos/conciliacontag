from pydantic import BaseSettings

class Settings(BaseSettings):
    SIMILARITY_THRESHOLD: float = 0.85
    CONTA_JUROS_MORA: str = "31426"
    CONTA_SEM_CORRESPONDENCIA: str = "10550"
    HISTORICO_JUROS: str = "20"
    HISTORICO_NORMAL: str = "104"
    MAX_FILE_SIZE: int = 50_000_000
    ALLOWED_ENCODINGS: list[str] = ['iso-8859-1', 'latin-1', 'cp1252', 'utf-8']

    class Config:
        env_file = ".env"

settings = Settings() 