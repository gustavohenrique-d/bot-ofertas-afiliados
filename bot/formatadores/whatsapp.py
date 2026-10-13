"""Post do WhatsApp: texto simples com *negrito* e ~riscado~."""
from bot.fontes.base import Oferta
from bot.formatadores import formatar_preco, linha_loja, texto_desconto, titulo_curto


def formatar(oferta: Oferta) -> str:
    # Asteriscos no título quebrariam o negrito
    titulo = titulo_curto(oferta.titulo).replace("*", "")
    linhas = [f"🔥 *{titulo}*"]
    loja = linha_loja(oferta.fonte)
    if loja:
        linhas.append(loja)
    linhas.append("")

    if oferta.tem_preco_original:
        linhas.append(f"De ~{formatar_preco(oferta.preco_original)}~")
    por = f"💰 Por *{formatar_preco(oferta.preco)}*"
    desconto = texto_desconto(oferta.desconto_pct)
    if desconto:
        por += f" ({desconto})"
    linhas.append(por)

    if oferta.cupom_publicavel:
        linhas.append(f"🎟️ Cupom: *{oferta.cupom_publicavel}*")

    linhas += ["", f"🛒 {oferta.link_afiliado}"]
    return "\n".join(linhas)
