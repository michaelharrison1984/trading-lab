# Trading Strategy Lab v5

Self-hosted Docker/Portainer strategy research, backtesting, paper trading and Telegram alerting for US/UK tickers.

## v5 highlights
- Strategy Library with seeded long, short and both-direction templates.
- Plain-English guided editor; RSI shows oversold controls for BUY and overbought controls for SHORT.
- Templates: SID, Trend SID, RSI Reversal, Moving Average Trend, MACD Momentum, Trend Pullback, 20/50-Day Breakouts, RSI+MACD and Counter-Trend Extreme.
- Safe strategy import/translation: paste a strategy description or supported Pine Script snippet. The Lab interprets common RSI/MA/MACD/pullback/breakout ideas but never executes pasted code.
- Backtester supports LONG, SHORT and BOTH in the same strategy.
- Strategy tuner, paper trading, ticker search, daily scanner and Telegram alerts retained.

## Upgrade from v4
Keep the existing `lab_data` volume. Replace the application files, rebuild the image, then redeploy/recreate both containers. v5 adds new strategy templates without deleting existing strategies/trades/settings.

## Docker Compose
```bash
docker compose up -d --build
```
Open `http://YOUR-SERVER-IP:8509`.

## Portainer
Build the image from this folder on the Docker host, then deploy `portainer-stack.yml`. Keep the existing `lab_data` named volume if upgrading.

## Telegram
Set in `.env` or Portainer environment:
```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

## Important
This is a research/paper-trading tool, not an execution engine or investment recommendation. Imported scripts are only best-effort translated; always review the plain-English interpretation before saving or testing.
