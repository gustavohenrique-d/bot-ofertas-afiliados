"""Fonte Amazon: só a interface. A API é liberada depois das 3 primeiras vendas."""
from bot.fontes.base import Fonte, FonteIndisponivel, Oferta


class FonteAmazon(Fonte):
    nome = "amazon"

    def __init__(self, *args, **kwargs):
        raise FonteIndisponivel("fonte Amazon ainda não implementada")

    def buscar(self, quantidade: int) -> list[Oferta]:
        raise NotImplementedError

    def revalidar(self, oferta: Oferta) -> Oferta | None:
        raise NotImplementedError
