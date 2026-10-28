# Output classification contract

1. **Public constraint context** — may state that a publisher reported upstream congestion, with
   source, time, revision and geographic resolution. It may not state available MW.
2. **Probabilistic regional risk** — may report a calibrated future-event probability only after
   temporal validation and a passed release gate. Current status: unavailable.
3. **Synthetic flexibility study** — may compare constrained hours and bounded dispatch only with
   the `synthetic_benchmark` label. It is not a real-network result.
4. **Operator-confirmed capacity** — may state confirmed available connection MW only from
   operator-confirmed evidence. Current status: unavailable.

Values and prose must never be promoted or blended across these layers.
