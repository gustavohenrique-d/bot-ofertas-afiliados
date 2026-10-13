import io
import json
import os

import pytest
import requests

import main
from bot.fontes.base import Oferta
from bot.publicadores.whatsapp import ErroWhatsApp, PublicadorWhatsApp, WhatsAppDesconectado
from config.settings import ARQUIVO_CONFIG_EXEMPLO, ErroConfig, Settings, exigir_id_whatsapp

PONTE = "http://localhost:3000"
GRUPO = "000000000000000000@g.us"


def resposta(status=200, corpo=b"", tipo="application/json"):
    r = requests.Response()
    r.status_code = status
    r.raw = io.BytesIO(corpo)
    r.headers["Content-Type"] = tipo
    r.url = "http://teste"
    return r


class PonteFalsa:
    """Simula a sessão do requests: imagem no GET e ponte do WhatsApp no POST."""

    def __init__(self, imagem=None, respostas=None):
        # "is None" e não "or": um Response 404 é falso em bool()
        self.imagem = imagem if imagem is not None else resposta(corpo=b"\x89PNG dados", tipo="image/png")
        self.respostas = respostas or {}   # rota -> resposta ou exceção
        self.envios = []                   # (rota, json, arquivo existia no envio?)

    def get(self, url, **_):
        if isinstance(self.imagem, Exception):
            raise self.imagem
        return self.imagem

    def post(self, url, json=None, **_):
        rota = url.removeprefix(PONTE)
        caminho = json.get("filePath")
        existia = bool(caminho) and os.path.exists(caminho)
        self.envios.append((rota, json, existia))
        retorno = self.respostas.get(rota, resposta(200, b'{"ok":true}'))
        if isinstance(retorno, Exception):
            raise retorno
        return retorno


def oferta(**extra):
    dados = dict(fonte="shopee", id_produto="1", titulo="Comedouro para Gatos", preco=89.9,
                 preco_original=159.9, link_afiliado="https://exemplo.com/p",
                 imagem_url="https://exemplo.com/foto.png")
    dados.update(extra)
    return Oferta(**dados)


@pytest.fixture
def pasta(tmp_path):
    return tmp_path / "tmp"


def publicador(sessao, pasta, **extra):
    pasta.mkdir(exist_ok=True)
    return PublicadorWhatsApp(GRUPO, PONTE + "/", sessao=sessao, pasta_temp=pasta, **extra)


# ---------- envio ----------

def test_envia_com_imagem_e_apaga_arquivo(pasta):
    ponte = PonteFalsa()
    publicador(ponte, pasta).publicar(oferta())

    assert len(ponte.envios) == 1
    rota, dados, existia = ponte.envios[0]
    assert rota == "/send-media"
    assert dados["chatId"] == GRUPO
    assert dados["mediaType"] == "image"
    assert dados["filePath"].endswith(".png")
    assert "*Comedouro para Gatos*" in dados["caption"]
    assert existia                      # arquivo existia na hora do envio
    assert list(pasta.iterdir()) == []  # e foi apagado depois


def test_sem_imagem_envia_so_texto(pasta):
    ponte = PonteFalsa()
    publicador(ponte, pasta).publicar(oferta(imagem_url=None))
    assert [e[0] for e in ponte.envios] == ["/send"]
    assert "*Comedouro para Gatos*" in ponte.envios[0][1]["message"]


@pytest.mark.parametrize("imagem", [
    requests.ConnectionError("sem rede"),
    resposta(404, b"nao achou", tipo="text/html"),
    resposta(200, b"<html>", tipo="text/html"),   # não é imagem
])
def test_download_falhou_cai_para_texto(pasta, imagem):
    ponte = PonteFalsa(imagem=imagem)
    publicador(ponte, pasta).publicar(oferta())
    assert [e[0] for e in ponte.envios] == ["/send"]
    assert list(pasta.iterdir()) == []


def test_imagem_grande_demais_cai_para_texto(pasta):
    ponte = PonteFalsa(imagem=resposta(corpo=b"x" * 2048, tipo="image/jpeg"))
    publicador(ponte, pasta, imagem_max_mb=1 / 1024).publicar(oferta())
    assert [e[0] for e in ponte.envios] == ["/send"]
    assert list(pasta.iterdir()) == []


def test_send_media_com_erro_cai_para_texto(pasta):
    ponte = PonteFalsa(respostas={"/send-media": resposta(500, b"erro")})
    publicador(ponte, pasta).publicar(oferta())
    assert [e[0] for e in ponte.envios] == ["/send-media", "/send"]
    assert list(pasta.iterdir()) == []


# ---------- falhas ----------

def test_503_no_send_media_e_falha_sem_tentar_texto(pasta):
    ponte = PonteFalsa(respostas={"/send-media": resposta(503)})
    with pytest.raises(WhatsAppDesconectado):
        publicador(ponte, pasta).publicar(oferta())
    assert [e[0] for e in ponte.envios] == ["/send-media"]
    assert list(pasta.iterdir()) == []  # apagado mesmo com erro


def test_503_no_send_e_falha(pasta):
    ponte = PonteFalsa(respostas={"/send": resposta(503)})
    with pytest.raises(WhatsAppDesconectado):
        publicador(ponte, pasta).publicar(oferta(imagem_url=None))


def test_erro_de_rede_no_envio_e_falha_sem_fallback(pasta):
    ponte = PonteFalsa(respostas={"/send-media": requests.Timeout("demorou")})
    with pytest.raises(ErroWhatsApp, match="falha de rede"):
        publicador(ponte, pasta).publicar(oferta())
    assert [e[0] for e in ponte.envios] == ["/send-media"]  # não reenvia: evita post duplicado
    assert list(pasta.iterdir()) == []


def test_send_com_erro_permanente_e_falha(pasta):
    ponte = PonteFalsa(respostas={"/send": resposta(400, b"chatId invalido")})
    with pytest.raises(ErroWhatsApp, match="HTTP 400"):
        publicador(ponte, pasta).publicar(oferta(imagem_url=None))


# ---------- pausa e configuração ----------

def test_pausa_fica_entre_minimo_e_maximo(pasta):
    p = publicador(PonteFalsa(), pasta, pausa_min=20, pausa_max=40)
    for _ in range(50):
        assert 20 <= p.pausa() <= 40


def config_exemplo():
    with open(ARQUIVO_CONFIG_EXEMPLO, encoding="utf-8") as f:
        return json.load(f)


def settings(**extra):
    dados = dict(telegram_bot_token="", telegram_channel_id="", telegram_admin_chat_id="",
                 shopee_app_id="", shopee_app_secret="", config=config_exemplo())
    dados.update(extra)
    return Settings(**dados)


def test_publicadores_ativos_do_env_substitui_config():
    st = settings(config={"publicadores_ativos": ["telegram"]}, publicadores_env=" Telegram, whatsapp ,")
    assert st.publicadores_ativos == ["telegram", "whatsapp"]


def test_publicadores_ativos_sem_env_usa_config():
    st = settings(config={"publicadores_ativos": ["telegram"]})
    assert st.publicadores_ativos == ["telegram"]


def test_id_whatsapp_confere_formato():
    assert exigir_id_whatsapp(GRUPO, "WHATSAPP_GROUP_ID", "@g.us") == GRUPO
    with pytest.raises(ErroConfig, match="@g.us"):
        exigir_id_whatsapp("0000000000000@s.whatsapp.net", "WHATSAPP_GROUP_ID", "@g.us")
    with pytest.raises(ErroConfig, match="não está definida"):
        exigir_id_whatsapp("", "WHATSAPP_ADMIN_ID", "@s.whatsapp.net")


def test_destinos_canal_e_admin():
    st = settings(telegram_bot_token="123:abc", telegram_channel_id="@canal",
                  telegram_admin_chat_id="42", whatsapp_group_id=GRUPO,
                  whatsapp_admin_id="0000000000000@s.whatsapp.net")
    (tg, wa), problemas = main.criar_publicadores(["telegram", "whatsapp"], st, "canal")
    assert (tg.chat_id, wa.chat_id) == ("@canal", GRUPO)
    assert problemas == []
    (tg, wa), _ = main.criar_publicadores(["telegram", "whatsapp"], st, "admin")
    assert (tg.chat_id, wa.chat_id) == ("42", "0000000000000@s.whatsapp.net")


@pytest.mark.parametrize("destino, extra, variavel", [
    ("canal", {}, "WHATSAPP_GROUP_ID"),                                         # ausente
    ("canal", {"whatsapp_group_id": "0000000000000@s.whatsapp.net"}, "@g.us"),  # inválido
    ("admin", {}, "WHATSAPP_ADMIN_ID"),
    ("admin", {"whatsapp_admin_id": GRUPO}, "@s.whatsapp.net"),
])
def test_whatsapp_sem_config_e_pulado_e_telegram_segue(destino, extra, variavel):
    st = settings(telegram_bot_token="123:abc", telegram_channel_id="@canal",
                  telegram_admin_chat_id="42", **extra)
    publicadores, problemas = main.criar_publicadores(["telegram", "whatsapp"], st, destino)
    assert [p.nome for p in publicadores] == ["telegram"]
    assert len(problemas) == 1
    assert problemas[0].startswith("[whatsapp] pulado") and variavel in problemas[0]


def test_nenhum_publicador_criado_para_tudo():
    with pytest.raises(ErroConfig, match="Nenhum publicador"):
        main.criar_publicadores(["telegram", "whatsapp"], settings(), "canal")


# ---------- fluxo do horário ----------

class PublicadorFalso:
    def __init__(self, nome, pausa, erro=None):
        self.nome, self._pausa, self.erro, self.enviadas = nome, pausa, erro, []

    def pausa(self):
        return self._pausa

    def publicar(self, oferta):
        self.enviadas.append(oferta.chave)
        if self.erro:
            raise self.erro


def test_503_pula_whatsapp_no_resto_do_horario(tmp_path, monkeypatch):
    telegram = PublicadorFalso("telegram", 5)
    whatsapp = PublicadorFalso("whatsapp", 30, WhatsAppDesconectado("/send-media: HTTP 503"))
    pausas, avisos = [], []
    monkeypatch.setattr(main, "ARQUIVO_BANCO", tmp_path / "bot.db")
    monkeypatch.setattr(main, "criar_publicadores", lambda *a, **k: ([telegram, whatsapp], []))
    monkeypatch.setattr(main.time, "sleep", pausas.append)
    monkeypatch.setattr(main.Avisador, "avisar", lambda self, texto: avisos.append(texto))

    args = main.ler_argumentos(["--slot", "12", "--fonte", "mock"])
    main.executar_slot(args, settings())

    assert len(telegram.enviadas) == 3        # Telegram segue normal
    assert len(whatsapp.enviadas) == 1        # WhatsApp só na primeira oferta
    assert pausas == [5, 5]                   # sem a pausa longa depois que caiu
    assert len(avisos) == 1                   # um aviso só
    assert avisos[0].count("[whatsapp]") == 2  # a falha e o "pulado no resto do horário"


def test_horario_sem_config_do_whatsapp_publica_no_telegram_e_avisa(tmp_path, monkeypatch):
    telegram = PublicadorFalso("telegram", 5)
    avisos = []
    monkeypatch.setattr(main, "ARQUIVO_BANCO", tmp_path / "bot.db")
    monkeypatch.setattr(main, "criar_publicadores", lambda *a, **k: (
        [telegram], ["[whatsapp] pulado: A variável WHATSAPP_GROUP_ID não está definida no .env"]))
    monkeypatch.setattr(main.time, "sleep", lambda _: None)
    monkeypatch.setattr(main.Avisador, "avisar", lambda self, texto: avisos.append(texto))

    args = main.ler_argumentos(["--slot", "12", "--fonte", "mock"])
    main.executar_slot(args, settings())

    assert len(telegram.enviadas) == 3
    assert len(avisos) == 1 and "WHATSAPP_GROUP_ID" in avisos[0]
