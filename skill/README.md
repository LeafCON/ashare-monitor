# Stock Portfolio Skill

A skill for managing stock portfolio, cash accounts, and investment tracking through the portfolio-monitor system.

## Installation

```bash
# Clone to OpenClaw skills directory
cd ~/.openclaw/skills/
git clone <repo-url> stock-portfolio
```

## Configuration

Add to your agent's `config.yaml`:

```yaml
skills:
  - name: stock-portfolio
    config:
      api_base_url: "http://localhost:18890"
      default_currencies:
        - USD
        - CNY
```

## Tools

### 1. Get Portfolio Summary

Get complete portfolio overview including stocks and cash.

**CLI:**
```bash
portfolio summary
```

**API:**
```bash
curl http://localhost:18890/api/dashboard
```

### 2. Get Holdings

Get current stock holdings with P&L.

**CLI:**
```bash
portfolio holdings
```

**API:**
```bash
curl http://localhost:18890/api/portfolio
```

### 3. Get Cash Balance

Get cash accounts by currency.

**CLI:**
```bash
portfolio cash
```

**API:**
```bash
curl http://localhost:18890/api/cash
```

### 4. Add Transaction

Record a buy/sell transaction.

**CLI:**
```bash
portfolio buy GOOGL 100 303.00 --note "建仓"
portfolio sell TME 1000 15.50 --note "止盈"
```

**API:**
```bash
curl -X POST http://localhost:18890/api/transactions \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "GOOGL",
    "name": "谷歌",
    "action": "buy",
    "price": 303.00,
    "shares": 100,
    "amount": 30300,
    "fee": 0,
    "date": "2026-02-19T10:00:00",
    "notes": "建仓"
  }'
```

### 5. Update Cash

Adjust cash balance (deposit/withdraw).

**CLI:**
```bash
portfolio cash-add USD 50000 --note "入金"
portfolio cash-sub CNY 10000 --note "出金"
```

**API:**
```bash
curl -X POST http://localhost:18890/api/cash \
  -H "Content-Type: application/json" \
  -d '{
    "currency": "USD",
    "amount": 50000,
    "type": "deposit",
    "note": "入金"
  }'
```

### 6. Get Watchlist

Get monitored stocks with alerts.

**CLI:**
```bash
portfolio watchlist
```

**API:**
```bash
curl http://localhost:18890/api/watchlist
```

### 7. Add to Watchlist

Add a stock to watchlist with price alerts.

**CLI:**
```bash
portfolio watch-add MSFT "微软" --buy 395 --sell 450 --stop 350
```

**API:**
```bash
curl -X POST http://localhost:18890/api/watchlist \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "MSFT",
    "name": "微软",
    "target_buy": 395,
    "target_sell": 450,
    "stop_loss": 350
  }'
```

### 8. Update Watchlist Item

Modify price targets for an existing watchlist item.

**CLI:**
```bash
# Update buy/sell/stop targets
portfolio watch-update MSFT --buy 380 --sell 460 --stop 340

# Clear a specific target
portfolio watch-update MSFT --clear-buy

# Disable/enable monitoring
portfolio watch-update MSFT --disable
portfolio watch-update MSFT --enable
```

**Options:**
| Flag | Description |
|------|-------------|
| `--buy <price>` | Set buy target |
| `--sell <price>` | Set sell target |
| `--stop <price>` | Set stop loss |
| `--clear-buy` | Clear buy target |
| `--clear-sell` | Clear sell target |
| `--clear-stop` | Clear stop loss |
| `--name <name>` | Update display name |
| `--enable` | Enable monitoring |
| `--disable` | Disable monitoring |

**API:**
```bash
curl -X PUT http://localhost:18890/api/watchlist/MSFT \
  -H "Content-Type: application/json" \
  -d '{
    "target_buy": 380,
    "target_sell": 460,
    "stop_loss": 340
  }'
```

> Note: Use `null` in API to clear a field: `{"target_buy": null}`

### 9. Delete from Watchlist

Remove a stock from the watchlist.

**CLI:**
```bash
portfolio watch-delete MSFT
```

**API (by symbol):**
```bash
curl -X DELETE http://localhost:18890/api/watchlist/symbol/MSFT
```

**API (by ID):**
```bash
curl -X DELETE http://localhost:18890/api/watchlist/6
```

### 10. Get Alerts History

Get triggered alerts history.

**CLI:**
```bash
portfolio alerts
```

**API:**
```bash
curl http://localhost:18890/api/alerts/history
```

## Usage Examples

### Daily Portfolio Check

```bash
# Get complete overview
portfolio summary

# Check specific holdings
portfolio holdings | grep GOOGL

# Check cash position
portfolio cash
```

### Record New Trade

```bash
# Buy 50 shares of MSFT at $400
portfolio buy MSFT 50 400.00 --note "突破建仓"

# System will:
# 1. Record the transaction
# 2. Update holdings (avg cost calculation)
# 3. Deduct $20,000 from USD cash
```

### Manage Price Alerts

```bash
# Add monitoring for NVDA
portfolio watch-add NVDA "英伟达" --buy 180 --stop 150

# Monitor TME for exit
portfolio watch-add TME "腾讯音乐" --sell 18 --stop 12

# Update NVDA targets
portfolio watch-update NVDA --buy 175 --stop 145

# Clear stop loss
portfolio watch-update NVDA --clear-stop

# Remove NVDA from watchlist
portfolio watch-delete NVDA
```

## Integration with Agent

### Quick Status Check

```python
# In agent code
portfolio = tool("stock-portfolio/summary")
holdings = portfolio["holdings"]
cash = portfolio["cash_accounts"]

print(f"总资产: ${portfolio['total_assets_usd']:,.2f}")
print(f"股票: ${portfolio['stock_value_usd']:,.2f}")
print(f"现金: ${cash['USD']:,.2f} + ¥{cash['CNY']:,.2f}")
```

### Before Making Trade Decision

```python
# Check current position
current = tool("stock-portfolio/holdings")
googl_position = next(h for h in current if h["symbol"] == "GOOGL")

print(f"GOOGL持仓: {googl_position['shares']}股 @ ${googl_position['avg_cost']:.2f}")
print(f"当前盈亏: {googl_position['pnl_pct']:.1f}%")

# Check cash
cash = tool("stock-portfolio/cash")
print(f"可用美元: ${cash['USD']:,.2f}")
```

### After Executing Trade

```python
# Record the transaction
tool("stock-portfolio/transaction", {
    "symbol": "MSFT",
    "action": "buy",
    "price": 400.00,
    "shares": 50,
    "note": "站稳400突破"
})

# Verify update
updated = tool("stock-portfolio/summary")
print(f"更新后总资产: ${updated['total_assets_usd']:,.2f}")
```

## Data Model

### Holdings
```json
{
  "symbol": "GOOGL",
  "name": "谷歌",
  "shares": 115.77,
  "avg_cost": 302.32,
  "current_price": 303.33,
  "market_value": 35116.97,
  "unrealized_pnl": 117.0,
  "pnl_pct": 0.33
}
```

### Cash Account
```json
{
  "currency": "USD",
  "balance": 394635.00,
  "usd_equivalent": 394635.00
}
```

### Transaction
```json
{
  "id": "xxx",
  "date": "2026-02-19T10:00:00",
  "symbol": "GOOGL",
  "action": "buy",
  "price": 303.00,
  "shares": 33.00,
  "amount": 9999.00,
  "fee": 0,
  "notes": "建仓"
}
```

## Best Practices

1. **Always record trades immediately** - Don't wait, record while memory is fresh
2. **Use notes field** - Record reasoning for future review
3. **Check cash before buying** - Ensure sufficient funds
4. **Set alerts for key levels** - Don't miss entry/exit points
5. **Review weekly** - Check overall allocation and rebalance if needed

## Troubleshooting

### Service not running
```bash
cd ~/Coding/portfolio-monitor
bash run.sh
```

### API connection error
- Check if service is running: `curl http://localhost:18890/api/health`
- Verify port 18890 is not occupied

### Data inconsistency
- Check transaction history: `portfolio transactions`
- Verify cash balance matches: `portfolio cash`
- Recalculate if needed by deleting and re-adding transactions

## License

MIT
