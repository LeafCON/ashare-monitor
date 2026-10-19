# 现金账户功能说明

## 功能概述

股票监控系统支持多币种现金账户管理，自动与交易记录联动，正确处理多币种总资产计算。

## 支持的币种

- **USD** - 美元现金
- **CNY** - 人民币现金

## 当前余额

- 美元现金：$394,635
- 人民币现金：¥109,298

## API 端点

### 查询现金余额
```
GET /api/cash          → 所有现金账户
GET /api/cash/USD      → 美元账户
GET /api/cash/CNY      → 人民币账户
```

### 调整现金余额
```
POST /api/cash/adjust
Content-Type: application/json

{
  "currency": "USD",  // 或 "CNY"
  "amount": 1000,     // 正数存入，负数取出
  "notes": "备注"
}
```

### 初始化现金账户
```
POST /api/cash/init
```

## 交易联动

- **买入股票**：自动扣减对应币种现金（金额 + 手续费）
- **卖出股票**：自动增加对应币种现金（金额 - 手续费）
- **余额不足**：买入时余额不足会返回 400 错误
- 币种根据股票代码自动判断：
  - A股（.SS/.SZ/.BJ 结尾）→ CNY
  - 其他 → USD

## Dashboard 总资产

总资产按 USD 等值计算，汇率 USD/CNY = 7.2：

```
总资产(USD) = 美股市值 + 美元现金 + (A股市值 / 7.2) + (人民币现金 / 7.2)
```

API 响应 (`/api/dashboard`) 中的 `total_assets` 包含：
- `total_assets_usd` — 总资产 USD 等值
- `stock_value_usd` — 美股市值
- `stock_value_cny` — A股市值（人民币）
- `cash_usd` — 美元现金
- `cash_cny` — 人民币现金
- `usd_to_cny` — 使用的汇率

## Dashboard 资产配置饼图

四个板块（USD等值）：
1. 美股（绿色）
2. A股（青色）
3. 美元现金（蓝色）
4. 人民币现金（紫色）

## 前端页面

### 看板 Tab
- 顶部四张摘要卡片：总资产、美元现金、人民币现金、美股市值
- 资产配置饼图（4个板块）
- 现金账户余额

### 现金账户 Tab
- 各币种余额卡片
- 存入/取出现金表单
- 账户明细表格
- 资产汇总（分币种显示原始金额 + USD等值）

## 数据存储

SQLite `cash_accounts` 表：
- `currency` (PK) — 币种代码（USD/CNY）
- `balance` — 余额
- `updated_at` — 更新时间
