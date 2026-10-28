# Production integration boundary

The production integration contract is directional:

```text
gridpulse-grid-core -> gridpulse-capacity-backtest -> production analytics service -> web UI
```

This repository is the canonical owner of analytical domain calculations. It does not own web
authentication, project persistence, job scheduling, customer-facing UI or command transport.
Production calls the stable application API and consumes immutable, versioned result contracts.

The former local `src/grid_data` compatibility copy has been removed. Network contracts,
providers and source parsers come from the pinned `gridpulse-grid-core` distribution. No
additional `grid_data` source may be copied into this repository.

Application adapters may translate request and result contracts. They may not reproduce capacity,
planning, uncertainty, economics, settlement, shadow or verification calculations.
