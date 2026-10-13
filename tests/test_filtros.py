import json
import logging
from collections import Counter

import pytest
import requests

import main
from bot.filtros import contar_publicada, motivo_rejeicao, motivo_variedade, selecionar
from bot.fontes.base import Oferta
from bot.fontes.shopee import FonteShopee, no_para_oferta
from config.settings import ARQUIVO_CONFIG_EXEMPLO, ErroConfig, Settings, carregar

FILTROS = {
    "desconto_minimo_pct": 20,
    "comissao_minima_pct": 5,
    "preco_minimo": 10,
    "preco_maximo": 500,
    "palavras_bloqueadas": ["arma", "usado"],
    "palavras_preferidas": ["gato", "pet"],
}


def oferta(id_produto="1", titulo="Luminária LED de Mesa", preco=50.0, preco_original=100.0, **extra):
    return Oferta(fonte="mock", id_produto=id_produto, titulo=titulo, preco=preco,
                  preco_original=preco_original, link_afiliado="https://exemplo.com", **extra)


def test_oferta_boa_passa():
    assert motivo_rejeicao(oferta(), FILTROS) is None


def test_palavra_bloqueada_ignora_acento_e_maiuscula():
    assert "bloqueada" in motivo_rejeicao(oferta(titulo="Celular USADO bom estado"), FILTROS)


def test_palavra_bloqueada_so_palavra_inteira():
    # "arma" não pode bloquear "armário"
    assert motivo_rejeicao(oferta(titulo="Armário de Cozinha"), FILTROS) is None


def test_faixa_de_preco():
    assert motivo_rejeicao(oferta(preco=5, preco_original=10), FILTROS) == "preço abaixo do mínimo"
    assert motivo_rejeicao(oferta(preco=600, preco_original=1000), FILTROS) == "preço acima do máximo"


def test_desconto_minimo():
    assert motivo_rejeicao(oferta(preco=90, preco_original=100), FILTROS) == "desconto abaixo do mínimo"


def test_sem_desconto_informado_e_rejeitada():
    assert motivo_rejeicao(oferta(preco_original=None), FILTROS) == "desconto não informado"


def test_comissao_minima_so_quando_informada():
    assert motivo_rejeicao(oferta(comissao_pct=2.0), FILTROS) == "comissão abaixo do mínimo"
    assert motivo_rejeicao(oferta(comissao_pct=None), FILTROS) is None


def test_selecionar_remove_recentes_e_duplicadas():
    lista = [oferta("1"), oferta("1"), oferta("2")]
    resultado = selecionar(lista, FILTROS, chaves_recentes={"mock:2"})
    assert [o.id_produto for o in resultado] == ["1"]


def test_selecionar_prioriza_preferidas_depois_desconto():
    comum_grande = oferta("1", preco=10.5, preco_original=100)  # ~90% OFF
    pet = oferta("2", titulo="Arranhador para Gatos", preco=70, preco_original=100)  # 30% OFF
    comum_media = oferta("3", preco=50, preco_original=100)  # 50% OFF
    resultado = selecionar([comum_media, comum_grande, pet], FILTROS, set())
    assert [o.id_produto for o in resultado] == ["2", "1", "3"]


def test_fila_manual_do_ml_vem_primeiro():
    shopee_pet = Oferta(fonte="shopee", id_produto="9", titulo="Cama para Gato", preco=10.5,
                        preco_original=100, link_afiliado="https://exemplo.com")
    ml_comum = Oferta(fonte="ml", id_produto="https://ml.com/a", titulo="Luminária", preco=70,
                      preco_original=100, link_afiliado="https://ml.com/a")
    resultado = selecionar([shopee_pet, ml_comum], FILTROS, set())
    assert [o.fonte for o in resultado] == ["ml", "shopee"]


# ---------- avaliação, vendas e palavras bloqueadas ----------

def test_avaliacao_e_vendas_minimas_so_quando_informadas():
    filtros = {**FILTROS, "avaliacao_minima": 4.5, "vendas_minimas": 50}
    assert motivo_rejeicao(oferta(avaliacao=4.4, vendas=100), filtros) == "avaliação abaixo do mínimo"
    assert motivo_rejeicao(oferta(avaliacao=4.5, vendas=49), filtros) == "vendas abaixo do mínimo"
    assert motivo_rejeicao(oferta(avaliacao=4.5, vendas=50), filtros) is None
    assert motivo_rejeicao(oferta(avaliacao=None, vendas=None), filtros) is None  # ML/mock não informam


def config_exemplo():
    with open(ARQUIVO_CONFIG_EXEMPLO, encoding="utf-8") as f:
        return json.load(f)


BLOQUEIOS = {**FILTROS, "palavras_bloqueadas": ["réplica", "replica", "falsificado", "usado", "+18"]}


@pytest.mark.parametrize("titulo", [
    "Tênis Réplica", "Tenis replica", "Bolsa Falsificado", "Celular Usado",
    "Jogo de Cartas +18", "Produto (+18) Casal",
])
def test_palavras_bloqueadas(titulo):
    assert "bloqueada" in motivo_rejeicao(oferta(titulo=titulo), BLOQUEIOS)


@pytest.mark.parametrize("titulo", [
    "Kit 18 Potes Herméticos",       # "+18" só casa com o termo inteiro
    "Tênis Esportivo Original",
    "Mochila Usadíssima Promo",      # palavra inteira: "usado" não casa com "usadíssima"
])
def test_titulos_legitimos_nao_sao_bloqueados(titulo):
    assert motivo_rejeicao(oferta(titulo=titulo), BLOQUEIOS) is None


def test_config_de_exemplo_tem_as_chaves_esperadas():
    cfg = config_exemplo()
    assert set(cfg["horarios"]) == set(main.SLOTS)
    for chave in ("desconto_minimo_pct", "comissao_minima_pct", "preco_minimo", "preco_maximo",
                  "avaliacao_minima", "vendas_minimas", "max_por_palavra_busca",
                  "max_preferidas_por_horario", "palavras_bloqueadas", "palavras_preferidas"):
        assert chave in cfg["filtros"]
    assert cfg["shopee"]["palavras_busca"]


def test_config_json_ausente_avisa_como_criar(tmp_path):
    with pytest.raises(ErroConfig, match="config.example.json"):
        carregar(tmp_path / ".env", tmp_path / "config.json")


# ---------- Shopee: campos usados pelos filtros ----------

def test_shopee_converte_avaliacao_e_vendas():
    no = {"itemId": 1, "productName": "Areia para Gatos", "priceMin": "48.38", "offerLink": "https://s.shopee/x",
          "priceDiscountRate": 31, "commissionRate": "0.07", "ratingStar": "4.9", "sales": 24741}
    o = no_para_oferta(no)
    assert (o.avaliacao, o.vendas) == (4.9, 24741)
    o = no_para_oferta({**no, "ratingStar": None, "sales": None})
    assert (o.avaliacao, o.vendas) == (None, None)


class SessaoShopee:
    """Responde cada busca com 3 itens próprios da palavra."""

    def __init__(self):
        self.palavras = []

    def post(self, url, data=None, **_):
        consulta = json.loads(data)["query"]
        palavra = consulta.split('keyword: "')[1].split('"')[0]
        self.palavras.append(palavra)
        nos = [{"itemId": f"{len(self.palavras)}{i}", "productName": f"{palavra} {i}", "priceMin": "50",
                "offerLink": "https://s.shopee/x"} for i in range(3)]
        r = requests.Response()
        r.status_code = 200
        r._content = json.dumps({"data": {"productOfferV2": {"nodes": nos}}}).encode()
        return r


def test_shopee_busca_todas_as_palavras_e_marca_a_origem():
    sessao = SessaoShopee()
    fonte = FonteShopee("id", "segredo", {"palavras_busca": ["pet", "casa", "gato"]}, sessao=sessao)
    ofertas = fonte.buscar(1)  # mesmo pedindo 1, busca todas (variedade e nicho pet)
    assert sorted(sessao.palavras) == ["casa", "gato", "pet"]
    assert len(ofertas) == 9
    assert all(o.titulo.startswith(o.palavra_busca) for o in ofertas)


# ---------- variedade por palavra de busca ----------

def test_limite_por_palavra_de_busca():
    contagem = Counter({("palavra", "pet"): 2, ("palavra", "casa"): 1})
    filtros = {"max_por_palavra_busca": 2}
    assert motivo_variedade(oferta(palavra_busca="pet"), contagem, filtros)
    assert motivo_variedade(oferta(palavra_busca="casa"), contagem, filtros) is None
    assert motivo_variedade(oferta(palavra_busca=None), contagem, filtros) is None  # ML/mock: sem limite
    assert motivo_variedade(oferta(palavra_busca="pet"), contagem, {}) is None      # limite desligado


def test_limite_de_preferidas_no_horario():
    filtros = {**FILTROS, "max_preferidas_por_horario": 2}
    contagem = Counter()
    for titulo in ("Cama para Gato", "Coleira Pet"):
        assert motivo_variedade(oferta(titulo=titulo), contagem, filtros) is None
        contar_publicada(oferta(titulo=titulo), contagem, filtros)
    assert motivo_variedade(oferta(titulo="Arranhador para Gatos"), contagem, filtros) == "limite de preferidas no horário"
    assert motivo_variedade(oferta(titulo="Luminária LED"), contagem, filtros) is None  # demais buscas seguem


class FonteFalsa:
    def __init__(self, ofertas):
        self.ofertas = ofertas

    def buscar(self, quantidade):
        return self.ofertas

    def revalidar(self, oferta):
        return oferta


def test_horario_limita_preferidas_e_palavra_e_mostra_mensagem_de_dry_run(tmp_path, monkeypatch, caplog, capsys):
    # Preferidas vêm primeiro: 2 de "pet" + 2 de "gato" (maior desconto), depois 3 de "casa"; meta 4.
    # Esperado: 2 preferidas (o limite de preferidas barra as de "gato") + 2 casa (limite por palavra).
    pet = [Oferta(fonte="shopee", id_produto=f"p{i}", titulo=f"Comedouro Pet {i}", preco=50, desconto_pct=50,
                  link_afiliado="https://s.shopee/x", palavra_busca="pet") for i in range(2)]
    pet += [Oferta(fonte="shopee", id_produto=f"g{i}", titulo=f"Arranhador Gato {i}", preco=50, desconto_pct=45,
                   link_afiliado="https://s.shopee/x", palavra_busca="gato") for i in range(2)]
    casa = [Oferta(fonte="shopee", id_produto=f"c{i}", titulo=f"Luminária {i}", preco=50, desconto_pct=40,
                   link_afiliado="https://s.shopee/x", palavra_busca="casa") for i in range(3)]
    monkeypatch.setattr(main, "ARQUIVO_BANCO", tmp_path / "bot.db")
    monkeypatch.setattr(main, "criar_fontes", lambda *a, **k: {"shopee": FonteFalsa(pet + casa)})
    config = {"horarios": {"12": 4}, "multiplicador_candidatos": 3,
              "filtros": {**FILTROS, "max_por_palavra_busca": 2, "max_preferidas_por_horario": 2}}
    st = Settings(telegram_bot_token="", telegram_channel_id="", telegram_admin_chat_id="",
                  shopee_app_id="", shopee_app_secret="", config=config)

    with caplog.at_level(logging.INFO, logger="bot"):
        main.executar_slot(main.ler_argumentos(["--slot", "12", "--dry-run"]), st)

    saida = capsys.readouterr().out
    mostradas = [linha.split(" · ")[2].split(" ")[0] for linha in saida.splitlines() if linha.startswith("=====")]
    assert mostradas == ["shopee:p0", "shopee:p1", "shopee:c0", "shopee:c1"]
    assert "4 oferta(s) seriam publicadas (dry-run" in caplog.text
    assert "concluído" not in caplog.text
