# config/settings.py
import os
from pathlib import Path
from dotenv import load_dotenv
from cryptography.fernet import Fernet

# Carregar variáveis de ambiente a partir do .env
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# Pastas Padrão
DOWNLOADS_DIR = BASE_DIR / "downloads"
LOGS_DIR = BASE_DIR / "logs"

# Garantir existência física das pastas básicas
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

class CryptoHelper:
    """
    Classe auxiliar para criptografia simétrica de chaves e senhas.
    Armazena a chave secreta localmente em um arquivo oculto para evitar
    exposição de credenciais sensíveis no banco ou configurações.
    """
    KEY_FILE = BASE_DIR / ".key"

    @classmethod
    def _get_or_create_key(cls) -> bytes:
        if cls.KEY_FILE.exists():
            return cls.KEY_FILE.read_bytes()
        
        # Gerar nova chave
        key = Fernet.generate_key()
        cls.KEY_FILE.write_bytes(key)
        # Ocultar arquivo no Windows
        if os.name == 'nt':
            try:
                import ctypes
                ctypes.windll.kernel32.SetFileAttributesW(str(cls.KEY_FILE), 0x02) # FILE_ATTRIBUTE_HIDDEN
            except Exception:
                pass
        return key

    @classmethod
    def encrypt(cls, plain_text: str) -> str:
        if not plain_text:
            return ""
        key = cls._get_or_create_key()
        fernet = Fernet(key)
        return fernet.encrypt(plain_text.encode('utf-8')).decode('utf-8')

    @classmethod
    def decrypt(cls, encrypted_text: str) -> str:
        if not encrypted_text:
            return ""
        key = cls._get_or_create_key()
        fernet = Fernet(key)
        try:
            return fernet.decrypt(encrypted_text.encode('utf-8')).decode('utf-8')
        except Exception:
            return ""

# Parâmetros padrão de Banco de Dados
DEFAULT_DB_SERVER = os.getenv("DB_SERVER", "127.0.0.1")
DEFAULT_DB_DATABASE = os.getenv("DB_DATABASE", "")
DEFAULT_DB_USER = os.getenv("DB_USER", "sa")
DEFAULT_DB_PASSWORD = os.getenv("DB_PASSWORD", "Mrts@2025")
DEFAULT_DB_PORT = os.getenv("DB_PORT", "1433")
