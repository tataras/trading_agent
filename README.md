# Trading Agent AI

Agent handlowy uzywajacy Gemini API do decyzji BUY/SELL/HOLD oraz Alpaca Paper
Trading do wykonywania zlecen testowych. Dane rynkowe sa pobierane z publicznego
API Binance.

## Struktura

```text
trading_agent/
├── main.py                    # Glowna petla agenta
├── config.py                  # Konfiguracja i loader .env
├── requirements.txt
├── .env.example
├── data/
│   └── collector.py           # Dane OHLCV, RSI, SMA, trend
├── agent/
│   ├── prompt_builder.py      # Prompt dla modelu
│   ├── gemini_client.py       # Komunikacja z Gemini API
│   └── response_parser.py     # Parsowanie JSON do TradingDecision
├── risk/
│   └── manager.py             # Limity ryzyka i stop-loss
└── broker/
    ├── alpaca_broker.py       # Alpaca Paper Trading
    └── mock_broker.py         # Lokalny mock broker
```

## Szybki Start

1. Zainstaluj zaleznosci:

```bash
pip install -r requirements.txt
```

2. Skopiuj konfiguracje:

```bash
cp .env.example .env
```

3. Uzupelnij `.env`:

```env
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.5-flash

BROKER_MODE=alpaca_paper
ALPACA_API_KEY=...
ALPACA_SECRET_KEY=...
ALPACA_BASE_URL=https://paper-api.alpaca.markets
ALPACA_SYMBOL=BTC/USD
```

4. Uruchom:

```bash
python main.py
```

## Przeplyw Cyklu

```text
Binance API
  -> data/collector.py
  -> agent/prompt_builder.py
  -> agent/gemini_client.py
  -> agent/response_parser.py
  -> risk/manager.py
  -> broker/alpaca_broker.py
```

## Najwazniejsze Parametry

| Parametr | Domyslnie | Opis |
| --- | --- | --- |
| `symbol` | `BTCUSDT` | Symbol dla danych Binance |
| `alpaca_symbol` | auto / `BTC/USD` | Symbol dla Alpaca |
| `timeframe` | `1h` | Interwal swiec |
| `interval_seconds` | `60` | Czas miedzy cyklami |
| `max_position_pct` | `0.05` | Max 5% kapitalu na pozycje |
| `stop_loss_pct` | `0.02` | Stop-loss przy stracie 2% |
| `max_daily_loss_pct` | `0.06` | Blokada przy dziennej stracie 6% |
| `broker_mode` | `alpaca_paper` | `alpaca_paper` albo `mock` |
| `gemini_model` | `gemini-2.5-flash` | Model Gemini |

## Tryb Mock

Aby wrocic do lokalnego paper tradingu bez Alpaca:

```env
BROKER_MODE=mock
```

## Ostrzezenie

To jest projekt edukacyjny. Nawet paper trading powinien byc monitorowany,
a przed uzyciem prawdziwego kapitalu potrzebne sa testy, backtesting i audyt
warstwy ryzyka.
