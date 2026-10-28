# Operator-territory backtest

GridPulse resolves a site's probable geographic DSO before a real-site capacity study. The
resolution is an evidence-governed screening result, not a connection offer, PCC assignment, or
capacity claim.

## Pipeline

1. Replay a captured, hashed site location. Historical runs never call a live geocoder.
2. Select only territory releases valid at the decision time and available by the evidence cutoff.
3. Match the point or parcel against valid Polygon/MultiPolygon geometry.
4. Quarantine boundaries, overlaps, polygon holes, cross-operator parcels, and location uncertainty.
5. Reconcile the operator against a captured MaStR network-operator registry, identifiers first.
6. Flag closed/private/railway/campus/direct-TSO exceptions for review.
7. Require reviewed operator evidence for responsibility, PCC, and study-outcome authorization.
8. Permit a physical nodal run only when the network operator and confirmed PCC agree.

## Truth boundary

- A territory match may identify a probable geographic DSO.
- Requested MW never assigns a TSO.
- A confirmed geographic operator does not establish voltage, PCC, capacity, cost, or date.
- Only a valid `connection_study_outcome` or stronger operator confirmation can authorize an
  operator-confirmed capacity comparison.

## Commands

```powershell
capacity-backtest territory validate-location captured-location.json
capacity-backtest territory ingest-geojson boundaries.geojson release.json `
  --source-id official-boundaries --source-url https://example.invalid/source `
  --licence "approved licence" --retrieved-at 2025-01-01T00:00:00Z
capacity-backtest territory resolve captured-location.json release.json mastr-operators.xml `
  --decision-time 2025-02-01T00:00:00Z --evidence-cutoff 2025-01-01T00:00:00Z `
  --registry-published-at 2024-12-30T00:00:00Z `
  --registry-retrieved-at 2025-01-01T00:00:00Z --requested-mw 80 --output result.json
capacity-backtest territory backtest historical-cases.json predictions.json
```

Do not scrape VNBdigital without an approved machine-readable interface and reuse basis. The
crosswalk parser accepts reviewed exports and deliberately cannot create a capacity claim.

## Release gates

Promotion requires zero historical evidence leakage and zero incorrect confident matches. Boundary
cases must never auto-confirm an operator, and no operator-confirmed state may exist without a
reviewed, hashed operator document within its validity and scope.
