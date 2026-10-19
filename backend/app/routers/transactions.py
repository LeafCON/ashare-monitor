"""Transaction CRUD endpoints."""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    Transaction, TransactionCreate, TransactionOut, TradeAction, gen_id, utcnow,
    CashAccount, PriceCache,
)

router = APIRouter(prefix="/api/transactions", tags=["transactions"])


def get_currency_for_symbol(symbol: str, db: Session) -> str:
    """Determine currency for a symbol based on market type or cached price."""
    # Check price cache first
    cached = db.query(PriceCache).filter(PriceCache.symbol == symbol).first()
    if cached and cached.currency:
        return cached.currency
    
    # Fallback: CN symbols typically end with .SS or .SZ
    if symbol.endswith(".SS") or symbol.endswith(".SZ") or symbol.endswith(".BJ"):
        return "CNY"
    return "USD"


def update_cash_for_transaction(db: Session, symbol: str, action: TradeAction, total_amount: float, fee: float):
    """Update cash account when transaction is created.
    
    - Buy: deduct cash (amount + fee)
    - Sell: add cash (amount - fee)
    """
    currency = get_currency_for_symbol(symbol, db)
    account = db.query(CashAccount).filter(CashAccount.currency == currency).first()
    
    if not account:
        # Auto-create cash account if not exists
        account = CashAccount(
            currency=currency,
            balance=0.0,
            updated_at=utcnow(),
        )
        db.add(account)
    
    if action == TradeAction.buy:
        # Buy: deduct total cost (amount + fee)
        total_cost = total_amount + fee
        if account.balance < total_cost:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient {currency} cash balance. Required: {total_cost:.2f}, Available: {account.balance:.2f}"
            )
        account.balance -= total_cost
    else:  # sell
        # Sell: add proceeds (amount - fee)
        proceeds = total_amount - fee
        account.balance += proceeds
    
    account.updated_at = utcnow()
    return account


@router.get("", response_model=List[TransactionOut])
def list_transactions(
    symbol: Optional[str] = None,
    action: Optional[TradeAction] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """List transactions with optional filters."""
    q = db.query(Transaction).order_by(Transaction.date.desc())

    if symbol:
        q = q.filter(Transaction.symbol == symbol.upper())
    if action:
        q = q.filter(Transaction.action == action)
    if start_date:
        q = q.filter(Transaction.date >= start_date)
    if end_date:
        q = q.filter(Transaction.date <= end_date)

    return q.offset(offset).limit(limit).all()


@router.post("", response_model=TransactionOut, status_code=201)
def create_transaction(payload: TransactionCreate, db: Session = Depends(get_db)):
    """Add a new transaction and update cash balance accordingly."""
    # Calculate total amount
    total_amount = round(payload.price * payload.shares, 4)
    
    # Update cash account first (will raise if insufficient)
    update_cash_for_transaction(
        db, 
        payload.symbol.upper(), 
        payload.action, 
        total_amount, 
        payload.fee
    )
    
    tx = Transaction(
        id=gen_id(),
        date=payload.date or datetime.now(timezone.utc),
        symbol=payload.symbol.upper(),
        name=payload.name,
        action=payload.action,
        price=payload.price,
        shares=payload.shares,
        amount=total_amount,
        fee=payload.fee,
        notes=payload.notes,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)
    return tx


@router.get("/{tx_id}", response_model=TransactionOut)
def get_transaction(tx_id: str, db: Session = Depends(get_db)):
    """Get a single transaction by ID."""
    tx = db.query(Transaction).filter(Transaction.id == tx_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return tx


@router.delete("/{tx_id}", status_code=204)
def delete_transaction(tx_id: str, db: Session = Depends(get_db)):
    """Delete a transaction and reverse its cash impact."""
    tx = db.query(Transaction).filter(Transaction.id == tx_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")

    # Reverse cash balance: buy→refund, sell→deduct
    try:
        currency = get_currency_for_symbol(tx.symbol, db)
        account = db.query(CashAccount).filter(CashAccount.currency == currency).first()
        if account:
            if tx.action == TradeAction.buy:
                # Refund: return amount + fee
                account.balance += (tx.amount + tx.fee)
            elif tx.action == TradeAction.sell:
                # Reverse sell proceeds: deduct amount - fee
                account.balance -= (tx.amount - tx.fee)
            account.updated_at = utcnow()
    except Exception as e:
        # Cash adjustment failure should not block transaction deletion
        import logging
        logging.getLogger(__name__).warning(f"Cash rollback failed for tx {tx_id}: {e}")

    db.delete(tx)
    db.commit()


@router.get("/export/csv")
def export_csv(db: Session = Depends(get_db)):
    """Export all transactions as CSV."""
    transactions = db.query(Transaction).order_by(Transaction.date.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["日期", "代码", "名称", "操作", "价格", "股数", "金额", "手续费", "备注"])

    for tx in transactions:
        writer.writerow([
            tx.date.strftime("%Y-%m-%d %H:%M"),
            tx.symbol,
            tx.name,
            "买入" if tx.action == TradeAction.buy else "卖出",
            f"{tx.price:.4f}",
            f"{tx.shares:.4f}",
            f"{tx.amount:.2f}",
            f"{tx.fee:.2f}",
            tx.notes or "",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=transactions.csv"},
    )
