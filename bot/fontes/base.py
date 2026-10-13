"""Modelo comum de oferta e interface que toda fonte deve seguir."""
from abc import ABC, abstractmethod
from dataclasses import dataclass


class FonteIndisponivel(Exception):
    """A fonte não pode ser usada agora (ex.: chaves ainda não configuradas)."""


class ErroFonte(Exception):
    """Falha ao consultar a fonte (rede, API, resposta inválida)."""


@dataclass
class Oferta:
    fonte: str                          # "mock", "shopee" ou "ml"
    id_produto: str                     # id único dentro da fonte
    titulo: str
    preco: float                        # preço atual ("por")
    link_afiliado: str
    preco_original: float | None = None  # preço "de" (só se a fonte informar)
    desconto_pct: float | None = None
    comissao_pct: float | None = None
    imagem_url: str | None = None
    loja: str | None = None
    cupom: str | None = None
    cupom_oficial: bool = False
    url_produto: str | None = None      # link original do produto (sem afiliado)
    avaliacao: float | None = None      # nota do produto, 0 a 5 (só se a fonte informar)
    vendas: int | None = None           # total de vendas (só se a fonte informar)
    palavra_busca: str | None = None    # palavra que achou a oferta (variedade por horário)

    def __post_init__(self):
        # Calcula o desconto a partir do "de/por" quando a fonte não informa
        if self.desconto_pct is None and self.tem_preco_original:
            self.desconto_pct = round((1 - self.preco / self.preco_original) * 100, 1)

    @property
    def chave(self) -> str:
        """Identificador usado no histórico (evita repetir produto)."""
        return f"{self.fonte}:{self.id_produto}"

    @property
    def tem_preco_original(self) -> bool:
        return bool(self.preco_original) and self.preco_original > self.preco

    @property
    def cupom_publicavel(self) -> str | None:
        """Cupom só sai no post se for oficial."""
        if self.cupom and self.cupom_oficial:
            return self.cupom.strip()
        return None


class Fonte(ABC):
    """Interface de uma fonte de ofertas."""

    nome: str = ""

    @abstractmethod
    def buscar(self, quantidade: int) -> list[Oferta]:
        """Retorna candidatas (sugestão: pelo menos `quantidade`)."""

    @abstractmethod
    def revalidar(self, oferta: Oferta) -> Oferta | None:
        """Confere a oferta logo antes de publicar. None = pular."""
