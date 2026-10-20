# A股 / 港股 / 美股行情监测台

[English](README.en.md)

本地看板，覆盖 A 股、港股、美股和加密货币。管理自选、持仓和告警，用 Telegram 提醒。交易接口在软件里的「接口」页填写，密钥只留在本机。某个市场还没配接口时，那一路等待，不发单。

## 安装

需要本机已有 Python 3.11+ 和 Node.js。

```bat
copy .env.example .env
copy config.example.yaml config.yaml
```

`.env` 里填写 Telegram，不要把 token 发到聊天里：

```
TELEGRAM_BOT_TOKEN=你的机器人 token
TELEGRAM_CHAT_ID=你的 chat id
ALERT_DRY_RUN=true
TRADING_AUTO_ORDER=false
```

`ALERT_DRY_RUN=true` 时，后台触发的告警只打印在控制台。看板上的「真发 Telegram」会真的调用 Bot API，用来单独测试。

## 打开程序

桌面快捷方式 **A股监测台** 会打开自己的窗口，不会跳到浏览器。

第一次若提示缺少依赖，在项目目录双击 `start.bat` 安装后再打开。

## 加自选

打开「监控预警」，点「添加」。也可以在看板搜索框输入代码或名称。`600519` 会变成 `600519.SS`（沪），`000001` 变成 `000001.SZ`（深），`00700` 或 `700` 变成 `00700.HK`（港股）。美股直接写代码，例如 `AAPL`。

可以填：

- 跌破价：现价小于等于该价格
- 突破价：现价大于等于该价格
- 涨跌幅阈值：留空则用 `config.yaml` 里的 `monitor.change_alert_pct`（默认 3%）

同一条规则有冷却时间，默认 60 分钟。全天触发次数默认不超过 30 条。这两项在 `config.yaml` 的 `alert.cooldown`（秒）和 `alert.max_per_day`。

首次启动会放入 9 只 A 股/ETF：贵州茅台、五粮液、中国平安、招商银行、平安银行、宁德时代、比亚迪、紫金矿业、沪深300ETF。

## Telegram

1. 在 Telegram 找 `@BotFather`，创建机器人，拿到 token。
2. 给机器人发一条消息。个人 chat id 可从 `@userinfobot` 查看；群 id 一般是负数。
3. 写入 `.env` 后重启 `start.bat`。
4. 在「监控预警」先点 **只打印**，确认文案。再点 **真发 Telegram**。只有后者会请求 Telegram。

告警例子：

```
[信号] 600519 贵州茅台 现价1688.00 涨跌+1.23% | 规则:pct_change>=3 | 分组:A股 | 请手动确认 | 时间:2026-10-18 23:41:00
```

## 交易接口

在「接口」页填写 Telegram、加密货币和股票券商。密钥写入本机 `.env`，页面只显示末四位。没填的市场保持等待。填好之后，通过闸门的决策会按该市场的接口发单。软件不会点击交易客户端，也不会保存交易软件的登录密码。

## 行情

A 股走新浪行情，失败时改用腾讯行情。港股和美股指数、美股个股走东方财富。刷新间隔见 `config.yaml` 的 `monitor.interval_active`。
