from bot.fontes.base import Oferta
from bot.formatadores import formatar_preco, titulo_curto
from bot.formatadores import telegram, whatsapp


def oferta(**extra):
    dados = dict(fonte="mock", id_produto="1", titulo="Comedouro para Gatos", preco=89.9,
                 preco_original=159.9, link_afiliado="https://exemplo.com/p?a=1&b=2")
    dados.update(extra)
    return Oferta(**dados)


def test_formatar_preco_brasileiro():
    assert formatar_preco(1299.9) == "R$ 1.299,90"
    assert formatar_preco(9.5) == "R$ 9,50"


def test_titulo_curto_nao_corta_palavra():
    titulo = titulo_curto("palavra " * 20, limite=30)
    assert len(titulo) <= 30
    assert titulo.endswith("palavra…")


def test_telegram_de_por_e_desconto():
    texto = telegram.formatar(oferta())
    assert "De <s>R$ 159,90</s>" in texto
    assert "<b>R$ 89,90</b>" in texto
    assert "(44% OFF)" in texto


def test_telegram_escapa_html():
    texto = telegram.formatar(oferta(titulo="Kit <2 peças> & brinde"))
    assert "Kit &lt;2 peças&gt; &amp; brinde" in texto
    assert 'href="https://exemplo.com/p?a=1&amp;b=2"' in texto


def test_telegram_sem_preco_original_mostra_so_por():
    texto = telegram.formatar(oferta(preco_original=None, desconto_pct=30))
    assert "De " not in texto
    assert "(30% OFF)" in texto


def test_cupom_so_aparece_se_oficial():
    assert "Cupom" in telegram.formatar(oferta(cupom="OFERTA10", cupom_oficial=True))
    assert "Cupom" not in telegram.formatar(oferta(cupom="OFERTA10", cupom_oficial=False))
    assert "Cupom" not in whatsapp.formatar(oferta(cupom="OFERTA10", cupom_oficial=False))


def test_telegram_cabe_na_legenda():
    texto = telegram.formatar(oferta(titulo="x " * 500))
    assert len(texto) <= telegram.LIMITE_LEGENDA


def test_whatsapp_texto_simples():
    texto = whatsapp.formatar(oferta(cupom="OFERTA10", cupom_oficial=True))
    assert "*Comedouro para Gatos*" in texto
    assert "De ~R$ 159,90~" in texto
    assert "*OFERTA10*" in texto
    assert "https://exemplo.com/p?a=1&b=2" in texto
    assert "<" not in texto


def test_linha_da_loja_abaixo_do_titulo():
    for fonte, loja in [("shopee", "🛍️ Shopee"), ("ml", "🛍️ Mercado Livre")]:
        for formatador in (telegram, whatsapp):
            linhas = formatador.formatar(oferta(fonte=fonte)).splitlines()
            assert linhas[1] == loja


def test_sem_linha_da_loja_para_fonte_desconhecida():
    for formatador in (telegram, whatsapp):
        assert "🛍️" not in formatador.formatar(oferta(fonte="mock"))


def test_telegram_cupom_toque_para_copiar():
    texto = telegram.formatar(oferta(cupom="OFERTA10", cupom_oficial=True))
    assert "<code>OFERTA10</code> (toque para copiar)" in texto
    assert "toque para copiar" not in whatsapp.formatar(oferta(cupom="OFERTA10", cupom_oficial=True))
