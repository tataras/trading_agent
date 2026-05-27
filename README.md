# Trading Agent AI

Agent handlowy uzywajacy Gemini API do decyzji BUY/SELL/HOLD oraz brokera
testowego do wykonywania zlecen. Projekt obsluguje:

- Binance jako publiczne zrodlo danych krypto
- EXANTE HTTP API Demo dla danych rynkowych i zlecen demo
- Alpaca Paper Trading dla zlecen testowych
- OANDA Practice dla danych forex i zlecen demo
- lokalny tryb demo/mock bez laczenia z brokerem

## Struktura

```text
trading_agent/
|-- main.py                    # Glowna petla agenta
|-- config.py                  # Konfiguracja i loader .env
|-- requirements.txt
|-- .env.example
|-- data/
|   `-- collector.py           # Dane OHLCV, RSI, SMA, trend
|-- agent/
|   |-- prompt_builder.py      # Prompt dla modelu
|   |-- gemini_client.py       # Komunikacja z Gemini API
|   `-- response_parser.py     # Parsowanie JSON do TradingDecision
|-- risk/
|   `-- manager.py             # Limity ryzyka i stop-loss
`-- broker/
    |-- alpaca_broker.py       # Alpaca Paper Trading
    |-- exante_broker.py       # EXANTE HTTP API Demo
    |-- oanda_broker.py        # OANDA Practice forex
    `-- mock_broker.py         # Lokalny mock broker
```

## Szybki start

1. Zainstaluj zaleznosci:

```bash
pip install -r requirements.txt
```

2. Skopiuj konfiguracje:

```bash
cp .env.example .env
```

3. Uzupelnij `.env` i uruchom:

```bash
python main.py
```

## Konfiguracja EXANTE Demo

Domyslna konfiguracja `.env.example` jest ustawiona pod EXANTE HTTP API Demo.
Utworz klucze demo w Client Area -> Settings -> API Management, a potem
uzupelnij:

```env
SYMBOL=AAPL.NASDAQ
TIMEFRAME=1m
MARKET_DATA_SOURCE=exante

BROKER_MODE=exante_demo
EXANTE_APPLICATION_ID=...
EXANTE_ACCESS_KEY=...
EXANTE_ACCOUNT_ID=...
EXANTE_TRADE_BASE_URL=https://api-demo.exante.eu/trade
EXANTE_MD_BASE_URL=https://api-demo.exante.eu/md
EXANTE_SYMBOL=AAPL.NASDAQ
EXANTE_SUMMARY_CURRENCY=EUR
EXANTE_ORDER_DURATION=day
EXANTE_MIN_ORDER_QUANTITY=1
```

Agent pobiera swiece z EXANTE `md/3.0/ohlc/{symbol}/{duration}` i sklada
zlecenia market przez `trade/3.0/orders`. BUY otwiera long, SELL zamyka long
przeciwna transakcja market.

## Konfiguracja OANDA Practice

Przyklad startowy dla forex na koncie demo OANDA:

```env
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.5-flash

SYMBOL=EUR/USD
TIMEFRAME=1h
MARKET_DATA_SOURCE=oanda

BROKER_MODE=oanda_demo
OANDA_ACCOUNT_ID=...
OANDA_ACCESS_TOKEN=...
OANDA_BASE_URL=https://api-fxpractice.oanda.com
OANDA_INSTRUMENT=EUR_USD
OANDA_MIN_ORDER_UNITS=1
```

Agent pobiera swiece z OANDA `instruments/{instrument}/candles`, a zlecenia
sklada przez konto practice. BUY otwiera pozycje long, SELL zamyka long w danym
instrumencie.

## Konfiguracja Alpaca Paper

```env
SYMBOL=BTCUSDT
MARKET_DATA_SOURCE=binance
BINANCE_BASE_URL=https://api.binance.com

BROKER_MODE=alpaca_paper
ALPACA_API_KEY=...
ALPACA_SECRET_KEY=...
ALPACA_BASE_URL=https://paper-api.alpaca.markets
ALPACA_SYMBOL=BTC/USD
```

## Najwazniejsze parametry

| Parametr | Domyslnie | Opis |
| --- | --- | --- |
| `SYMBOL` | `AAPL.NASDAQ` | Symbol instrumentu, np. `AAPL.NASDAQ`, `BTCUSDT` albo `EUR/USD` |
| `MARKET_DATA_SOURCE` | `exante` | `exante`, `binance`, `oanda` albo `demo` |
| `BROKER_MODE` | `exante_demo` | `exante_demo`, `alpaca_paper`, `oanda_demo` albo `mock` |
| `EXANTE_SYMBOL` | `AAPL.NASDAQ` | Symbol EXANTE, np. `AAPL.NASDAQ`; puste = z `SYMBOL` |
| `OANDA_INSTRUMENT` | auto | Instrument OANDA, np. `EUR_USD`; puste = z `SYMBOL` |
| `TIMEFRAME` | `1m` | Interwal swiec: `1m`, `5m`, `15m`, `1h`, `4h`, `1d` |
| `MAX_POSITION_PCT` | `0.05` | Max 5% kapitalu na pozycje |
| `STOP_LOSS_PCT` | `0.02` | Stop-loss przy stracie 2% |
| `MAX_DAILY_LOSS_PCT` | `0.06` | Blokada przy dziennej stracie 6% |

## Tryb mock/demo

Aby uzyc lokalnie generowanych danych i lokalnego paper tradingu:

```env
MARKET_DATA_SOURCE=demo
BROKER_MODE=mock
```

## Ostrzezenie

To jest projekt edukacyjny. Nawet paper trading powinien byc monitorowany, a
przed uzyciem prawdziwego kapitalu potrzebne sa testy, backtesting i audyt
warstwy ryzyka.
