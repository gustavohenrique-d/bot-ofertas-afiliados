"""Fonte Mercado Livre: lê a fila manual (CSV). Nada de scraping.

Colunas: link_afiliado,titulo,preco,preco_original,imagem_url,cupom,cupom_oficial
O CSV nunca é alterado pelo bot: "vista" e "publicada" ficam no SQLite.
"""
import csv
import logging
from datetime import timedelta
from pathlib import Path

from bot.banco import agora_utc
from bot.filtros import normalizar
from bot.fontes.base import Fonte, Oferta

log = logging.getLogger(__name__)

VALORES_SIM = {"sim", "s", "yes", "y", "true", "1", "x"}


def ler_preco(texto: str | None) -> float | None:
    """Aceita "129.90", "129,90" e "R$ 1.299,90"."""
    limpo = (texto or "").replace("R$", "").replace(" ", "").strip()
    if not limpo:
        return None
    if "," in limpo:  # formato brasileiro
        limpo = limpo.replace(".", "").replace(",", ".")
    try:
        valor = float(limpo)
    except ValueError:
        return None
    return valor if valor > 0 else None


def linha_para_oferta(linha: dict) -> Oferta | None:
    """Converte uma linha do CSV em Oferta. None se faltar dado obrigatório."""
    link = (linha.get("link_afiliado") or "").strip()
    titulo = (linha.get("titulo") or "").strip()
    preco = ler_preco(linha.get("preco"))
    if not link.startswith("http") or not titulo or preco is None:
        return None
    return Oferta(
        fonte="ml",
        id_produto=link,
        titulo=titulo,
        preco=preco,
        link_afiliado=link,
        preco_original=ler_preco(linha.get("preco_original")),
        imagem_url=(linha.get("imagem_url") or "").strip() or None,
        cupom=(linha.get("cupom") or "").strip() or None,
        cupom_oficial=normalizar((linha.get("cupom_oficial") or "").strip()) in VALORES_SIM,
    )


def ler_linhas(arquivo: Path) -> list[dict]:
    """Lê o CSV aceitando vírgula ou ponto e vírgula (Excel em português)."""
    with open(arquivo, encoding="utf-8-sig", newline="") as f:
        conteudo = f.read()
    if not conteudo.strip():
        return []
    cabecalho = conteudo.splitlines()[0]
    separador = ";" if cabecalho.count(";") > cabecalho.count(",") else ","
    leitor = csv.DictReader(conteudo.splitlines(), delimiter=separador)
    return [{(k or "").strip().lower(): v for k, v in linha.items()} for linha in leitor]


class FonteMercadoLivre(Fonte):
    nome = "ml"

    def __init__(self, arquivo: Path, banco, validade_horas: float = 24):
        self.arquivo = arquivo
        self.banco = banco
        self.validade = timedelta(hours=validade_horas)
        self._vistas = {}

    def buscar(self, quantidade: int) -> list[Oferta]:
        if not self.arquivo.exists():
            log.warning("Fila do Mercado Livre não encontrada: %s", self.arquivo.name)
            return []
        agora = agora_utc()
        ofertas, expiradas = [], 0
        for numero, linha in enumerate(ler_linhas(self.arquivo), start=2):
            oferta = linha_para_oferta(linha)
            if oferta is None:
                log.warning("Fila ML, linha %d ignorada: falta link, título ou preço válido", numero)
                continue
            vista, publicada = self.banco.situacao_fila(self.nome, oferta.id_produto)
            if publicada:
                continue
            vista = vista or self.banco.registrar_vista(self.nome, oferta.id_produto)
            if agora - vista > self.validade:
                expiradas += 1
                continue
            self._vistas[oferta.id_produto] = vista
            ofertas.append(oferta)
        if expiradas:
            log.info("Fila ML: %d oferta(s) com mais de %s sem publicar foram ignoradas",
                     expiradas, self.validade)
        return ofertas

    def revalidar(self, oferta: Oferta) -> Oferta | None:
        """Sem API para conferir preço: só garante que não passou da validade."""
        vista = self._vistas.get(oferta.id_produto)
        if vista and agora_utc() - vista > self.validade:
            return None
        return oferta
