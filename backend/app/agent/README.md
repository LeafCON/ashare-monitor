# Crypto decision layer

This sits beside the stock monitor. It does not send exchange orders.

## Layers

- Research notes are in `backend/app/agent/RESEARCH.md`. Numbers there are copied from the cited pages and dated. Missing funding, open interest, unlock, and revenue figures are left missing.
- `state_engine.py` builds mid, spread, imbalance, realized volatility, inventory, and drawdown. A timestamp after the decision time raises.
- `reflex.py` calls Jev only when `JEV_API_KEY` is set. Otherwise it tries `HuggingFaceTB/SmolLM2-135M-Instruct` when `AGENT_HF=true` and the weights are installed. The running default is the local calibrated scorer, which returns the same typed fields.
- `policy.py` allows an order only when setup quality is at least 2, direction confidence is above 0.80, and risk state is `safe`. Size is quarter-Kelly, then capped at 10% of quote balance.
- `execute.py` sends a Binance spot market order after that gate. If `BINANCE_API_KEY` or `BINANCE_API_SECRET` is empty, the loop waits and does not send. The stock monitor keeps running.
- `risk.py` blocks at 15% drawdown, 5% daily loss, and 10% position fraction. `AGENT_KILL=true` or a `data/agent_kill` file stops every order.

## AgentKit

`https://agentkit.xyz` did not load on 2026-10-20 (gateway timeout). The six phases are the files in this folder: this note (spec), `schema.py` (architecture), the tests (plan and test-first), `REVIEW.md` (review), and the paper endpoint (ship). Nothing is installed from that site.

## API

- `GET /api/agent/status`
- `POST /api/agent/tick` reads the live book when Binance keys are set and sends an order if the gate passes. Without keys it returns `waiting: true`.
- `GET /api/agent/review`

## What could I be wrong about?

The local scorer is not a forecast. Jev's published latency is the vendor's own figure, not a measurement from this machine. BTC and ETH levels in the research note disagree across sources by a few hundred dollars on the same date. A paper fill is not a live fill. Turning `AGENT_ARMED` on still does not connect an exchange.
