"""Leitura do .env (chaves) e do config.json (regras do bot)."""
import json
import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

# Caminhos sempre relativos à raiz do projeto (funciona no Windows e no Linux)
RAIZ = Path(__file__).resolve().parent.parent
PASTA_DADOS = RAIZ / "dados"
PASTA_LOGS = RAIZ / "logs"
ARQUIVO_ENV = RAIZ / ".env"
ARQUIVO_CONFIG = RAIZ / "config" / "config.json"
ARQUIVO_CONFIG_EXEMPLO = RAIZ / "config" / "config.example.json"
ARQUIVO_BANCO = PASTA_DADOS / "bot.db"
ARQUIVO_FILA_ML = PASTA_DADOS / "fila_mercadolivre.csv"
URL_PONTE_PADRAO = "http://localhost:3000"  # ponte de WhatsApp do Hermes Agent


class ErroConfig(Exception):
    """Configuração ausente ou inválida."""


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    telegram_channel_id: str
    telegram_admin_chat_id: str
    shopee_app_id: str
    shopee_app_secret: str
    config: dict
    whatsapp_group_id: str = ""
    whatsapp_admin_id: str = ""
    whatsapp_bridge_url: str = URL_PONTE_PADRAO
    publicadores_env: str = ""  # PUBLICADORES_ATIVOS do .env (vazio = usa o config.json)

    @property
    def fuso(self) -> ZoneInfo:
        return ZoneInfo(self.config.get("fuso", "America/Sao_Paulo"))

    @property
    def publicadores_ativos(self) -> list[str]:
        """PUBLICADORES_ATIVOS do .env, se definido, substitui o do config.json."""
        if self.publicadores_env:
            return [nome.strip().lower() for nome in self.publicadores_env.split(",") if nome.strip()]
        return list(self.config.get("publicadores_ativos", ["telegram"]))


def _env(nome: str) -> str:
    return os.getenv(nome, "").strip()


def carregar(arquivo_env: Path = ARQUIVO_ENV, arquivo_config: Path = ARQUIVO_CONFIG) -> Settings:
    """Carrega .env e config.json. O .env é opcional (ex.: --dry-run com mock)."""
    load_dotenv(arquivo_env)
    if not arquivo_config.exists():
        # O config.json não vai para o git: cada instalação cria o seu a partir do exemplo
        raise ErroConfig(f"Arquivo config/{arquivo_config.name} não encontrado. Copie config/config.example.json "
                         f"para config/config.json e ajuste as palavras de busca e os filtros.")
    try:
        with open(arquivo_config, encoding="utf-8") as f:
            config = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise ErroConfig(f"Não consegui ler {arquivo_config.name}: {e}") from e

    return Settings(
        telegram_bot_token=_env("TELEGRAM_BOT_TOKEN"),
        telegram_channel_id=_env("TELEGRAM_CHANNEL_ID"),
        telegram_admin_chat_id=_env("TELEGRAM_ADMIN_CHAT_ID"),
        shopee_app_id=_env("SHOPEE_APP_ID"),
        shopee_app_secret=_env("SHOPEE_APP_SECRET"),
        config=config,
        whatsapp_group_id=_env("WHATSAPP_GROUP_ID"),
        whatsapp_admin_id=_env("WHATSAPP_ADMIN_ID"),
        whatsapp_bridge_url=_env("WHATSAPP_BRIDGE_URL") or URL_PONTE_PADRAO,
        publicadores_env=_env("PUBLICADORES_ATIVOS"),
    )


def exigir(valor: str, nome: str) -> str:
    """Garante que a variável do .env existe (sem nunca mostrar o valor)."""
    if not valor:
        raise ErroConfig(f"A variável {nome} não está definida no .env")
    return valor


def exigir_id_whatsapp(valor: str, nome: str, sufixo: str) -> str:
    """Confere o formato do ID do WhatsApp (grupo @g.us, pessoa @s.whatsapp.net)."""
    exigir(valor, nome)
    if not valor.endswith(sufixo):
        raise ErroConfig(f"A variável {nome} deve terminar em {sufixo}")
    return valor
