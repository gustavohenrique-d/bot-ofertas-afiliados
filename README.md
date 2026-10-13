# Bot de Ofertas de Afiliados

Bot em Python que busca ofertas de afiliados (Shopee e Mercado Livre), aplica filtros de curadoria e publica
as mesmas ofertas num **canal do Telegram** e num **grupo de WhatsApp**, em 4 horários por dia.

É código determinístico (sem IA) e leve: roda numa **VM Linux de 1 GB de RAM**, agendado pelo cron, usando só
`requests`, `python-dotenv` e SQLite. Nada de navegador, Selenium ou scraping.

## Regras de negócio

- **Só fontes oficiais.** Preço, link e cupom vêm da API oficial de afiliados ou de uma fila preenchida à mão.
  O bot nunca estima preço nem raspa páginas.
- **Cupom só se for oficial.** Precisa vir de um campo da API ou estar marcado `cupom_oficial = sim` na fila manual.
- **Revalidação de preço.** Logo antes de publicar, o preço é consultado de novo na API. Se piorou ou a oferta
  sumiu, ela é pulada.
- **Sem repetir produto.** O mesmo produto não volta antes de 7 dias (histórico no SQLite).
- **Volume controlado.** 4 horários (8h, 12h, 18h e 21h, fuso `America/Sao_Paulo`), com quantidade por horário
  configurável.
- **Erros nunca vão para o público.** Falhas geram um aviso curto no chat privado do administrador no Telegram.

## Arquitetura

```
main.py                 linha de comando e orquestração de um horário
config/
  settings.py           lê o .env (segredos) e o config.json (regras)
  config.example.json   modelo de configuração
bot/
  fontes/               de onde vêm as ofertas (todas devolvem o mesmo dataclass Oferta)
    base.py             Oferta + interface Fonte (buscar, revalidar)
    shopee.py           Shopee Affiliate Open API (GraphQL, assinatura SHA256)
    mercadolivre.py     fila manual em CSV (não existe API de afiliados do ML)
    amazon.py           interface reservada para a futura API da Amazon
    mock.py             3 ofertas falsas para testar sem chaves
  filtros.py            curadoria: desconto, comissão, preço, avaliação, vendas, bloqueios, variedade
  banco.py              SQLite: histórico de publicações e controle da fila manual
  formatadores/         texto do post para cada destino (Telegram em HTML, WhatsApp em *negrito*)
  publicadores/         envio para cada destino
    telegram.py         Bot API (sendPhoto com fallback para sendMessage, retry em 429/5xx)
    whatsapp.py         ponte HTTP local do Hermes Agent
  avisos.py             alertas de erro no chat privado
scripts/rodar_slot.sh   chamado pelo cron (com flock contra execução dupla)
tests/                  pytest
```

### Fluxo de um horário

1. **Busca** candidatas em todas as fontes ativas.
2. **Filtra:** remove produtos publicados nos últimos 7 dias e os que não passam nos filtros.
3. **Ordena:** fila manual primeiro (ela vence), depois ofertas com palavras preferidas, depois maior desconto.
4. **Variedade:** limita quantas ofertas da mesma palavra de busca e quantas "preferidas" saem por horário.
5. **Revalida** cada oferta na fonte e reaplica os filtros com o preço atualizado.
6. **Publica** em todos os destinos e grava no histórico se pelo menos um deu certo.

### Fontes

- **Shopee:** API oficial GraphQL (`productOfferV2` para buscar, `generateShortLink` para o link de afiliado).
  Autenticação por `Authorization: SHA256 Credential=..., Timestamp=..., Signature=sha256(AppID + Timestamp + corpo + Secret)`.
  Usa avaliação (`ratingStar`) e vendas (`sales`) nos filtros quando a API informa.
- **Mercado Livre:** não há API de afiliados, então a fonte é um CSV preenchido à mão com links já gerados no
  portal do ML. Como não dá para revalidar o preço, linhas com mais de 24h sem publicar são ignoradas.
- **Amazon:** só a interface, para quando a API for liberada.
- **Mock:** ofertas fixas para testar formatação e publicação sem nenhuma chave.

### Publicadores

- **Telegram:** foto + legenda em HTML. Se a foto falhar, envia só o texto. Em 429 respeita o `retry_after`;
  em 5xx tenta de novo.
- **WhatsApp:** pela ponte local do **Hermes Agent** (Nous Research), baseada em Baileys. A imagem é baixada
  para um arquivo temporário, enviada e apagada (mesmo em erro). Se a imagem falhar, vai só o texto. Erro de
  rede ou 503 (WhatsApp desconectado) **não** gera nova tentativa, para evitar post duplicado no grupo. Depois
  de um 503, o WhatsApp é pulado no resto do horário e o Telegram segue normal. A pausa entre posts é sorteada
  (padrão de 20 a 40 s).
- Um publicador com configuração faltando é pulado com aviso; o horário só para se nenhum puder ser criado.

## Stack

- Python 3.10+
- `requests`, `python-dotenv`, `tzdata`
- SQLite (biblioteca padrão)
- `pytest` para os testes
- Agendamento externo por cron; logs com rotação em `logs/`

## Como rodar

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt

cp .env.example .env                              # Windows: copy
cp config/config.example.json config/config.json  # Windows: copy

python main.py --fonte mock --dry-run --slot 12   # mostra os posts no terminal, sem chaves e sem enviar
```

Sem o `config/config.json`, o bot para com uma mensagem dizendo para copiar o arquivo de exemplo.

### Linha de comando

```
python main.py --slot 08                 publica as ofertas do horário (08, 12, 18 ou 21)
python main.py --dry-run                 mostra os posts no terminal; não envia e não grava nada
python main.py --test                    envia 1 oferta falsa aos destinos privados do administrador
python main.py --test --canal            envia 1 oferta falsa ao canal e ao grupo
python main.py --fonte mock|shopee|ml    usa só esta fonte
```

### Variáveis do `.env`

| Variável | O que é |
|---|---|
| `TELEGRAM_BOT_TOKEN` | token do bot (BotFather) |
| `TELEGRAM_CHANNEL_ID` | canal onde as ofertas são publicadas (o bot precisa ser admin) |
| `TELEGRAM_ADMIN_CHAT_ID` | chat privado que recebe os avisos de erro e o `--test` |
| `SHOPEE_APP_ID` / `SHOPEE_APP_SECRET` | chaves da Shopee Affiliate Open API |
| `WHATSAPP_GROUP_ID` | grupo de destino (termina em `@g.us`) |
| `WHATSAPP_ADMIN_ID` | contato que recebe o `--test` (termina em `@s.whatsapp.net`) |
| `WHATSAPP_BRIDGE_URL` | endereço da ponte do Hermes Agent (padrão `http://localhost:3000`) |
| `PUBLICADORES_ATIVOS` | ex.: `telegram,whatsapp`; substitui `publicadores_ativos` do `config.json` |

Sem as chaves da Shopee, a fonte é pulada com um aviso no log.

### Configuração (`config/config.json`)

Horários e quantidade por horário, fontes e publicadores padrão, dias sem repetir, pausas, e os filtros:
desconto mínimo, comissão mínima, faixa de preço, avaliação e vendas mínimas, palavras bloqueadas, palavras
preferidas e limites de variedade. Veja `config/config.example.json`.

### Fila do Mercado Livre

`dados/fila_mercadolivre.csv`, uma oferta por linha:

```
link_afiliado,titulo,preco,preco_original,imagem_url,cupom,cupom_oficial
https://exemplo.com/link-afiliado,Organizador de Gaveta,"39,90","69,90",https://exemplo.com/foto.jpg,,
```

O bot só lê a fila; linhas publicadas ou vencidas são ignoradas.

### Agendamento (cron, fuso de São Paulo)

```
0 8  * * * /caminho/do/projeto/scripts/rodar_slot.sh 08
0 12 * * * /caminho/do/projeto/scripts/rodar_slot.sh 12
0 18 * * * /caminho/do/projeto/scripts/rodar_slot.sh 18
0 21 * * * /caminho/do/projeto/scripts/rodar_slot.sh 21
```

O relógio do servidor precisa estar em `America/Sao_Paulo` (`sudo timedatectl set-timezone America/Sao_Paulo`).

## Testes

```bash
python -m pytest
```

Os testes cobrem filtros e variedade, conversão dos dados da Shopee, formatadores, fila do Mercado Livre,
publicador do WhatsApp (com uma ponte falsa), a escolha de publicadores e o aviso de `config.json` ausente.

## Direitos

© 2026 Gustavo Henrique. Todos os direitos reservados. O código está disponível para consulta; para usar ou adaptar, entre em contato.
