"""Post do Telegram: legenda em HTML (parse_mode=HTML)."""
from html import escape

from bot.fontes.base import Oferta
from bot.formatadores import formatar_preco, linha_loja, texto_desconto, titulo_curto

LIMITE_LEGENDA = 1024  # limite do Telegram para legenda de foto


def formatar(oferta: Oferta) -> str:
    linhas = [f"🔥 <b>{escape(titulo_curto(oferta.titulo))}</b>"]
    loja = linha_loja(oferta.fonte)
    if loja:
        linhas.append(loja)
    linhas.append("")

    if oferta.tem_preco_original:
        linhas.append(f"De <s>{formatar_preco(oferta.preco_original)}</s>")
    por = f"💰 Por <b>{formatar_preco(oferta.preco)}</b>"
    desconto = texto_desconto(oferta.desconto_pct)
    if desconto:
        por += f" ({desconto})"
    linhas.append(por)

    if oferta.cupom_publicavel:
        linhas.append(f"🎟️ Cupom: <code>{escape(oferta.cupom_publicavel)}</code> (toque para copiar)")

    linhas += ["", f'🛒 <a href="{escape(oferta.link_afiliado, quote=True)}">Comprar agora</a>']
    # Não cortamos o texto (quebraria o HTML). O título já é curto; se ainda
    # passar do limite, o sendPhoto falha e o publicador cai para sendMessage.
    return "\n".join(linhas)
