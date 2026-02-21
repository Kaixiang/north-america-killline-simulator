# north-america-killline-simulator

## Game design draft

A structured Chinese design draft for **Kill Line: North America** is available at:

- `docs/game_design_zh.md`

## Build progress: annual simulation prototype

A playable annual-loop prototype (25-year survival model) is now available:

- `annual_sim.py`

Run:

```bash
python annual_sim.py --years 25 --seed 42
```

This prototype implements:

- Macro cycle transitions (Boom / Tightening / Recession) with trend persistence.
- Annual income/expense settlement.
- Asset volatility and cycle-linked returns.
- Fragility model and annual risk checks.
- Bankruptcy trigger (`cash < 0` for 2 consecutive years).
- Endgame scoring (max drawdown, average risk exposure, stability, net worth).
