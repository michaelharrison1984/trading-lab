# Trading Strategy Lab — Docker/Portainer

## Features
- Streamlit dashboard at `http://YOUR-SERVER-IP:8509`
- SID, trend-filtered SID, and Trend-Pullback long-only daily signals
- Scheduled scanner Monday–Friday 22:30 UTC; manual scan button
- Telegram alerts with date, last close, indicative stop and 2R target; deduplicated per symbol/strategy/day
- Backtest one symbol/strategy at a time, next-open entry, stops, targets, maximum hold, fees and slippage; export trades
- Manual paper-trading journal and persistent SQLite storage
- Configurable US and UK watchlist; London tickers use `.L`

## Install — Docker Compose
1. Unzip this project on your Docker host.
2. In its folder: `cp .env.example .env`.
3. Create a Telegram bot by chatting to `@BotFather` in Telegram and copying its token.
4. Send your bot a message; open `https://api.telegram.org/bot<TOKEN>/getUpdates` privately and find `message.chat.id`. Keep the token secret.
5. Put `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`.
6. Run `docker compose up -d --build`.
7. Open `http://YOUR-SERVER-IP:8509`, select Settings, and test Telegram.
8. Review the watchlist and use Scan now. Scheduled scans run on weekdays at 22:30 UTC.

## Portainer
Portainer stacks using the Web editor usually cannot build an image from a multi-file project unless the files are already on the host and a suitable build context is configured. The reliable method is to build locally first:

```bash
cd trading-strategy-lab
docker build -t trading-strategy-lab:local .
```

Then paste the contents of `portainer-stack.yml` into **Stacks → Add stack → Web editor**. Replace both Telegram placeholders using Portainer's environment variables (`TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`) before deploying. The stack uses the prebuilt local image and a named SQLite volume. When using a multi-node Swarm, ensure the image is available on the deployment node and the volume stays attached to the same node.

## Strategy definitions (transparent approximations, not a licensed proprietary SID implementation)
- **SID:** RSI(14) was below 30 within previous 8 bars; previous RSI <= 35; RSI and MACD histogram both improve. Exit at RSI >= 50, 2R target, stop or time limit.
- **Trend-filtered SID:** SID conditions plus close > MA50 > MA200.
- **Trend-Pullback:** close > MA50 > MA200; prior RSI 35–45, RSI improving, close above previous high, MACD histogram improving.
- Stops use the lower of the previous five-day low and 1.5 ATR below signal close. Targets use 2R. These rules are configurable only through the source code in v1; the UI lets you adjust risk, costs and holding period.

## Important limitations
- Signals are generated on completed daily bars; signals on a US holiday may reflect an older bar. Verify the date.
- Data downloads depend on Yahoo Finance availability and may be delayed, incomplete, or revised.
- Historical results assume fills at next open with a fixed cost/slippage assumption. Gaps can produce losses beyond stops; stop/target execution is approximate.
- Single-symbol backtests use one position at a time, no shorting or leverage. Open positions are marked to market at the end of the sample.
- Backtests do not correct for survivorship bias, FX, dividends as cash flows, taxes, borrow costs, market impact, or multiple simultaneous portfolio positions. Adjusted OHLC may include dividend adjustments; interpret results accordingly.
- Paper trades are manually entered and manually exited; **not** automatically filled by the scanner. Paper journal does not calculate FX conversion or automatically mark open positions to market.
- This is a prototype, not investment advice, and does not establish a 2–3% monthly edge.
- No login is built in. **Do not expose port 8509 publicly**; use a VPN or authenticated reverse proxy.

## Maintenance
- `docker compose logs -f scanner` shows scan activity/errors.
- `docker compose logs -f trading-lab` shows UI errors.
- Back up the Docker volume `lab_data` regularly.
- Restart after changing environment variables: `docker compose up -d --force-recreate`.

## v2 Strategy Lab upgrade
The dashboard now includes **Strategy Manager** and **Optimiser** pages.

- SID, Trend-filtered SID and Trend-Pullback are protected built-in templates.
- Enable/disable any strategy for the scheduled scanner.
- Edit parameters and entry rules, then save them as a new custom strategy.
- Custom strategies can be overwritten or deleted from the UI.
- Backtesting can compare multiple saved strategies on the same ticker/history.
- The optimiser grid-searches up to 200 parameter combinations and ranks results by Sharpe then CAGR.
- Saved custom strategies live in the existing `/data/lab.db` volume, so they survive container recreation.

### Updating an existing installation
Keep the existing `lab_data` Docker volume so your settings, alerts and paper trades are retained. Replace the application files/image with v2 and recreate both `trading-lab` and `scanner`. On first start, the database schema is upgraded automatically.

The rule builder currently supports price/OHLCV, RSI, MACD histogram, moving averages, ATR, previous high, 20-day average volume and SID-armed state. All configured entry rules use AND logic. This is intentionally constrained rather than allowing arbitrary Python expressions.
