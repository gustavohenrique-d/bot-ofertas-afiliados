"""Filtros de qualidade e ordenação das ofertas candidatas."""
import logging
import re
import unicodedata
from collections import Counter

from bot.fontes.base import Oferta

log = logging.getLogger(__name__)

# Fontes escolhidas à mão: passam na frente das automáticas
FONTES_MANUAIS = {"ml"}


def normalizar(texto: str) -> str:
    """Minúsculas e sem acentos, para comparar palavras."""
    sem_acento = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in sem_acento if not unicodedata.combining(c)).lower()


def encontrar_palavra(texto: str, palavras: list[str], inteira: bool) -> str | None:
    """Retorna a primeira palavra da lista presente no texto.

    inteira=True  -> "arma" não casa com "armário" (bloqueio)
    inteira=False -> "gato" casa com "gatos" (preferência)
    """
    alvo = normalizar(texto)
    for palavra in palavras:
        # Lookaround em vez de \b: funciona também com termos como "+18"
        padrao = r"(?<!\w)" + re.escape(normalizar(palavra)) + (r"(?!\w)" if inteira else "")
        if re.search(padrao, alvo):
            return palavra
    return None


def motivo_rejeicao(oferta: Oferta, filtros: dict) -> str | None:
    """Retorna o motivo para descartar a oferta, ou None se ela passa."""
    bloqueada = encontrar_palavra(oferta.titulo, filtros.get("palavras_bloqueadas", []), inteira=True)
    if bloqueada:
        return f"palavra bloqueada '{bloqueada}'"

    preco_min = filtros.get("preco_minimo")
    preco_max = filtros.get("preco_maximo")
    if preco_min is not None and oferta.preco < preco_min:
        return "preço abaixo do mínimo"
    if preco_max is not None and oferta.preco > preco_max:
        return "preço acima do máximo"

    desconto_min = filtros.get("desconto_minimo_pct") or 0
    if desconto_min:
        if oferta.desconto_pct is None:
            return "desconto não informado"
        if oferta.desconto_pct < desconto_min:
            return "desconto abaixo do mínimo"

    # Comissão só é conferida quando a fonte informa (hoje só a Shopee)
    comissao_min = filtros.get("comissao_minima_pct") or 0
    if comissao_min and oferta.comissao_pct is not None and oferta.comissao_pct < comissao_min:
        return "comissão abaixo do mínimo"

    # Avaliação e vendas: idem, só quando a fonte informa (hoje só a Shopee)
    avaliacao_min = filtros.get("avaliacao_minima") or 0
    if avaliacao_min and oferta.avaliacao is not None and oferta.avaliacao < avaliacao_min:
        return "avaliação abaixo do mínimo"
    vendas_min = filtros.get("vendas_minimas") or 0
    if vendas_min and oferta.vendas is not None and oferta.vendas < vendas_min:
        return "vendas abaixo do mínimo"

    return None


def eh_preferida(oferta: Oferta, filtros: dict) -> bool:
    return bool(encontrar_palavra(oferta.titulo, filtros.get("palavras_preferidas", []), inteira=False))


def motivo_variedade(oferta: Oferta, contagem: Counter, filtros: dict) -> str | None:
    """Variedade no horário: limite por palavra de busca e limite de preferidas (pet).

    `contagem` guarda o que já foi publicado no horário (ver contar_publicada).
    """
    limite_palavra = filtros.get("max_por_palavra_busca") or 0
    if limite_palavra and oferta.palavra_busca and contagem[("palavra", oferta.palavra_busca)] >= limite_palavra:
        return f"limite da palavra de busca '{oferta.palavra_busca}'"
    limite_preferidas = filtros.get("max_preferidas_por_horario") or 0
    if limite_preferidas and contagem["preferidas"] >= limite_preferidas and eh_preferida(oferta, filtros):
        return "limite de preferidas no horário"
    return None


def contar_publicada(oferta: Oferta, contagem: Counter, filtros: dict) -> None:
    if oferta.palavra_busca:
        contagem[("palavra", oferta.palavra_busca)] += 1
    if eh_preferida(oferta, filtros):
        contagem["preferidas"] += 1


def pontuacao(oferta: Oferta, filtros: dict) -> tuple:
    """Maior primeiro: fila manual (vence em 24h), palavra preferida (nicho pet) e maior desconto."""
    manual = oferta.fonte in FONTES_MANUAIS
    return (1 if manual else 0, 1 if eh_preferida(oferta, filtros) else 0, oferta.desconto_pct or 0)


def selecionar(ofertas: list[Oferta], filtros: dict, chaves_recentes: set[str]) -> list[Oferta]:
    """Remove duplicadas, repetidas nos últimos dias e reprovadas; ordena as restantes."""
    aprovadas, vistas = [], set()
    descartes = Counter()
    for oferta in ofertas:
        if oferta.chave in vistas:
            continue
        vistas.add(oferta.chave)
        if oferta.chave in chaves_recentes:
            descartes["publicada recentemente"] += 1
            continue
        motivo = motivo_rejeicao(oferta, filtros)
        if motivo:
            log.debug("Descartada %s: %s", oferta.chave, motivo)
            descartes[motivo] += 1
            continue
        aprovadas.append(oferta)

    if descartes:
        log.info("Descartes: %s", dict(descartes))
    return sorted(aprovadas, key=lambda o: pontuacao(o, filtros), reverse=True)
