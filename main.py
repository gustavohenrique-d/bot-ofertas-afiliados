"""Bot de Ofertas de Afiliados — ponto de entrada.

Uso:
    python main.py --slot 08                 publica as ofertas do horário (08, 12, 18 ou 21)
    python main.py --dry-run                 mostra os posts no terminal, sem enviar nem gravar
    python main.py --test                    envia 1 oferta falsa aos seus destinos privados
                                             (Telegram: TELEGRAM_ADMIN_CHAT_ID, WhatsApp: WHATSAPP_ADMIN_ID)
    python main.py --test --canal            envia 1 oferta falsa ao canal do Telegram e ao grupo do WhatsApp
    python main.py --fonte mock|shopee|ml    escolhe a fonte (padrão: fontes_padrao do config)
"""
import argparse
import logging
import sys
import time
from collections import Counter
from datetime import datetime
from logging.handlers import RotatingFileHandler

from bot import filtros
from bot.avisos import Avisador
from bot.banco import Banco
from bot.fontes.base import Fonte, FonteIndisponivel, Oferta
from bot.fontes.mercadolivre import FonteMercadoLivre
from bot.fontes.mock import FonteMock
from bot.fontes.shopee import FonteShopee
from bot.formatadores import telegram as formatador_telegram
from bot.formatadores import whatsapp as formatador_whatsapp
from bot.publicadores import PublicadorIndisponivel
from bot.publicadores.telegram import ClienteTelegram, PublicadorTelegram
from bot.publicadores.whatsapp import PublicadorWhatsApp
from config.settings import (ARQUIVO_BANCO, ARQUIVO_FILA_ML, PASTA_LOGS, ErroConfig,
                             Settings, carregar, exigir, exigir_id_whatsapp)

SLOTS = ("08", "12", "18", "21")
FORMATADORES = {"telegram": formatador_telegram.formatar, "whatsapp": formatador_whatsapp.formatar}
# Nome amigável de cada destino, para as mensagens do --test
NOMES_DESTINO = {("telegram", "canal"): "canal", ("telegram", "admin"): "seu chat privado",
                 ("whatsapp", "canal"): "grupo", ("whatsapp", "admin"): "seu número"}

log = logging.getLogger("bot")


# ---------- preparação ----------

def ler_argumentos(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bot de Ofertas de Afiliados")
    parser.add_argument("--slot", choices=SLOTS, help="horário a publicar (padrão: o mais próximo de agora)")
    parser.add_argument("--fonte", choices=["mock", "shopee", "ml"], help="usa só esta fonte")
    parser.add_argument("--dry-run", action="store_true", help="mostra os posts sem enviar e sem gravar nada")
    parser.add_argument("--test", action="store_true", help="envia 1 oferta falsa aos destinos privados")
    parser.add_argument("--canal", action="store_true",
                        help="com --test, envia ao canal/grupo em vez dos destinos privados")
    args = parser.parse_args(argv)
    if args.canal and not args.test:
        parser.error("--canal só pode ser usado junto com --test")
    return args


def configurar_logs(no_terminal: bool) -> None:
    PASTA_LOGS.mkdir(exist_ok=True)
    formato = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    raiz = logging.getLogger()
    raiz.setLevel(logging.INFO)
    arquivo = RotatingFileHandler(PASTA_LOGS / "bot.log", maxBytes=1_000_000,
                                  backupCount=5, encoding="utf-8")
    arquivo.setFormatter(formato)
    raiz.addHandler(arquivo)
    # No terminal: tudo. No cron (sem terminal): só avisos e erros, que vão para cron.log
    terminal = logging.StreamHandler()
    terminal.setFormatter(formato)
    terminal.setLevel(logging.INFO if no_terminal else logging.WARNING)
    raiz.addHandler(terminal)
    # urllib3 em DEBUG mostraria a URL com o token do bot
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def criar_cliente_telegram(st: Settings, tentativas: int | None = None) -> ClienteTelegram:
    cfg = st.config.get("telegram", {})
    return ClienteTelegram(st.telegram_bot_token,
                           tentativas=tentativas or int(cfg.get("tentativas", 3)),
                           timeout=int(cfg.get("timeout_seg", 20)))


def criar_avisador(st: Settings, ativo: bool) -> Avisador:
    cliente = criar_cliente_telegram(st, tentativas=2) if st.telegram_bot_token else None
    return Avisador(cliente, st.telegram_admin_chat_id, ativo=ativo)


def criar_fontes(nomes: list[str], st: Settings, banco: Banco) -> dict[str, Fonte]:
    fontes = {}
    for nome in nomes:
        try:
            if nome == "mock":
                fontes[nome] = FonteMock()
            elif nome == "shopee":
                fontes[nome] = FonteShopee(st.shopee_app_id, st.shopee_app_secret,
                                           st.config.get("shopee", {}))
            elif nome == "ml":
                validade = st.config.get("mercadolivre", {}).get("validade_horas", 24)
                fontes[nome] = FonteMercadoLivre(ARQUIVO_FILA_ML, banco, validade)
            else:
                log.warning("Fonte desconhecida no config: %s", nome)
        except FonteIndisponivel as e:
            # Só log: não é erro (ex.: chaves da Shopee ainda em aprovação)
            log.warning("Fonte %s pulada: %s", nome, e)
    return fontes


def criar_publicador_whatsapp(st: Settings, chat_id: str) -> PublicadorWhatsApp:
    cfg = st.config.get("whatsapp", {})
    return PublicadorWhatsApp(chat_id, st.whatsapp_bridge_url,
                              timeout=float(cfg.get("timeout_seg", 30)),
                              timeout_imagem=float(cfg.get("timeout_imagem_seg", 10)),
                              imagem_max_mb=float(cfg.get("imagem_max_mb", 5)),
                              pausa_min=float(cfg.get("pausa_min_seg", 20)),
                              pausa_max=float(cfg.get("pausa_max_seg", 40)))


def criar_publicador(nome: str, st: Settings, canal: bool):
    """Cria um publicador. Levanta ErroConfig se faltar algo no .env; None se o nome não existe."""
    if nome == "telegram":
        exigir(st.telegram_bot_token, "TELEGRAM_BOT_TOKEN")
        chat_id = (exigir(st.telegram_channel_id, "TELEGRAM_CHANNEL_ID") if canal
                   else exigir(st.telegram_admin_chat_id, "TELEGRAM_ADMIN_CHAT_ID"))
        pausa = float(st.config.get("pausa_entre_posts_seg", 5))
        return PublicadorTelegram(criar_cliente_telegram(st), chat_id, pausa_seg=pausa)
    if nome == "whatsapp":
        chat_id = (exigir_id_whatsapp(st.whatsapp_group_id, "WHATSAPP_GROUP_ID", "@g.us") if canal
                   else exigir_id_whatsapp(st.whatsapp_admin_id, "WHATSAPP_ADMIN_ID", "@s.whatsapp.net"))
        return criar_publicador_whatsapp(st, chat_id)
    log.warning("Publicador desconhecido no config: %s", nome)
    return None


def criar_publicadores(nomes: list[str], st: Settings, destino: str = "canal") -> tuple[list, list[str]]:
    """destino "canal": canal do Telegram e grupo do WhatsApp; "admin": seus destinos privados.

    Publicador com configuração faltando é pulado (os outros seguem).
    Retorna (publicadores, problemas). Só levanta ErroConfig se nenhum puder ser criado.
    """
    publicadores, problemas = [], []
    for nome in nomes:
        try:
            publicador = criar_publicador(nome, st, canal=destino == "canal")
        except ErroConfig as e:
            log.error("[%s] pulado: %s", nome, e)
            problemas.append(f"[{nome}] pulado: {e}")
            continue
        if publicador:
            publicadores.append(publicador)
    if not publicadores:
        detalhe = "; ".join(problemas) or "publicadores_ativos vazio"
        raise ErroConfig(f"Nenhum publicador pôde ser criado ({detalhe})")
    return publicadores, problemas


def slot_atual(st: Settings) -> str:
    """Horário configurado mais próximo da hora atual em São Paulo."""
    hora = datetime.now(st.fuso).hour
    return min(SLOTS, key=lambda s: abs(int(s) - hora))


# ---------- etapas do fluxo ----------

def buscar_candidatas(fontes: dict[str, Fonte], quantidade: int, problemas: list[str]) -> list[Oferta]:
    candidatas = []
    for nome, fonte in fontes.items():
        try:
            achadas = fonte.buscar(quantidade)
            log.info("Fonte %s: %d candidata(s)", nome, len(achadas))
            candidatas.extend(achadas)
        except Exception as e:
            log.exception("Fonte %s falhou", nome)
            problemas.append(f"fonte {nome} falhou: {e}")
    return candidatas


def revalidar(fonte: Fonte, oferta: Oferta, problemas: list[str]) -> Oferta | None:
    try:
        return fonte.revalidar(oferta)
    except Exception as e:
        log.exception("Revalidação de %s falhou", oferta.chave)
        problemas.append(f"revalidação de {oferta.chave} falhou: {e}")
        return None


def publicar_em_todos(oferta: Oferta, publicadores: list) -> tuple[dict[str, str | None], list[str]]:
    """Envia para cada publicador.

    Retorna ({nome: None se ok, ou mensagem de erro}, [nomes dos publicadores que caíram]).
    """
    resultados, indisponiveis = {}, []
    for publicador in publicadores:
        try:
            publicador.publicar(oferta)
            resultados[publicador.nome] = None
            log.info("[%s] OK: %s", publicador.nome, oferta.chave)
        except Exception as e:
            resultados[publicador.nome] = str(e) or type(e).__name__
            log.error("[%s] FALHOU: %s — %s", publicador.nome, oferta.chave, resultados[publicador.nome])
            if isinstance(e, PublicadorIndisponivel):
                indisponiveis.append(publicador.nome)
    return resultados, indisponiveis


def mostrar(oferta: Oferta, nomes_publicadores: list[str], numero: int) -> None:
    for nome in nomes_publicadores:
        formatar = FORMATADORES.get(nome)
        if not formatar:
            continue
        print(f"\n===== Post {numero} · {nome} · {oferta.chave} =====")
        print(f"[foto] {oferta.imagem_url or '(sem imagem: vai como texto)'}")
        print(formatar(oferta))
    print(flush=True)


# ---------- modos de execução ----------

def executar_slot(args, st: Settings) -> int:
    cfg = st.config
    slot = args.slot or slot_atual(st)
    quantidade = int(cfg.get("horarios", {}).get(slot, 0))
    nomes_fontes = [args.fonte] if args.fonte else cfg.get("fontes_padrao", [])
    nomes_publicadores = st.publicadores_ativos
    filtros_cfg = cfg.get("filtros", {})
    avisador = criar_avisador(st, ativo=not args.dry_run)
    problemas: list[str] = []

    log.info("Horário %s: meta de %d oferta(s), fontes %s%s", slot, quantidade,
             nomes_fontes, " (dry-run)" if args.dry_run else "")

    with Banco(ARQUIVO_BANCO, gravar=not args.dry_run) as banco:
        fontes = criar_fontes(nomes_fontes, st, banco)
        multiplicador = int(cfg.get("multiplicador_candidatos", 3))
        candidatas = buscar_candidatas(fontes, quantidade * multiplicador, problemas)
        recentes = banco.chaves_recentes(int(cfg.get("dias_sem_repetir", 7)))
        fila = filtros.selecionar(candidatas, filtros_cfg, recentes)
        log.info("%d candidata(s), %d aprovada(s) nos filtros", len(candidatas), len(fila))

        publicadores = []
        if not args.dry_run:
            publicadores, erros_config = criar_publicadores(nomes_publicadores, st, "canal")
            problemas.extend(erros_config)
        publicadas, ja_enviou = 0, False
        variedade = Counter()  # o que já saiu no horário, por palavra de busca e preferidas

        for oferta in fila:
            if publicadas >= quantidade:
                break
            motivo = filtros.motivo_variedade(oferta, variedade, filtros_cfg)
            if motivo:
                log.debug("Pulada %s: %s", oferta.chave, motivo)
                continue
            atual = revalidar(fontes[oferta.fonte], oferta, problemas)
            if atual is None:
                continue
            motivo = filtros.motivo_rejeicao(atual, filtros_cfg)
            if motivo:
                log.info("Pulada após revalidar %s: %s", atual.chave, motivo)
                continue

            if args.dry_run:
                publicadas += 1
                filtros.contar_publicada(oferta, variedade, filtros_cfg)
                mostrar(atual, nomes_publicadores, publicadas)
                continue

            if ja_enviou:
                # Espera a maior pausa entre os publicadores (o WhatsApp pede mais)
                time.sleep(max(p.pausa() for p in publicadores))
            ja_enviou = True
            resultados, indisponiveis = publicar_em_todos(atual, publicadores)
            sucesso = [nome for nome, erro in resultados.items() if erro is None]
            falhas = {nome: erro for nome, erro in resultados.items() if erro is not None}
            if sucesso:
                banco.registrar_publicacao(atual, slot, sucesso)
                publicadas += 1
                filtros.contar_publicada(oferta, variedade, filtros_cfg)
            for nome, erro in falhas.items():
                problemas.append(f"[{nome}] {atual.chave}: {erro}")
            if indisponiveis:
                # Destino caiu: pula no resto do horário (um aviso só; os outros seguem)
                publicadores = [p for p in publicadores if p.nome not in indisponiveis]
                for nome in indisponiveis:
                    log.warning("[%s] indisponível: pulado no resto do horário %s", nome, slot)
                    problemas.append(f"[{nome}] pulado no resto do horário")
                if not publicadores:
                    break

    if args.dry_run:
        log.info("Horário %s: %d oferta(s) seriam publicadas (dry-run; meta %d)", slot, publicadas, quantidade)
    else:
        log.info("Horário %s concluído: %d de %d publicada(s)", slot, publicadas, quantidade)
    if problemas:
        avisador.avisar(f"Horário {slot}: {len(problemas)} problema(s)\n- " + "\n- ".join(problemas[:10]))
    if publicadas == 0 and quantidade > 0 and cfg.get("avisar_slot_vazio", True):
        avisador.avisar(f"Horário {slot}: nenhuma oferta publicada.")
    return 0


def executar_teste(args, st: Settings) -> int:
    """Envia 1 oferta falsa aos destinos privados (ou ao canal/grupo com --canal). Não grava histórico."""
    oferta = FonteMock().buscar(1)[0]
    nomes = st.publicadores_ativos
    if args.dry_run:
        mostrar(oferta, nomes, 1)
        return 0
    destino = "canal" if args.canal else "admin"
    publicadores, erros_config = criar_publicadores(nomes, st, destino)
    for problema in erros_config:
        print(problema)
    if erros_config:
        criar_avisador(st, ativo=True).avisar("Teste: " + "; ".join(erros_config))
    resultados, _ = publicar_em_todos(oferta, publicadores)
    for nome, erro in resultados.items():
        alvo = NOMES_DESTINO.get((nome, destino), destino)
        if erro is None:
            print(f"[{nome}] Oferta de teste enviada para o {alvo}.")
        else:
            print(f"[{nome}] FALHOU ao enviar para o {alvo}: {erro}")
    tudo_ok = not erros_config and all(erro is None for erro in resultados.values())
    return 0 if tudo_ok else 1


def main(argv=None) -> int:
    # Terminal do Windows às vezes não aceita emoji sem isso
    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8", errors="replace")

    args = ler_argumentos(argv)
    configurar_logs(no_terminal=args.dry_run or sys.stderr.isatty())
    try:
        st = carregar()
    except ErroConfig as e:
        log.error("%s", e)
        return 2

    try:
        return executar_teste(args, st) if args.test else executar_slot(args, st)
    except ErroConfig as e:
        log.error("Configuração: %s", e)
        if not args.dry_run:
            criar_avisador(st, ativo=True).avisar(f"Configuração: {e}")
        return 2
    except Exception as e:
        log.exception("Erro inesperado")
        if not args.dry_run:
            criar_avisador(st, ativo=True).avisar(f"Erro inesperado: {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
