from datetime import timedelta

import pytest

from bot import banco as modulo_banco
from bot.banco import Banco
from bot.fontes.mercadolivre import FonteMercadoLivre, ler_preco

CABECALHO = "link_afiliado,titulo,preco,preco_original,imagem_url,cupom,cupom_oficial\n"


@pytest.fixture
def fila(tmp_path):
    arquivo = tmp_path / "fila.csv"
    arquivo.write_text(
        CABECALHO
        + 'https://ml.com/a,Coleira para Cachorro,"39,90","79,90",https://img/a.jpg,OFERTA10,sim\n'
        + "https://ml.com/b,Tapete Higiênico,49.90,99.90,,CUPOMX,não\n"
        + ",Sem link,10,20,,,\n",
        encoding="utf-8",
    )
    return arquivo


def test_ler_preco_formatos():
    assert ler_preco("129.90") == 129.90
    assert ler_preco("129,90") == 129.90
    assert ler_preco("R$ 1.299,90") == 1299.90
    assert ler_preco("") is None
    assert ler_preco("abc") is None


def test_le_fila_e_ignora_linha_invalida(tmp_path, fila):
    with Banco(tmp_path / "bot.db") as banco:
        ofertas = FonteMercadoLivre(fila, banco).buscar(10)
    assert [o.link_afiliado for o in ofertas] == ["https://ml.com/a", "https://ml.com/b"]
    a, b = ofertas
    assert a.preco == 39.90 and a.preco_original == 79.90
    assert a.cupom_publicavel == "OFERTA10"
    assert b.cupom_publicavel is None  # cupom_oficial = não


def test_aceita_ponto_e_virgula(tmp_path):
    arquivo = tmp_path / "fila.csv"
    arquivo.write_text(CABECALHO.replace(",", ";") + "https://ml.com/a;Coleira;39,90;79,90;;;\n",
                       encoding="utf-8")
    with Banco(tmp_path / "bot.db") as banco:
        ofertas = FonteMercadoLivre(arquivo, banco).buscar(10)
    assert len(ofertas) == 1 and ofertas[0].preco == 39.90


def test_ignora_oferta_vencida(tmp_path, fila, monkeypatch):
    caminho = tmp_path / "bot.db"
    with Banco(caminho) as banco:
        FonteMercadoLivre(fila, banco, validade_horas=24).buscar(10)  # registra "vista"

    # 25 horas depois
    futuro = modulo_banco.agora_utc() + timedelta(hours=25)
    monkeypatch.setattr("bot.fontes.mercadolivre.agora_utc", lambda: futuro)
    with Banco(caminho) as banco:
        assert FonteMercadoLivre(fila, banco, validade_horas=24).buscar(10) == []


def test_publicada_nao_volta(tmp_path, fila):
    caminho = tmp_path / "bot.db"
    with Banco(caminho) as banco:
        fonte = FonteMercadoLivre(fila, banco)
        primeira = fonte.buscar(10)[0]
        banco.registrar_publicacao(primeira, "08", ["telegram"])
        restantes = fonte.buscar(10)
    assert [o.link_afiliado for o in restantes] == ["https://ml.com/b"]


def test_dry_run_nao_grava_nada(tmp_path, fila):
    caminho = tmp_path / "bot.db"
    # Sem banco existente: não cria arquivo
    with Banco(caminho, gravar=False) as banco:
        ofertas = FonteMercadoLivre(fila, banco).buscar(10)
        banco.registrar_publicacao(ofertas[0], "08", ["telegram"])
    assert not caminho.exists()

    # Com banco existente: não registra "vista" nem publicação
    Banco(caminho).fechar()
    with Banco(caminho, gravar=False) as banco:
        ofertas = FonteMercadoLivre(fila, banco).buscar(10)
        banco.registrar_publicacao(ofertas[0], "08", ["telegram"])
    with Banco(caminho) as banco:
        assert banco.situacao_fila("ml", "https://ml.com/a") == (None, None)
        assert banco.chaves_recentes(7) == set()
