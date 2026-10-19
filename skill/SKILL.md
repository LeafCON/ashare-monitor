# stock-portfolio skill

通过 CLI 与 portfolio-monitor 服务交互，管理股票持仓、现金账户、交易记录、告警，以及查询完整市场数据。

## 安装

> 前提：portfolio-monitor 服务已运行（见根目录 README 的 Docker 部署）

```bash
cp -rp skill/ ~/.openclaw/skills/stock-portfolio/
chmod +x ~/.openclaw/skills/stock-portfolio/portfolio
```

## 配置

默认连接 `http://localhost:8802`，可通过环境变量覆盖：

```bash
export PORTFOLIO_API_URL="http://your-server:8802"
```

## 命令全览

### 持仓管理

| 命令 | 说明 |
|------|------|
| `portfolio summary` | 资产总览（持仓 + 现金） |
| `portfolio holdings` | 当前持仓及盈亏 |
| `portfolio cash` | 现金账户余额 |
| `portfolio buy SYMBOL SHARES PRICE [note]` | 记录买入 |
| `portfolio sell SYMBOL SHARES PRICE [note]` | 记录卖出 |
| `portfolio transactions` | 交易历史 |

### 监控预警

| 命令 | 说明 |
|------|------|
| `portfolio watch` | 监控列表（含分批建仓计划） |
| `portfolio watch-add SYMBOL [name] [--buy p] [--sell p] [--stop p]` | 添加监控 |
| `portfolio watch-update SYMBOL [--buy p] [--sell p] [--stop p]` | 修改档位 |
| `portfolio watch-delete SYMBOL` | 删除监控 |
| `portfolio alerts` | 告警历史 |

### 市场数据（基础）

| 命令 | 说明 |
|------|------|
| `portfolio price SYMBOL` | 实时行情（美股 + A股，如 510300.SS） |
| `portfolio ratios SYMBOL` | 估值指标（PE/PB/EPS/ROE/股息率） |
| `portfolio income SYMBOL [quarterly\|annual] [limit]` | 损益表 |
| `portfolio estimates SYMBOL` | 分析师预期 & 目标价 |
| `portfolio news SYMBOL [limit]` | 最新新闻 |

### 市场数据（扩展）

| 命令 | 说明 |
|------|------|
| `portfolio balance SYMBOL [quarterly\|annual] [limit]` | 资产负债表 |
| `portfolio cashflow SYMBOL [quarterly\|annual] [limit]` | 现金流量表 |
| `portfolio company SYMBOL` | 公司基本信息（行业/员工/简介） |
| `portfolio insiders SYMBOL [limit]` | 内幕交易记录 |
| `portfolio segments SYMBOL` | 营收拆分（按产品/地区） |
| `portfolio crypto SYMBOL` | 加密货币价格（BTC-USD/ETH-USD） |
| `portfolio prices SYMBOL [start] [end] [interval]` | 历史 OHLCV 数据 |

### 宏观与量化

| 命令 | 说明 |
|------|------|
| `portfolio macro` | 宏观指标（VIX / 美债10年 / DXY / 标普 / 纳指） |
| `portfolio quant SYMBOL` | 单支量化信号评分 |
| `portfolio quant-all` | 全部持仓量化信号 |
| `portfolio earnings` | 财报日历（未来30天） |
| `portfolio earnings-recent` | 最近已发布财报 |
| `portfolio snapshot` | 历史资产快照 |

## 示例

```bash
# 持仓 & 资产
portfolio holdings
portfolio summary
portfolio cash

# 市场数据
portfolio price TME
portfolio ratios BABA
portfolio income GOOGL quarterly 4
portfolio estimates NVDA
portfolio news BABA 5

# 深度分析
portfolio balance BABA quarterly
portfolio cashflow AAPL annual 3
portfolio company BABA
portfolio insiders TSLA 10
portfolio crypto BTC-USD

# 宏观 & 量化
portfolio macro
portfolio quant-all
portfolio earnings

# 交易
portfolio buy TME 500 15.50 "加仓"
portfolio sell BABA 50 200.00 "止盈"
```

## 详细文档

见 `README.md`。
