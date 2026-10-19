# A股行情监测台

基于 [kedoupi/portfolio-monitor](https://github.com/kedoupi/portfolio-monitor)（MIT）改的本地看板。管理自选和告警，用 Telegram 提醒。信号文案带「请手动确认」。

自动下单是一个开关，**默认关闭**。关闭时只提醒，下单由你自己完成。打开开关也不会点击交易软件，不会保存交易密码。当前没有接入券商，所以即使打开也只记录意向，不会提交委托。

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

打开「监控预警」，点「添加」。代码可以写 `600519`，会按规则变成 `600519.SS`（沪）或 `000001.SZ`（深）。

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

## 自动下单开关

在「监控预警」页。默认关。

- 关闭：只发提醒，请你手动确认后自己下单。
- 打开：仍然不连接券商，不保存密码，不去点交易客户端。记录一条「未提交」的意向，方便以后接官方接口。

## 行情

A 股走新浪行情，失败时改用腾讯行情，一次拉取多只。美股仍走原来的 Yahoo 路径（需要安装 `curl_cffi`）。刷新间隔见 `config.yaml` 的 `monitor.interval_active`。
