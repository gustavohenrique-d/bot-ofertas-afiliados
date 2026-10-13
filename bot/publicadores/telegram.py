"""Publicação no Telegram via Bot API (requests)."""
import logging
import time

import requests

from bot.fontes.base import Oferta
from bot.formatadores.telegram import formatar

log = logging.getLogger(__name__)

URL_API = "https://api.telegram.org/bot{token}/{metodo}"
ESPERA_MAXIMA = 120  # não segura o horário por mais que isso num 429


class ErroTelegram(Exception):
    pass


class ClienteTelegram:
    """Chamada à Bot API com nova tentativa em erro temporário (429 e 5xx)."""

    def __init__(self, token: str, tentativas: int = 3, timeout: int = 20,
                 sessao=None, dormir=time.sleep):
        self.token = token
        self.tentativas = max(1, tentativas)
        self.timeout = timeout
        self.sessao = sessao or requests.Session()
        self.dormir = dormir

    def _sem_token(self, texto: str) -> str:
        """Tira o token de mensagens de erro antes de ir para log/aviso."""
        if self.token and len(self.token) >= 8:
            return texto.replace(self.token, "***")
        return texto

    def chamar(self, metodo: str, dados: dict) -> dict:
        url = URL_API.format(token=self.token, metodo=metodo)
        ultimo_erro = ""
        for tentativa in range(1, self.tentativas + 1):
            try:
                resposta = self.sessao.post(url, data=dados, timeout=self.timeout)
            except requests.RequestException as e:
                ultimo_erro = f"falha de rede ({type(e).__name__})"
                espera = 2 ** tentativa
            else:
                try:
                    corpo = resposta.json()
                except ValueError:
                    corpo = {}
                if resposta.status_code == 200 and corpo.get("ok"):
                    return corpo.get("result") or {}
                ultimo_erro = f"HTTP {resposta.status_code}: {corpo.get('description', '')}".strip()
                if resposta.status_code == 429:
                    espera = int((corpo.get("parameters") or {}).get("retry_after", 5)) + 1
                    if espera > ESPERA_MAXIMA:
                        break
                elif resposta.status_code >= 500:
                    espera = 2 ** tentativa
                else:
                    # Erro permanente (400, 401, 403...): não adianta repetir
                    raise ErroTelegram(self._sem_token(f"{metodo}: {ultimo_erro}"))
            if tentativa < self.tentativas:
                log.warning("Telegram %s: %s. Nova tentativa em %ss",
                            metodo, self._sem_token(ultimo_erro), espera)
                self.dormir(espera)
        raise ErroTelegram(self._sem_token(f"{metodo} falhou após {tentativa} tentativa(s): {ultimo_erro}"))


class PublicadorTelegram:
    nome = "telegram"

    def __init__(self, cliente: ClienteTelegram, chat_id: str, pausa_seg: float = 5):
        self.cliente = cliente
        self.chat_id = chat_id
        self.pausa_seg = pausa_seg

    def pausa(self) -> float:
        return self.pausa_seg

    def publicar(self, oferta: Oferta) -> None:
        texto = formatar(oferta)
        if oferta.imagem_url:
            try:
                self.cliente.chamar("sendPhoto", {
                    "chat_id": self.chat_id,
                    "photo": oferta.imagem_url,
                    "caption": texto,
                    "parse_mode": "HTML",
                })
                return
            except ErroTelegram as e:
                log.warning("sendPhoto falhou (%s); enviando só o texto", e)
        self.cliente.chamar("sendMessage", {
            "chat_id": self.chat_id,
            "text": texto,
            "parse_mode": "HTML",
        })
