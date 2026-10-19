"""
Market data router — provides real-time price, ratios, income, estimates, and news.

Data sources:
  Primary:  yfinance (free, supports US + A-shares via .SS/.SZ suffix)
  Optional: Financial Datasets API (when FINANCIAL_DATASETS_API_KEY is set)

Cache: in-memory TTL cache, 5 minutes per symbol per endpoint.
"""

from __future__ import annotations

import logging
import math
import os
import time
from functools import wraps
from typing import Any, Dict, Optional

import requests
try:
    import yfinance as yf
except Exception:  # optional; the A-share monitor does not need it to start
    yf = None
from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/market", tags=["market"])

# ── Simple in-memory TTL cache ────────────────────────────────────────────────

_CACHE: Dict[str, Dict[str, Any]] = {}  # key -> {"data": ..., "ts": float}
CACHE_TTL = 300  # 5 minutes


def _cache_get(key: str) -> Optional[Any]:
    entry = _CACHE.get(key)
    if entry and (time.time() - entry["ts"]) < CACHE_TTL:
        return entry["data"]
    return None


def _cache_set(key: str, data: Any) -> None:
    _CACHE[key] = {"data": data, "ts": time.time()}


def cached(prefix: str):
    """Decorator: cache the result of a function keyed by (prefix, *args)."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            key = f"{prefix}:{':'.join(str(a) for a in args)}"
            hit = _cache_get(key)
            if hit is not None:
                logger.debug(f"Cache HIT: {key}")
                return hit
            result = fn(*args, **kwargs)
            if "error" not in result:
                _cache_set(key, result)
            return result
        return wrapper
    return decorator


# ── Financial Datasets API helper ─────────────────────────────────────────────

FD_BASE = "https://api.financialdatasets.ai"
_FD_API_KEY = os.environ.get("FINANCIAL_DATASETS_API_KEY", "")


def _fd_available() -> bool:
    return bool(_FD_API_KEY)


def _fd_get(path: str, params: Optional[Dict] = None) -> Optional[Dict]:
    """Call Financial Datasets API. Returns None on any failure (triggers yfinance fallback)."""
    if not _fd_available():
        return None
    try:
        url = f"{FD_BASE}{path}"
        resp = requests.get(
            url,
            params=params or {},
            headers={"x-api-key": _FD_API_KEY, "Accept": "application/json"},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            if "error" not in data:
                return data
        elif resp.status_code in (402, 429):
            logger.warning(f"FD API {resp.status_code} for {path}")
    except Exception as e:
        logger.warning(f"FD API request failed for {path}: {e}")
    return None


# ── yfinance helpers ──────────────────────────────────────────────────────────

def _safe(val) -> Optional[Any]:
    """Convert NaN/Inf to None."""
    if val is None:
        return None
    try:
        if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
            return None
    except TypeError:
        pass
    return val


def _yf_ticker(symbol: str) -> yf.Ticker:
    return yf.Ticker(symbol.upper())


# ── Endpoint: GET /api/market/price/{symbol} ──────────────────────────────────

@cached("price")
def _fetch_price(symbol: str) -> Dict:
    upper = symbol.upper()

    # Try FD API first
    fd = _fd_get(f"/prices/snapshot/", {"ticker": upper})
    if fd and "snapshot" in fd:
        s = fd["snapshot"]
        price = _safe(s.get("price"))
        prev = _safe(s.get("prev_close") or s.get("previous_close"))
        change = round(price - prev, 4) if price and prev else None
        change_pct = round(change / prev * 100, 2) if change and prev else None
        return {
            "symbol": upper,
            "source": "financial_datasets",
            "price": price,
            "previous_close": prev,
            "change": change,
            "change_pct": change_pct,
            "volume": _safe(s.get("volume")),
            "market_cap": _safe(s.get("market_cap")),
            "currency": s.get("currency", "USD"),
            "open": _safe(s.get("open")),
            "high": _safe(s.get("high")),
            "low": _safe(s.get("low")),
        }

    # yfinance fallback
    try:
        ticker = _yf_ticker(upper)
        info = ticker.info
        hist = ticker.history(period="2d")

        price = _safe(info.get("regularMarketPrice") or info.get("currentPrice"))
        if not price and not hist.empty:
            price = float(hist["Close"].iloc[-1])

        prev = _safe(info.get("regularMarketPreviousClose") or info.get("previousClose"))
        if not prev and len(hist) >= 2:
            prev = float(hist["Close"].iloc[-2])

        if price is None:
            return {"symbol": upper, "error": "No price data available"}

        change = round(price - prev, 4) if price and prev else None
        change_pct = round(change / prev * 100, 2) if change and prev else None

        return {
            "symbol": upper,
            "source": "yfinance",
            "price": round(price, 4),
            "previous_close": round(prev, 4) if prev else None,
            "change": change,
            "change_pct": change_pct,
            "volume": _safe(info.get("regularMarketVolume") or info.get("volume")),
            "market_cap": _safe(info.get("marketCap")),
            "currency": info.get("currency", "USD"),
            "open": _safe(info.get("regularMarketOpen") or info.get("open")),
            "high": _safe(info.get("regularMarketDayHigh") or info.get("dayHigh")),
            "low": _safe(info.get("regularMarketDayLow") or info.get("dayLow")),
            "name": info.get("longName") or info.get("shortName", upper),
        }
    except Exception as e:
        logger.error(f"yfinance price error for {upper}: {e}")
        return {"symbol": upper, "error": str(e)}


@router.get("/price/{symbol}")
def get_price(symbol: str):
    """实时价格快照，支持美股（AAPL）和A股（510300.SS）。"""
    result = _fetch_price(symbol)
    if "error" in result and "symbol" in result and len(result) == 2:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# ── Endpoint: GET /api/market/ratios/{symbol} ─────────────────────────────────

@cached("ratios")
def _fetch_ratios(symbol: str) -> Dict:
    upper = symbol.upper()

    # Try FD API
    fd = _fd_get(f"/financial-metrics/snapshot/", {"ticker": upper})
    if fd and "snapshot" in fd:
        s = fd["snapshot"]
        return {
            "symbol": upper,
            "source": "financial_datasets",
            "market_cap": _safe(s.get("market_cap")),
            "pe_ratio": _safe(s.get("pe_ratio") or s.get("price_to_earnings_ratio_ttm")),
            "forward_pe": _safe(s.get("forward_pe")),
            "pb_ratio": _safe(s.get("pb_ratio") or s.get("price_to_book_ratio")),
            "ps_ratio": _safe(s.get("price_to_sales_ratio")),
            "peg_ratio": _safe(s.get("peg_ratio")),
            "eps": _safe(s.get("eps_ttm") or s.get("earnings_per_share")),
            "forward_eps": _safe(s.get("eps_forward") or s.get("forward_eps")),
            "dividend_yield": _safe(s.get("dividend_yield")),
            "profit_margin": _safe(s.get("net_profit_margin")),
            "operating_margin": _safe(s.get("operating_profit_margin")),
            "revenue": _safe(s.get("revenue_ttm")),
            "return_on_equity": _safe(s.get("return_on_equity")),
            "return_on_assets": _safe(s.get("return_on_assets")),
            "debt_to_equity": _safe(s.get("debt_to_equity")),
            "beta": _safe(s.get("beta")),
            "52_week_high": _safe(s.get("fifty_two_week_high")),
            "52_week_low": _safe(s.get("fifty_two_week_low")),
        }

    # yfinance fallback
    try:
        info = _yf_ticker(upper).info
        return {
            "symbol": upper,
            "source": "yfinance",
            "market_cap": _safe(info.get("marketCap")),
            "pe_ratio": _safe(info.get("trailingPE")),
            "forward_pe": _safe(info.get("forwardPE")),
            "pb_ratio": _safe(info.get("priceToBook")),
            "ps_ratio": _safe(info.get("priceToSalesTrailing12Months")),
            "peg_ratio": _safe(info.get("pegRatio")),
            "eps": _safe(info.get("trailingEps")),
            "forward_eps": _safe(info.get("forwardEps")),
            "dividend_yield": _safe(info.get("dividendYield")),
            "profit_margin": _safe(info.get("profitMargins")),
            "operating_margin": _safe(info.get("operatingMargins")),
            "revenue": _safe(info.get("totalRevenue")),
            "revenue_growth": _safe(info.get("revenueGrowth")),
            "earnings_growth": _safe(info.get("earningsGrowth")),
            "return_on_equity": _safe(info.get("returnOnEquity")),
            "return_on_assets": _safe(info.get("returnOnAssets")),
            "debt_to_equity": _safe(info.get("debtToEquity")),
            "current_ratio": _safe(info.get("currentRatio")),
            "book_value": _safe(info.get("bookValue")),
            "enterprise_value": _safe(info.get("enterpriseValue")),
            "beta": _safe(info.get("beta")),
            "52_week_high": _safe(info.get("fiftyTwoWeekHigh")),
            "52_week_low": _safe(info.get("fiftyTwoWeekLow")),
            "avg_volume": _safe(info.get("averageVolume")),
            "name": info.get("longName") or info.get("shortName", upper),
        }
    except Exception as e:
        logger.error(f"yfinance ratios error for {upper}: {e}")
        return {"symbol": upper, "error": str(e)}


@router.get("/ratios/{symbol}")
def get_ratios(symbol: str):
    """PE/PB/EPS/市值等关键估值指标。"""
    result = _fetch_ratios(symbol)
    if "error" in result and len(result) == 2:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# ── Endpoint: GET /api/market/income/{symbol} ─────────────────────────────────

@cached("income")
def _fetch_income(symbol: str, period: str) -> Dict:
    upper = symbol.upper()

    # Try FD API
    fd = _fd_get(f"/financials/income-statements/", {
        "ticker": upper,
        "period": period,
        "limit": 4,
    })
    if fd and "income_statements" in fd and fd["income_statements"]:
        return {
            "symbol": upper,
            "source": "financial_datasets",
            "period": period,
            "income_statements": fd["income_statements"],
        }

    # yfinance fallback
    try:
        ticker = _yf_ticker(upper)
        df = ticker.quarterly_income_stmt if period == "quarterly" else ticker.income_stmt

        if df is None or df.empty:
            return {"symbol": upper, "error": f"No income statement data for {upper}"}

        records = []
        for col in list(df.columns)[:4]:
            date_str = col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col)
            row: Dict[str, Any] = {"report_period": date_str}
            for idx in df.index:
                key = str(idx).lower().replace(" ", "_")
                val = df.loc[idx, col]
                row[key] = _safe(float(val)) if val is not None and not (isinstance(val, float) and math.isnan(val)) else None
            records.append(row)

        # Normalize to canonical field names
        normalized = []
        for r in records:
            normalized.append({
                "report_period": r.get("report_period"),
                "revenue": r.get("total_revenue"),
                "cost_of_revenue": r.get("cost_of_revenue"),
                "gross_profit": r.get("gross_profit"),
                "operating_income": r.get("operating_income"),
                "net_income": r.get("net_income") or r.get("net_income_common_stockholders"),
                "ebitda": r.get("ebitda") or r.get("normalized_ebitda"),
                "eps_basic": r.get("basic_eps"),
                "eps_diluted": r.get("diluted_eps"),
                "research_and_development": r.get("research_and_development"),
                "interest_expense": r.get("interest_expense"),
            })

        return {
            "symbol": upper,
            "source": "yfinance",
            "period": period,
            "income_statements": normalized,
        }
    except Exception as e:
        logger.error(f"yfinance income error for {upper}: {e}")
        return {"symbol": upper, "error": str(e)}


@router.get("/income/{symbol}")
def get_income(
    symbol: str,
    period: str = Query("annual", pattern="^(annual|quarterly)$"),
):
    """财报数据（损益表）。period=annual|quarterly，默认年度。"""
    result = _fetch_income(symbol, period)
    if "error" in result and len(result) == 2:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# ── Endpoint: GET /api/market/estimates/{symbol} ──────────────────────────────

@cached("estimates")
def _fetch_estimates(symbol: str, period: str) -> Dict:
    upper = symbol.upper()

    # Try FD API
    fd = _fd_get(f"/financials/analyst-estimates/", {
        "ticker": upper,
        "period": period,
        "limit": 4,
    })
    if fd and "analyst_estimates" in fd and fd["analyst_estimates"]:
        return {
            "symbol": upper,
            "source": "financial_datasets",
            "period": period,
            "analyst_estimates": fd["analyst_estimates"],
        }

    # yfinance fallback — analyst_price_targets + earnings_estimate
    try:
        ticker = _yf_ticker(upper)

        result: Dict[str, Any] = {
            "symbol": upper,
            "source": "yfinance",
            "period": period,
        }

        # Price targets
        try:
            pt = ticker.analyst_price_targets
            if pt:
                result["price_targets"] = {
                    "current": _safe(pt.get("current")),
                    "low": _safe(pt.get("low")),
                    "high": _safe(pt.get("high")),
                    "mean": _safe(pt.get("mean")),
                    "median": _safe(pt.get("median")),
                }
        except Exception:
            pass

        # Earnings + revenue estimates
        try:
            ee = ticker.earnings_estimate
            if ee is not None and not ee.empty:
                result["earnings_estimates"] = ee.reset_index().to_dict(orient="records")
        except Exception:
            pass

        try:
            re = ticker.revenue_estimate
            if re is not None and not re.empty:
                result["revenue_estimates"] = re.reset_index().to_dict(orient="records")
        except Exception:
            pass

        # Recommendations summary
        try:
            rec = ticker.recommendations_summary
            if rec is not None and not rec.empty:
                result["recommendations"] = rec.to_dict(orient="records")
        except Exception:
            pass

        if len(result) <= 3:
            result["error"] = f"No analyst estimate data available for {upper}"

        return result

    except Exception as e:
        logger.error(f"yfinance estimates error for {upper}: {e}")
        return {"symbol": upper, "error": str(e)}


@router.get("/estimates/{symbol}")
def get_estimates(
    symbol: str,
    period: str = Query("annual", pattern="^(annual|quarterly)$"),
):
    """分析师预期（目标价、盈利预测、营收预测、评级）。"""
    result = _fetch_estimates(symbol, period)
    if "error" in result and len(result) == 2:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# ── Endpoint: GET /api/market/news/{symbol} ───────────────────────────────────

@cached("news")
def _fetch_news(symbol: str, limit: int) -> Dict:
    upper = symbol.upper()

    # Try FD API
    fd = _fd_get(f"/news/", {"ticker": upper, "limit": limit})
    if fd and "news" in fd and fd["news"]:
        return {
            "symbol": upper,
            "source": "financial_datasets",
            "news": fd["news"],
        }

    # yfinance fallback
    try:
        ticker = _yf_ticker(upper)
        raw_news = ticker.news or []

        articles = []
        for item in raw_news[:limit]:
            content = item.get("content", {})
            articles.append({
                "title": content.get("title") or item.get("title", ""),
                "description": content.get("summary") or item.get("summary", ""),
                "url": (content.get("canonicalUrl") or {}).get("url") or item.get("link", ""),
                "source": (content.get("provider") or {}).get("displayName") or item.get("publisher", ""),
                "published_at": content.get("pubDate") or item.get("providerPublishTime", ""),
            })

        return {
            "symbol": upper,
            "source": "yfinance",
            "count": len(articles),
            "news": articles,
        }
    except Exception as e:
        logger.error(f"yfinance news error for {upper}: {e}")
        return {"symbol": upper, "error": str(e)}


@router.get("/news/{symbol}")
def get_news(
    symbol: str,
    limit: int = Query(10, ge=1, le=50),
):
    """近期新闻，默认返回10条，最多50条。"""
    result = _fetch_news(symbol, limit)
    if "error" in result and len(result) == 2:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# ── Endpoint: GET /api/market/balance/{symbol} ────────────────────────────────

@cached("balance")
def _fetch_balance(symbol: str, period: str, limit: int) -> Dict:
    upper = symbol.upper()
    try:
        ticker = _yf_ticker(upper)
        df = ticker.quarterly_balance_sheet if period == "quarterly" else ticker.balance_sheet

        if df is None or df.empty:
            return {"symbol": upper, "error": "data not available"}

        records = []
        for col in list(df.columns)[:limit]:
            date_str = col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col)
            row: Dict[str, Any] = {}
            for idx in df.index:
                key = str(idx)
                val = df.loc[idx, col]
                row[key] = None if (val is None or (isinstance(val, float) and (math.isnan(val) or math.isinf(val)))) else float(val)

            def g(k): return row.get(k)

            total_assets = g("Total Assets")
            total_liabilities = g("Total Liabilities Net Minority Interest") or g("Total Liabilities")
            stockholders_equity = g("Stockholders Equity") or g("Common Stock Equity")
            cash = g("Cash And Cash Equivalents") or g("Cash Cash Equivalents And Short Term Investments")
            total_debt = g("Total Debt")
            book_value = g("Book Value")
            shares = g("Ordinary Shares Number") or g("Share Issued")

            bvps = None
            if book_value and shares and shares > 0:
                bvps = round(book_value / shares, 4)
            elif stockholders_equity and shares and shares > 0:
                bvps = round(stockholders_equity / shares, 4)

            records.append({
                "date": date_str,
                "total_assets": _safe(total_assets),
                "total_liabilities": _safe(total_liabilities),
                "shareholders_equity": _safe(stockholders_equity),
                "cash": _safe(cash),
                "total_debt": _safe(total_debt),
                "book_value_per_share": _safe(bvps),
            })

        return {"symbol": upper, "source": "yfinance", "period": period, "data": records}
    except Exception as e:
        logger.error(f"yfinance balance error for {upper}: {e}")
        return {"symbol": upper, "error": "data not available"}


@router.get("/balance/{symbol}")
def get_balance(
    symbol: str,
    period: str = Query("quarterly", pattern="^(annual|quarterly)$"),
    limit: int = Query(4, ge=1, le=8),
):
    """资产负债表（total_assets/liabilities/equity/cash/debt/bvps）。"""
    result = _fetch_balance(symbol, period, limit)
    if "error" in result and len(result) == 2:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# ── Endpoint: GET /api/market/cashflow/{symbol} ───────────────────────────────

@cached("cashflow")
def _fetch_cashflow(symbol: str, period: str, limit: int) -> Dict:
    upper = symbol.upper()
    try:
        ticker = _yf_ticker(upper)
        df = ticker.quarterly_cashflow if period == "quarterly" else ticker.cashflow

        if df is None or df.empty:
            return {"symbol": upper, "error": "data not available"}

        records = []
        for col in list(df.columns)[:limit]:
            date_str = col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col)
            row: Dict[str, Any] = {}
            for idx in df.index:
                val = df.loc[idx, col]
                row[str(idx)] = None if (val is None or (isinstance(val, float) and (math.isnan(val) or math.isinf(val)))) else float(val)

            def g(k): return row.get(k)

            ocf = g("Operating Cash Flow") or g("Cash Flow From Continuing Operating Activities")
            capex = g("Capital Expenditure") or g("Purchase Of Property Plant And Equipment")
            ni = g("Net Income") or g("Net Income From Continuing Operations")
            fcf = None
            if ocf is not None and capex is not None:
                fcf = ocf + capex  # capex is already negative in yfinance

            records.append({
                "date": date_str,
                "operating_cash_flow": _safe(ocf),
                "capital_expenditure": _safe(capex),
                "free_cash_flow": _safe(fcf),
                "net_income": _safe(ni),
            })

        return {"symbol": upper, "source": "yfinance", "period": period, "data": records}
    except Exception as e:
        logger.error(f"yfinance cashflow error for {upper}: {e}")
        return {"symbol": upper, "error": "data not available"}


@router.get("/cashflow/{symbol}")
def get_cashflow(
    symbol: str,
    period: str = Query("quarterly", pattern="^(annual|quarterly)$"),
    limit: int = Query(4, ge=1, le=8),
):
    """现金流量表（OCF/CapEx/FCF/净利润）。"""
    result = _fetch_cashflow(symbol, period, limit)
    if "error" in result and len(result) == 2:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# ── Endpoint: GET /api/market/company/{symbol} ────────────────────────────────

@cached("company")
def _fetch_company(symbol: str) -> Dict:
    upper = symbol.upper()
    try:
        info = _yf_ticker(upper).info
        if not info or info.get("quoteType") == "NONE":
            return {"symbol": upper, "error": "data not available"}

        desc = info.get("longBusinessSummary", "") or ""
        if len(desc) > 300:
            desc = desc[:300] + "..."

        return {
            "symbol": upper,
            "source": "yfinance",
            "name": info.get("longName") or info.get("shortName", upper),
            "sector": info.get("sector", ""),
            "industry": info.get("industry", ""),
            "country": info.get("country", ""),
            "employees": _safe(info.get("fullTimeEmployees")),
            "description": desc,
            "website": info.get("website", ""),
            "exchange": info.get("exchange", ""),
        }
    except Exception as e:
        logger.error(f"yfinance company error for {upper}: {e}")
        return {"symbol": upper, "error": "data not available"}


@router.get("/company/{symbol}")
def get_company(symbol: str):
    """公司基本信息（行业/员工数/简介/网站）。"""
    result = _fetch_company(symbol)
    if "error" in result and len(result) == 2:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# ── Endpoint: GET /api/market/insiders/{symbol} ───────────────────────────────

@cached("insiders")
def _fetch_insiders(symbol: str, limit: int) -> Dict:
    upper = symbol.upper()
    try:
        ticker = _yf_ticker(upper)
        df = ticker.insider_transactions

        if df is None or df.empty:
            return {"symbol": upper, "error": "data not available"}

        records = []
        for _, row in df.head(limit).iterrows():
            date_val = row.get("Start Date") or row.get("Date") or row.get("startDate")
            date_str = date_val.strftime("%Y-%m-%d") if hasattr(date_val, "strftime") else str(date_val)[:10] if date_val else ""

            shares_val = row.get("Shares") or row.get("shares")
            value_val = row.get("Value") or row.get("value")
            txt = row.get("Text") or row.get("text") or ""

            records.append({
                "date": date_str,
                "name": str(row.get("Insider") or row.get("name") or ""),
                "title": str(row.get("Position") or row.get("title") or ""),
                "transaction_type": str(row.get("Transaction") or row.get("transaction") or txt)[:80],
                "shares": _safe(float(shares_val)) if shares_val is not None else None,
                "value": _safe(float(value_val)) if value_val is not None else None,
            })

        return {"symbol": upper, "source": "yfinance", "count": len(records), "data": records}
    except Exception as e:
        logger.error(f"yfinance insiders error for {upper}: {e}")
        return {"symbol": upper, "error": "data not available"}


@router.get("/insiders/{symbol}")
def get_insiders(
    symbol: str,
    limit: int = Query(10, ge=1, le=50),
):
    """内幕交易记录（高管买卖）。"""
    result = _fetch_insiders(symbol, limit)
    if "error" in result and len(result) == 2:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# ── Endpoint: GET /api/market/segments/{symbol} ───────────────────────────────

@cached("segments")
def _fetch_segments(symbol: str) -> Dict:
    upper = symbol.upper()
    try:
        ticker = _yf_ticker(upper)
        result: Dict[str, Any] = {"symbol": upper, "source": "yfinance"}
        found = False

        for attr in ("revenue_by_product", "revenue_by_geography"):
            try:
                df = getattr(ticker, attr, None)
                if df is not None and not (hasattr(df, "empty") and df.empty):
                    # Convert DataFrame to dict
                    if hasattr(df, "to_dict"):
                        data = df.to_dict()
                        # Normalize keys (Timestamps -> string)
                        normalized = {}
                        for seg, vals in data.items():
                            normalized[str(seg)] = {
                                (k.strftime("%Y-%m-%d") if hasattr(k, "strftime") else str(k)): (
                                    None if (v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v)))) else v
                                )
                                for k, v in vals.items()
                            }
                        result[attr] = normalized
                        found = True
            except Exception:
                pass

        if not found:
            return {"symbol": upper, "error": "not available"}

        return result
    except Exception as e:
        logger.error(f"yfinance segments error for {upper}: {e}")
        return {"symbol": upper, "error": "not available"}


@router.get("/segments/{symbol}")
def get_segments(symbol: str):
    """营收拆分（按产品/地区）。若无数据返回 error:not available。"""
    return _fetch_segments(symbol)


# ── Endpoint: GET /api/market/crypto/{symbol} ────────────────────────────────

@router.get("/crypto/{symbol}")
def get_crypto(symbol: str):
    """加密货币价格，symbol 如 BTC-USD / ETH-USD。"""
    # Reuse the price endpoint — yfinance handles crypto tickers natively
    upper = symbol.upper()
    # Ensure -USD suffix is present if missing common pairs
    result = _fetch_price(upper)
    if "error" in result and len(result) == 2:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# ── Endpoint: GET /api/market/prices/{symbol} ─────────────────────────────────

@router.get("/prices/{symbol}")
def get_prices(
    symbol: str,
    start: str = Query("2024-01-01"),
    end: str = Query(...),
    interval: str = Query("1d", pattern="^(1d|1wk|1mo|5m|15m|30m|1h)$"),
):
    """历史 OHLCV 价格序列。interval: 1d|1wk|1mo|5m|15m|30m|1h。"""
    upper = symbol.upper()
    import datetime
    # default end to today if not provided
    cache_key = f"prices:{upper}:{start}:{end}:{interval}"
    hit = _cache_get(cache_key)
    if hit is not None:
        return hit

    try:
        ticker = _yf_ticker(upper)
        hist = ticker.history(start=start, end=end, interval=interval)

        if hist is None or hist.empty:
            return {"symbol": upper, "error": "data not available"}

        records = []
        for ts, row in hist.iterrows():
            date_str = ts.strftime("%Y-%m-%d %H:%M:%S") if hasattr(ts, "strftime") else str(ts)
            records.append({
                "date": date_str,
                "open": _safe(float(row["Open"])),
                "high": _safe(float(row["High"])),
                "low": _safe(float(row["Low"])),
                "close": _safe(float(row["Close"])),
                "volume": _safe(float(row["Volume"])),
            })

        result = {
            "symbol": upper,
            "source": "yfinance",
            "interval": interval,
            "start": start,
            "end": end,
            "count": len(records),
            "data": records,
        }
        _cache_set(cache_key, result)
        return result
    except Exception as e:
        logger.error(f"yfinance prices error for {upper}: {e}")
        return {"symbol": upper, "error": "data not available"}
