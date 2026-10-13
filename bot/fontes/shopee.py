"""Fonte Shopee: Shopee Affiliate Open API (GraphQL).

Autenticação (header Authorization):
    SHA256 Credential={AppID}, Timestamp={unix em segundos}, Signature={assinatura}
    assinatura = sha256(AppID + Timestamp + corpo_json + Secret) em hexadecimal
O corpo assinado precisa ser exatamente o mesmo enviado na requisição.

ATENÇÃO: nomes e formatos dos campos conferidos em fontes públicas; valide com a
documentação do painel de afiliados assim que as chaves forem aprovadas.
"""
import hashlib
import json
import logging
import random
import time

import requests

from bot.fontes.base import ErroFonte, Fonte, FonteIndisponivel, Oferta

log = logging.getLogger(__name__)

URL_API = "https://open-api.affiliate.shopee.com.br/graphql"
CAMPOS = ("itemId productName productLink offerLink imageUrl shopName "
          "priceMin priceMax priceDiscountRate commissionRate ratingStar sales")


def montar_autorizacao(app_id: str, segredo: str, corpo: str, timestamp: int) -> str:
    assinatura = hashlib.sha256(f"{app_id}{timestamp}{corpo}{segredo}".encode("utf-8")).hexdigest()
    return f"SHA256 Credential={app_id}, Timestamp={timestamp}, Signature={assinatura}"


def _numero(valor) -> float | None:
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def no_para_oferta(no: dict) -> Oferta | None:
    """Converte um item da API em Oferta. Só usa dados vindos da API."""
    item_id = no.get("itemId")
    titulo = (no.get("productName") or "").strip()
    preco = _numero(no.get("priceMin"))
    link = no.get("offerLink") or ""
    if not item_id or not titulo or not preco or not link:
        return None
    comissao = _numero(no.get("commissionRate"))  # fração: "0.07" = 7%
    vendas = _numero(no.get("sales"))
    return Oferta(
        fonte="shopee",
        id_produto=str(item_id),
        titulo=titulo,
        preco=preco,
        link_afiliado=link,
        preco_original=None,  # a API não traz o preço "de"; não estimamos
        desconto_pct=_numero(no.get("priceDiscountRate")),  # já em %: 30 = 30%
        comissao_pct=round(comissao * 100, 2) if comissao is not None else None,
        imagem_url=no.get("imageUrl") or None,
        loja=no.get("shopName") or None,
        url_produto=no.get("productLink") or None,
        avaliacao=_numero(no.get("ratingStar")),  # texto: "4.9"
        vendas=int(vendas) if vendas is not None else None,
        # A API de ofertas não tem campo de cupom: nunca publicamos cupom da Shopee
    )


class FonteShopee(Fonte):
    nome = "shopee"

    def __init__(self, app_id: str, segredo: str, config: dict, sessao=None, timeout: int = 20):
        if not app_id or not segredo:
            raise FonteIndisponivel("SHOPEE_APP_ID/SHOPEE_APP_SECRET ainda não configurados")
        self.app_id = app_id
        self.segredo = segredo
        self.palavras = list(config.get("palavras_busca") or ["pet"])
        self.ordenacao = int(config.get("ordenacao", 2))
        self.limite_por_busca = int(config.get("limite_por_busca", 20))
        self.sub_ids = list(config.get("sub_ids") or [])
        self.sessao = sessao or requests.Session()
        self.timeout = timeout

    def _consultar(self, query: str) -> dict:
        corpo = json.dumps({"query": query}, separators=(",", ":"))
        timestamp = int(time.time())
        cabecalhos = {
            "Content-Type": "application/json",
            "Authorization": montar_autorizacao(self.app_id, self.segredo, corpo, timestamp),
        }
        try:
            resposta = self.sessao.post(URL_API, data=corpo.encode("utf-8"),
                                        headers=cabecalhos, timeout=self.timeout)
        except requests.RequestException as e:
            raise ErroFonte(f"Shopee: falha de rede ({type(e).__name__})") from e
        if resposta.status_code != 200:
            raise ErroFonte(f"Shopee: HTTP {resposta.status_code}")
        try:
            dados = resposta.json()
        except ValueError as e:
            raise ErroFonte("Shopee: resposta não é JSON") from e
        if dados.get("errors"):
            raise ErroFonte(f"Shopee: {dados['errors'][0].get('message', 'erro desconhecido')}")
        return dados.get("data") or {}

    def _ofertas_da_consulta(self, argumentos: str) -> list[Oferta]:
        query = f"{{productOfferV2({argumentos}) {{ nodes {{ {CAMPOS} }} }} }}"
        nos = (self._consultar(query).get("productOfferV2") or {}).get("nodes") or []
        return [o for o in map(no_para_oferta, nos) if o]

    def buscar(self, quantidade: int) -> list[Oferta]:
        """Busca TODAS as palavras: a variedade por palavra e o nicho pet dependem disso."""
        palavras = self.palavras[:]
        random.shuffle(palavras)  # desempate entre ofertas iguais varia entre os horários
        ofertas, ultimo_erro = [], None
        for palavra in palavras:
            argumentos = (f"keyword: {json.dumps(palavra)}, sortType: {self.ordenacao}, "
                          f"page: 1, limit: {self.limite_por_busca}")
            try:
                achadas = self._ofertas_da_consulta(argumentos)
            except ErroFonte as e:
                log.warning("Busca '%s' na Shopee falhou: %s", palavra, e)
                ultimo_erro = e
                continue
            for oferta in achadas:
                oferta.palavra_busca = palavra
            ofertas.extend(achadas)
        if not ofertas and ultimo_erro:
            raise ultimo_erro
        return ofertas

    def revalidar(self, oferta: Oferta) -> Oferta | None:
        """Consulta o item de novo: pula se sumiu ou se o preço piorou."""
        atuais = self._ofertas_da_consulta(f"itemId: {int(oferta.id_produto)}, page: 1, limit: 1")
        if not atuais:
            log.info("Shopee %s: oferta sumiu, pulando", oferta.id_produto)
            return None
        atual = atuais[0]
        if atual.preco > oferta.preco + 0.005:
            log.info("Shopee %s: preço piorou (%.2f -> %.2f), pulando",
                     oferta.id_produto, oferta.preco, atual.preco)
            return None
        atual.palavra_busca = oferta.palavra_busca
        atual.link_afiliado = self._link_curto(atual)
        return atual

    def _link_curto(self, oferta: Oferta) -> str:
        """Gera o link curto de afiliado; se falhar, usa o offerLink da API."""
        origem = oferta.url_produto or oferta.link_afiliado
        query = (f"mutation {{ generateShortLink(input: {{originUrl: {json.dumps(origem)}, "
                 f"subIds: {json.dumps(self.sub_ids)}}}) {{ shortLink }} }}")
        try:
            link = (self._consultar(query).get("generateShortLink") or {}).get("shortLink")
        except ErroFonte as e:
            log.warning("Link curto da Shopee falhou (%s); usando offerLink", e)
            link = None
        return link or oferta.link_afiliado
