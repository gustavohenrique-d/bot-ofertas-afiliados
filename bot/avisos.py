"""Alertas de erro no chat privado do administrador (nunca no canal)."""
import logging

log = logging.getLogger(__name__)

LIMITE_TEXTO = 3500


class Avisador:
    """Envia avisos curtos ao TELEGRAM_ADMIN_CHAT_ID. Com ativo=False só registra no log."""

    def __init__(self, cliente=None, chat_id: str = "", ativo: bool = True):
        self.cliente = cliente
        self.chat_id = chat_id
        self.ativo = ativo

    def avisar(self, texto: str) -> None:
        if not self.ativo:
            log.warning("Aviso (não enviado, dry-run): %s", texto)
            return
        log.warning("Aviso ao admin: %s", texto)
        if not (self.cliente and self.chat_id):
            log.error("Aviso não enviado: TELEGRAM_BOT_TOKEN/TELEGRAM_ADMIN_CHAT_ID ausentes")
            return
        try:
            # Texto puro (sem parse_mode) para não quebrar com caracteres especiais
            self.cliente.chamar("sendMessage", {
                "chat_id": self.chat_id,
                "text": f"⚠️ Bot de ofertas\n{texto}"[:LIMITE_TEXTO],
            })
        except Exception as e:  # o aviso nunca pode derrubar o bot
            log.error("Não consegui enviar o aviso ao admin: %s", e)
