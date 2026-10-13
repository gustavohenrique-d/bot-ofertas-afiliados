"""Publicadores: cada um envia a oferta para um destino (Telegram, WhatsApp...)."""
from typing import Protocol

from bot.fontes.base import Oferta


class PublicadorIndisponivel(Exception):
    """O destino caiu (ex.: WhatsApp desconectado): pular no resto do horário."""


class Publicador(Protocol):
    nome: str

    def publicar(self, oferta: Oferta) -> None:
        """Envia a oferta. Levanta exceção se falhar."""

    def pausa(self) -> float:
        """Segundos a esperar antes do próximo post."""
