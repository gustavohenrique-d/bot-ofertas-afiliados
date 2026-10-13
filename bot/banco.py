"""SQLite: histórico de publicações (evita repetir produto) e controle da fila manual."""
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

ESQUEMA = """
CREATE TABLE IF NOT EXISTS publicacoes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    fonte        TEXT NOT NULL,
    id_produto   TEXT NOT NULL,
    titulo       TEXT,
    preco        REAL,
    slot         TEXT,
    publicadores TEXT,
    publicada_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_publicacoes_data ON publicacoes (publicada_em);

CREATE TABLE IF NOT EXISTS fila_manual (
    fonte        TEXT NOT NULL,
    id_item      TEXT NOT NULL,
    vista_em     TEXT NOT NULL,
    publicada_em TEXT,
    PRIMARY KEY (fonte, id_item)
);
"""


def agora_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _texto(data: datetime) -> str:
    return data.astimezone(timezone.utc).isoformat(timespec="seconds")


def _data(texto: str | None) -> datetime | None:
    return datetime.fromisoformat(texto) if texto else None


class Banco:
    """Acesso ao SQLite. Com gravar=False (dry-run) nada é escrito no arquivo."""

    def __init__(self, caminho: Path, gravar: bool = True):
        self.gravar = gravar
        if gravar:
            caminho.parent.mkdir(parents=True, exist_ok=True)
            self.con = sqlite3.connect(caminho)
            self.con.executescript(ESQUEMA)
        elif caminho.exists():
            # Somente leitura: o próprio SQLite recusa qualquer escrita
            self.con = sqlite3.connect(caminho.resolve().as_uri() + "?mode=ro", uri=True)
        else:
            # Ainda não existe banco: usa um vazio em memória, sem criar arquivo
            self.con = sqlite3.connect(":memory:")
            self.con.executescript(ESQUEMA)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.fechar()

    def fechar(self) -> None:
        self.con.close()

    # ---------- histórico ----------

    def chaves_recentes(self, dias: int) -> set[str]:
        """Chaves "fonte:id" publicadas nos últimos `dias` dias."""
        limite = _texto(agora_utc() - timedelta(days=dias))
        linhas = self.con.execute(
            "SELECT fonte, id_produto FROM publicacoes WHERE publicada_em >= ?", (limite,)
        )
        return {f"{fonte}:{id_produto}" for fonte, id_produto in linhas}

    def registrar_publicacao(self, oferta, slot: str, publicadores: list[str]) -> None:
        if not self.gravar:
            return
        agora = _texto(agora_utc())
        with self.con:
            self.con.execute(
                "INSERT INTO publicacoes (fonte, id_produto, titulo, preco, slot, publicadores, publicada_em)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (oferta.fonte, oferta.id_produto, oferta.titulo, oferta.preco, slot,
                 ",".join(publicadores), agora),
            )
            # Se veio de uma fila manual, marca o item como publicado
            self.con.execute(
                "UPDATE fila_manual SET publicada_em = ?"
                " WHERE fonte = ? AND id_item = ? AND publicada_em IS NULL",
                (agora, oferta.fonte, oferta.id_produto),
            )

    # ---------- fila manual (Mercado Livre) ----------

    def situacao_fila(self, fonte: str, id_item: str) -> tuple[datetime | None, datetime | None]:
        """Retorna (vista_em, publicada_em) de um item da fila."""
        linha = self.con.execute(
            "SELECT vista_em, publicada_em FROM fila_manual WHERE fonte = ? AND id_item = ?",
            (fonte, id_item),
        ).fetchone()
        if not linha:
            return None, None
        return _data(linha[0]), _data(linha[1])

    def registrar_vista(self, fonte: str, id_item: str) -> datetime:
        """Marca quando o bot viu o item pela primeira vez. Retorna essa data."""
        vista, _ = self.situacao_fila(fonte, id_item)
        if vista:
            return vista
        agora = agora_utc()
        if self.gravar:
            with self.con:
                self.con.execute(
                    "INSERT OR IGNORE INTO fila_manual (fonte, id_item, vista_em) VALUES (?, ?, ?)",
                    (fonte, id_item, _texto(agora)),
                )
        return agora
