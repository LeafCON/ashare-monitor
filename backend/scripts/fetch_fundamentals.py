"""
Fetch fundamental data for portfolio symbols and compute historical percentiles.

Data sources:
- US stocks: akshare (百度股市通 for PE/PB, 东方财富 for ROE/margins)
- CN stocks: akshare (乐咕乐股 for CSI300 PE)

Usage:
    cd ~/Coding/portfolio-monitor/backend
    source ../venv/bin/activate
    python -m scripts.fetch_fundamentals
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import SessionLocal, init_db
from app.models import QuantSignal

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("fetch_fundamentals")

# ── Configuration ──────────────────────────────────────────────────────────

US_SYMBOLS = ["BABA", "TME", "GOOGL", "MSFT", "NVDA", "META"]
CN_SYMBOL = "510300.SS"


def compute_percentile(current: float, values: list[float]) -> float:
    """Percentile of current within values (0-100)."""
    if not values or current is None:
        return 50.0
    below = sum(1 for v in values if v < current)
    equal = sum(1 for v in values if v == current)
    n = len(values)
    return round((below + 0.5 * equal) / n * 100, 1) if n else 50.0


def fetch_us_valuation(symbol: str) -> dict:
    """Fetch PE(TTM), PB history for a US stock via akshare/百度.
    
    Returns {
        "pe_ttm": float, "pe_percentile": float, "pe_history": [{date, value}],
        "pb": float, "pb_percentile": float, "pb_history": [{date, value}],
    }
    """
    import akshare as ak
    
    result = {}
    
    # PE(TTM)
    try:
        df = ak.stock_us_valuation_baidu(symbol=symbol, indicator="市盈率(TTM)", period="近三年")
        if df is not None and not df.empty:
            values = df["value"].dropna().tolist()
            current = values[-1] if values else None
            if current is not None:
                result["pe_ttm"] = round(float(current), 2)
                result["pe_percentile"] = compute_percentile(float(current), [float(v) for v in values])
                # Sample history for charts (every ~60 days)
                step = max(1, len(df) // 12)
                hist = []
                for _, row in df.iloc[::step].iterrows():
                    try:
                        hist.append({"date": str(row["date"]), "value": float(row["value"])})
                    except (ValueError, TypeError):
                        pass
                result["pe_history"] = hist[-12:]
        time.sleep(0.5)
    except Exception as e:
        logger.warning(f"  {symbol} PE fetch error: {e}")
    
    # PB
    try:
        df = ak.stock_us_valuation_baidu(symbol=symbol, indicator="市净率", period="近三年")
        if df is not None and not df.empty:
            values = df["value"].dropna().tolist()
            current = values[-1] if values else None
            if current is not None:
                result["pb"] = round(float(current), 2)
                result["pb_percentile"] = compute_percentile(float(current), [float(v) for v in values])
                step = max(1, len(df) // 12)
                hist = []
                for _, row in df.iloc[::step].iterrows():
                    try:
                        hist.append({"date": str(row["date"]), "value": float(row["value"])})
                    except (ValueError, TypeError):
                        pass
                result["pb_history"] = hist[-12:]
        time.sleep(0.5)
    except Exception as e:
        logger.warning(f"  {symbol} PB fetch error: {e}")
    
    return result


def fetch_us_financials(symbol: str) -> dict:
    """Fetch ROE, gross margin, revenue growth from 东方财富.
    
    Returns {"roe": float, "gross_margin": float, "revenue_growth": float}
    """
    import akshare as ak
    
    result = {}
    
    try:
        df = ak.stock_financial_us_analysis_indicator_em(symbol=symbol, indicator="年报")
        if df is not None and not df.empty:
            # Get latest row (first row is most recent)
            latest = df.iloc[0]
            
            roe = latest.get("ROE_AVG")
            if roe is not None and str(roe) != "nan" and str(roe) != "None":
                result["roe"] = round(float(roe), 2)
            
            gm = latest.get("GROSS_PROFIT_RATIO")
            if gm is not None and str(gm) != "nan" and str(gm) != "None":
                result["gross_margin"] = round(float(gm), 2)
            
            rg = latest.get("OPERATE_INCOME_YOY")
            if rg is not None and str(rg) != "nan" and str(rg) != "None":
                result["revenue_growth"] = round(float(rg), 2)
                
    except Exception as e:
        logger.warning(f"  {symbol} financial data error: {e}")
    
    return result


def fetch_cn_index_pe() -> dict:
    """Fetch CSI300 PE(TTM) via akshare 乐咕乐股.
    
    Returns {"pe_ttm": float, "pe_percentile": float, "pe_history": [...]}
    """
    import akshare as ak
    
    try:
        df = ak.stock_index_pe_lg(symbol="沪深300")
        if df is None or df.empty:
            return {}
        
        pe_col = "滚动市盈率"
        date_col = "日期"
        
        df[pe_col] = df[pe_col].astype(float)
        df = df.dropna(subset=[pe_col])
        
        # Last 3 years for percentile
        three_years_ago = datetime.now() - timedelta(days=3 * 365)
        recent = df[df[date_col].apply(lambda x: datetime.fromisoformat(str(x)) >= three_years_ago)]
        
        if recent.empty:
            recent = df.tail(252)  # ~1 year of trading days
        
        values = recent[pe_col].tolist()
        current = values[-1] if values else None
        
        if current is None:
            return {}
        
        result = {
            "pe_ttm": round(float(current), 2),
            "pe_percentile": compute_percentile(float(current), [float(v) for v in values]),
        }
        
        # Sample history for chart
        step = max(1, len(recent) // 12)
        hist = []
        for _, row in recent.iloc[::step].iterrows():
            try:
                hist.append({"date": str(row[date_col]), "value": float(row[pe_col])})
            except (ValueError, TypeError):
                pass
        result["pe_history"] = hist[-12:]
        
        return result
        
    except Exception as e:
        logger.error(f"  CSI300 PE error: {e}")
        return {}


def refresh_all_signals():
    """Main refresh function — fetch all data and save to DB."""
    db = SessionLocal()
    now = datetime.now(timezone.utc)
    
    try:
        # Clear old data (keep it fresh)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        deleted = db.query(QuantSignal).filter(QuantSignal.updated_at >= today_start).delete()
        if deleted:
            logger.info(f"Cleared {deleted} existing signals from today")
        db.commit()
        
        updated_count = 0
        symbols_done = 0
        
        # ── US Stocks ──
        for symbol in US_SYMBOLS:
            logger.info(f"Processing {symbol}...")
            
            # Valuation (PE, PB)
            val_data = fetch_us_valuation(symbol)
            time.sleep(1)
            
            # Financials (ROE, margins, growth)
            fin_data = fetch_us_financials(symbol)
            time.sleep(1)
            
            has_data = False
            
            # Save PE
            if "pe_ttm" in val_data:
                db.add(QuantSignal(
                    symbol=symbol, date=now, metric="pe_ttm",
                    value=val_data["pe_ttm"], percentile=val_data.get("pe_percentile", 50),
                    updated_at=now,
                ))
                updated_count += 1
                has_data = True
                
                # Historical PE for chart
                for entry in val_data.get("pe_history", []):
                    try:
                        all_values = [float(e["value"]) for e in val_data.get("pe_history", [])]
                        db.add(QuantSignal(
                            symbol=symbol, date=datetime.fromisoformat(entry["date"]),
                            metric="pe_ttm", value=float(entry["value"]),
                            percentile=compute_percentile(float(entry["value"]), all_values),
                            updated_at=now,
                        ))
                    except Exception:
                        pass
            
            # Save PB
            if "pb" in val_data:
                db.add(QuantSignal(
                    symbol=symbol, date=now, metric="pb",
                    value=val_data["pb"], percentile=val_data.get("pb_percentile", 50),
                    updated_at=now,
                ))
                updated_count += 1
                has_data = True
            
            # Save ROE
            if "roe" in fin_data:
                db.add(QuantSignal(
                    symbol=symbol, date=now, metric="roe",
                    value=fin_data["roe"], percentile=50,
                    updated_at=now,
                ))
                updated_count += 1
                has_data = True
            
            # Save Gross Margin
            if "gross_margin" in fin_data:
                db.add(QuantSignal(
                    symbol=symbol, date=now, metric="gross_margin",
                    value=fin_data["gross_margin"], percentile=50,
                    updated_at=now,
                ))
                updated_count += 1
                has_data = True
            
            # Save Revenue Growth
            if "revenue_growth" in fin_data:
                db.add(QuantSignal(
                    symbol=symbol, date=now, metric="revenue_growth",
                    value=fin_data["revenue_growth"], percentile=50,
                    updated_at=now,
                ))
                updated_count += 1
                has_data = True
            
            if has_data:
                symbols_done += 1
                logger.info(f"  ✓ {symbol}: PE={val_data.get('pe_ttm')}, PB={val_data.get('pb')}, ROE={fin_data.get('roe')}, GM={fin_data.get('gross_margin')}, RG={fin_data.get('revenue_growth')}")
            else:
                logger.warning(f"  ✗ {symbol}: no data")
        
        # ── CN Stock (CSI 300) ──
        logger.info("Processing 510300.SS (CSI 300)...")
        cn_data = fetch_cn_index_pe()
        
        if "pe_ttm" in cn_data:
            db.add(QuantSignal(
                symbol=CN_SYMBOL, date=now, metric="pe_ttm",
                value=cn_data["pe_ttm"], percentile=cn_data.get("pe_percentile", 50),
                updated_at=now,
            ))
            updated_count += 1
            symbols_done += 1
            
            # Historical entries
            for entry in cn_data.get("pe_history", []):
                try:
                    all_values = [float(e["value"]) for e in cn_data.get("pe_history", [])]
                    db.add(QuantSignal(
                        symbol=CN_SYMBOL, date=datetime.fromisoformat(entry["date"]),
                        metric="pe_ttm", value=float(entry["value"]),
                        percentile=compute_percentile(float(entry["value"]), all_values),
                        updated_at=now,
                    ))
                except Exception:
                    pass
            
            logger.info(f"  ✓ 510300.SS: PE={cn_data['pe_ttm']}, percentile={cn_data.get('pe_percentile')}")
        
        db.commit()
        logger.info(f"✅ Done: {updated_count} signals for {symbols_done} symbols")
        return updated_count
        
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        db.rollback()
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    init_db()
    refresh_all_signals()
