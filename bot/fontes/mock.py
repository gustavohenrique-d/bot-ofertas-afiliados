"""Fonte de teste: 3 ofertas falsas, para testar formatação e publicação sem chaves."""
from bot.fontes.base import Fonte, Oferta

OFERTAS_EXEMPLO = [
    dict(
        id_produto="mock-1",
        titulo="Comedouro Automático para Gatos e Cães 3,5L com Timer Programável",
        preco=119.90,
        preco_original=219.90,
        comissao_pct=10.0,
        loja="Pet Shop Oficial",
        imagem_url="https://placehold.co/800x800/png?text=Comedouro+Pet",
        link_afiliado="https://example.com/oferta/teste-1",
        cupom="PET10",
        cupom_oficial=True,
    ),
    dict(
        id_produto="mock-2",
        titulo="Fone de Ouvido Bluetooth 5.3 sem Fio com Case Carregador",
        preco=59.90,
        preco_original=129.90,
        comissao_pct=8.0,
        loja="Loja Tech",
        imagem_url="https://placehold.co/800x800/png?text=Fone+Bluetooth",
        link_afiliado="https://example.com/oferta/teste-2",
    ),
    dict(
        id_produto="mock-3",
        titulo="Kit 3 Potes Herméticos de Vidro com Tampa de Bambu 1L",
        preco=74.90,
        preco_original=99.90,
        comissao_pct=12.0,
        loja="Casa & Cozinha",
        imagem_url="https://placehold.co/800x800/png?text=Potes+de+Vidro",
        link_afiliado="https://example.com/oferta/teste-3",
        cupom="NAOOFICIAL",  # não oficial: não pode aparecer no post
        cupom_oficial=False,
    ),
]


class FonteMock(Fonte):
    nome = "mock"

    def buscar(self, quantidade: int) -> list[Oferta]:
        return [Oferta(fonte=self.nome, **dados) for dados in OFERTAS_EXEMPLO]

    def revalidar(self, oferta: Oferta) -> Oferta | None:
        return oferta
