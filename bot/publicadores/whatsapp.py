"""Publicação no WhatsApp pela ponte local do Hermes Agent (Baileys).

A ponte só é acessível de dentro da VM:
    POST /send       {"chatId", "message"}
    POST /send-media {"chatId", "filePath", "mediaType": "image", "caption"}
filePath é um arquivo local, por isso a imagem é baixada antes e apagada depois.
"""
import logging
import os
import random
import tempfile
from pathlib import Path

import requests

from bot.fontes.base import Oferta
from bot.formatadores.whatsapp import formatar
from bot.publicadores import PublicadorIndisponivel

log = logging.getLogger(__name__)

EXTENSOES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}


class ErroWhatsApp(Exception):
    pass


class WhatsAppDesconectado(PublicadorIndisponivel):
    """A ponte respondeu 503: o WhatsApp está desconectado."""


class ErroImagem(Exception):
    """A imagem não pôde ser baixada (tipo errado, grande demais...)."""


def _sucesso(resposta) -> bool:
    return 200 <= resposta.status_code < 300


class PublicadorWhatsApp:
    nome = "whatsapp"

    def __init__(self, chat_id: str, url_ponte: str, timeout: float = 30,
                 timeout_imagem: float = 10, imagem_max_mb: float = 5,
                 pausa_min: float = 20, pausa_max: float = 40,
                 sessao=None, pasta_temp: Path | None = None, sortear=random.uniform):
        self.chat_id = chat_id
        self.url_ponte = url_ponte.rstrip("/")
        self.timeout = timeout
        self.timeout_imagem = timeout_imagem
        self.imagem_max_bytes = int(imagem_max_mb * 1024 * 1024)
        self.pausa_min, self.pausa_max = sorted((pausa_min, pausa_max))
        self.sessao = sessao or requests.Session()
        self.pasta_temp = pasta_temp  # None = pasta temporária do sistema
        self.sortear = sortear

    def pausa(self) -> float:
        """Pausa com variação aleatória, para reduzir o risco de bloqueio do número."""
        return self.sortear(self.pausa_min, self.pausa_max)

    def publicar(self, oferta: Oferta) -> None:
        texto = formatar(oferta)
        if oferta.imagem_url and self._enviar_com_imagem(oferta.imagem_url, texto):
            return
        resposta = self._post("/send", {"chatId": self.chat_id, "message": texto})
        if not _sucesso(resposta):
            raise ErroWhatsApp(f"/send: HTTP {resposta.status_code}: {resposta.text[:200]}".strip())

    def _enviar_com_imagem(self, url: str, legenda: str) -> bool:
        """True se a foto foi enviada; False para cair no envio só de texto."""
        try:
            caminho = self._baixar_imagem(url)
        except (requests.RequestException, ErroImagem, OSError) as e:
            log.warning("Imagem não baixada (%s); enviando só o texto", e)
            return False
        try:
            resposta = self._post("/send-media", {
                "chatId": self.chat_id,
                "filePath": str(caminho),
                "mediaType": "image",
                "caption": legenda,
            })
        finally:
            caminho.unlink(missing_ok=True)  # apaga mesmo se der erro
        if _sucesso(resposta):
            return True
        log.warning("/send-media respondeu HTTP %s; enviando só o texto", resposta.status_code)
        return False

    def _baixar_imagem(self, url: str) -> Path:
        resposta = self.sessao.get(url, timeout=self.timeout_imagem, stream=True)
        try:
            resposta.raise_for_status()
            tipo = resposta.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if not tipo.startswith("image/"):
                raise ErroImagem(f"conteúdo não é imagem ({tipo or 'sem tipo'})")
            descritor, nome = tempfile.mkstemp(prefix="oferta_", suffix=EXTENSOES.get(tipo, ".jpg"),
                                               dir=self.pasta_temp)
            caminho = Path(nome)
            try:
                with os.fdopen(descritor, "wb") as arquivo:
                    total = 0
                    for bloco in resposta.iter_content(64 * 1024):
                        total += len(bloco)
                        if total > self.imagem_max_bytes:
                            raise ErroImagem("imagem maior que o limite")
                        arquivo.write(bloco)
            except BaseException:
                caminho.unlink(missing_ok=True)
                raise
            return caminho
        finally:
            resposta.close()

    def _post(self, rota: str, dados: dict):
        """Chama a ponte. Rede ou 503 viram falha, sem nova tentativa (evita post duplicado)."""
        try:
            resposta = self.sessao.post(self.url_ponte + rota, json=dados, timeout=self.timeout)
        except requests.RequestException as e:
            raise ErroWhatsApp(f"{rota}: falha de rede ({type(e).__name__})") from e
        if resposta.status_code == 503:
            raise WhatsAppDesconectado(f"{rota}: WhatsApp desconectado (HTTP 503)")
        return resposta
