# Review log, 2026-10-20

- Jev's decide endpoint is documented at https://jevtypesafeai.com/jev/trading as POST /api/v1/decide with a jv_live_ key. This machine has no key, so the reflex does not call it.
- agentkit.xyz returned a gateway timeout. No package was installed from there.
- The Hugging Face model named for a later local load is HuggingFaceTB/SmolLM2-135M-Instruct. It is small enough to sit on CPU, and it is not loaded during the default paper tick. The default scorer is local and tested.
- Tests cover a future timestamp leak, a 20% drawdown, a weak setup, a crisis escalation, and a disarmed high-confidence decision. The last one must not fire.
- Paper ticks append to data/agent_journal.jsonl. That file is local and is not part of the public source tree.

## What could I be wrong about?

The edge, if any, is not shown. A one-day down move is not a regime. Dominance feeds differ by about one point. Quarter-Kelly on a made-up probability is still made up. Slippage and fees are not in the paper fill. The 5% daily-loss and 10% position caps are local choices, not figures from the market pages. Leaving the switch disarmed is the point: a system that cannot send an order cannot lose money it does not have on an exchange.
