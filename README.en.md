# A-Share, Hong Kong, and US Market Monitor

English guide. [中文说明](README.md)

A local desktop monitor for A-shares, Hong Kong stocks, US stocks, and crypto. It tracks a watchlist, shows quotes, and sends a Telegram message when a rule you wrote is hit. Trading keys are entered on the APIs page and stay on this machine. A market with no interface waits and sends no order.

## What you need

Python 3.11 or newer, and Node.js, on Windows.

```bat
copy .env.example .env
copy config.example.yaml config.yaml
```

Put the Telegram values in `.env`. Do not paste the token into chat:

```
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
TELEGRAM_THREAD_ID=
TRADING_AUTO_ORDER=false
```

Leave `TELEGRAM_THREAD_ID` empty unless the chat is a forum topic.

## Open the app

The desktop shortcut **A股监测台** opens its own window. It does not open a browser tab.

The first time, if dependencies are missing, double-click `start.bat` in the project folder, then open the shortcut again.

## Add a symbol

On the dashboard, type a code or a name (`600519`, 茅台, `00700`, 腾讯, `AAPL`) and click Add.

- `600519` is stored as `600519.SS` (Shanghai).
- `000001` is stored as `000001.SZ` (Shenzhen).
- `00700` or `700` is stored as `00700.HK` (Hong Kong).
- US tickers stay as letters, for example `AAPL`.

Adding a symbol only shows its quote. It does not create an alert.

The first launch includes a sample A-share list, three Hong Kong names (Tencent, Alibaba, Xiaomi), and four US index cards: S&P 500, Nasdaq, Dow Jones, and the US Dollar Index.

## Holdings

Open **持仓**. Enter code, name, share count, and cost, then save. Saving the same code again replaces the share count and cost. Delete removes that position. This record does not change the cash balance.

## Alerts

Open **监控预警** and fill at least one of these on a symbol:

- Break below: alert when the price is at or under this level
- Break above: alert when the price is at or over this level
- Stop: alert when the price is at or under this level
- Percent move: alert when the daily move reaches this percent

If none of those fields is set, the symbol is quote-only and will not alert.

The same rule will not fire again until the cooldown ends. The default is 60 minutes. The default daily cap is 30 alerts. Both are in `config.yaml`: `alert.cooldown` is in seconds, and `alert.max_per_day` is the cap.

**Print only** shows the text and does not call Telegram. **Send to Telegram** and a real strategy hit use the same Bot API call. If the token is missing, the hit is stored in history and nothing is sent.

Example:

```
[信号] 600519 贵州茅台 现价1688.00 涨跌+1.23% | 规则:pct_change>=3 | 分组:A股 | 请手动确认 | 时间:2026-10-18 23:41:00
```

## Telegram

1. Create a bot with `@BotFather` and copy the token.
2. Send the bot one message. A personal chat id is available from `@userinfobot`. A group id is usually negative.
3. You can also enter them on the APIs page inside the app. They are stored in the local `.env`.
4. Use **Print only** to check the wording, then **Send to Telegram**.

## Quotes

A-share quotes come from Sina, then Tencent if Sina fails. Hong Kong stocks, US stocks, and the index cards come from Eastmoney. The refresh interval is `monitor.interval_active` in `config.yaml`, in seconds.
