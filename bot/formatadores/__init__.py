"""Funções comuns aos formatadores de post."""

# Nome da loja exibido no post, por fonte (fontes fora da lista não mostram loja)
NOMES_LOJA = {"shopee": "Shopee", "ml": "Mercado Livre"}


def linha_loja(fonte: str) -> str | None:
    """Ex.: "shopee" -> "🛍️ Shopee"; None para fontes sem loja definida (ex.: mock)."""
    nome = NOMES_LOJA.get(fonte)
    return f"🛍️ {nome}" if nome else None


def formatar_preco(valor: float) -> str:
    """1299.9 -> "R$ 1.299,90"."""
    inteiro, centavos = f"{valor:,.2f}".split(".")
    return f"R$ {inteiro.replace(',', '.')},{centavos}"


def titulo_curto(titulo: str, limite: int = 80) -> str:
    """Encurta o título sem cortar palavra no meio."""
    texto = " ".join((titulo or "").split())
    if len(texto) <= limite:
        return texto
    corte = texto[: limite - 1].rsplit(" ", 1)[0] or texto[: limite - 1]
    return corte.rstrip(" ,.-–") + "…"


def texto_desconto(desconto_pct: float | None) -> str | None:
    if desconto_pct is None or desconto_pct < 1:
        return None
    return f"{round(desconto_pct)}% OFF"
