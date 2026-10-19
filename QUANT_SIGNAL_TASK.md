# 量化信号板块开发任务

## 目标
在 portfolio-monitor 工作台新增「量化信号」Tab，展示持仓标的的基本面历史分位数据，辅助判断估值高低。

## 标的范围
- 美股：BABA、TME、GOOGL、MSFT、NVDA、META
- A股：510300.SS（沪深300ETF，用指数PE代替）

## 后端任务

### 1. 新增数据脚本 backend/scripts/fetch_fundamentals.py
用 AKShare 拉取以下指标：
- 美股：PE(TTM)、PB、ROE、毛利率、营收同比增长（用 akshare stock_us_fundamental 或 yfinance fallback）
- A股：沪深300指数PE（akshare index_value_hist_funddata）
- 历史数据范围：最近3年，按季度

### 2. 新增数据表 QuantSignal（backend/app/models.py）
```python
class QuantSignal(Base):
    __tablename__ = "quant_signals"
    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), index=True)
    date = Column(DateTime)
    metric = Column(String(30))   # pe_ttm / pb / roe / gross_margin / revenue_growth
    value = Column(Float)
    percentile = Column(Float)    # 历史分位（0-100），越低越便宜
    updated_at = Column(DateTime, default=utcnow)
```

### 3. 新增 API（backend/app/routers/quant.py）
- GET /api/quant/signals — 返回所有标的最新信号
- GET /api/quant/signals/{symbol} — 返回单标的历史数据
- POST /api/quant/refresh — 手动触发数据刷新

### 4. 定时刷新
每天收盘后（16:00 CST）自动更新一次，加入 apscheduler

## 前端任务（frontend/src/App.vue）

### 新增 Tab：「📊 量化」

展示内容：
1. **信号总览卡片**（每个标的一张）
   - 标的名称 + 市场
   - 当前PE/PB 及历史分位（用颜色标注：<20% 绿色=便宜，>80% 红色=贵）
   - ROE 近期趋势（箭头：↑↓→）
   - 综合评分（0-100，基于各指标分位加权）

2. **历史分位走势图**（点击标的展开）
   - 用 echarts 折线图展示 PE 历史分位
   - 标注当前位置

### 颜色规范
- 分位 < 20%：绿色（历史低位，相对便宜）
- 分位 20-50%：蓝色（中性偏低）
- 分位 50-80%：黄色（中性偏高）
- 分位 > 80%：红色（历史高位，相对贵）

## 验收标准
1. `GET /api/quant/signals` 返回至少4个标的的数据
2. 前端「量化」Tab 可正常访问，展示信号卡片
3. PE分位颜色标注正确
4. `npm run build` 通过，服务重启正常
5. **每步必须贴实际命令输出，禁止编造**

## 技术注意
- 美股基本面数据优先用 yfinance（`pip install yfinance`），akshare美股数据不稳定
- A股用 akshare，已在 venv 里安装
- 分位计算：当前值在过去3年历史数据中的百分位
- 数据库迁移：在 migrate_alerts.py 里加建表逻辑，或新建 migrate_quant.py

## 项目路径
~/Coding/portfolio-monitor
venv 路径：~/Coding/portfolio-monitor/venv
