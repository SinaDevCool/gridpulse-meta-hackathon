# Berlin grid-capacity evidence audit

**Decision:** Public evidence is insufficient for available-MW claims at grid nodes.

## Output sufficiency

| Output | Status | Missing mandatory inputs |
|---|---|---|
| constraint_screening | conditionally_sufficient | geographic_attribution |
| relative_node_ranking | insufficient | benchmark_validation, comparable_demand_estimates, scenario_sensitivity_testing |
| capacity_bands | insufficient | contracted_queued_demand, electrical_parameters, equipment_ratings, existing_demand, n_minus_one_policy, operator_validation_or_outcomes, switching_state |

## Registered sources

- **SimBench consortium — simbench_datasets**: synthetic_demonstration; prohibited for berlin_live_capacity.
- **Stromnetz Berlin GmbH — stromnetz_berlin_enwg**: operator_published; prohibited for nodal_headroom, connection_feasibility.
- **Stromnetz Berlin GmbH — stromnetz_berlin_repartierung**: operator_published; prohibited for current_residual_capacity, nodal_headroom.
- **Stromnetz Berlin GmbH — stromnetz_berlin_allocation_2025**: operator_published; prohibited for current_residual_capacity, nodal_headroom.
- **Stromnetz Berlin GmbH — stromnetz_berlin_kraftnav**: operator_published; prohibited for branch_ratings, nodal_headroom.
- **Stromnetz Berlin GmbH — stromnetz_berlin_hv_requirements**: operator_published; prohibited for nodal_headroom.
- **Deutscher Wetterdienst Climate Data Center — dwd_hourly_climate**: operator_published; prohibited for grid_capacity, grid_feasibility.
- **ENTSO-E Transparency Platform — entsoe_outage_api**: operator_published; prohibited for substation_headroom, unreported_outage_inference.
- **50Hertz Transmission GmbH — fifty_hertz_congestion**: constraint_detected; prohibited for distribution_nodal_headroom.
- **Bundesnetzagentur — smard_download_center**: operator_published; prohibited for substation_loading, nodal_headroom.
- **VNBdigital — vnbdigital_network_plans**: planned_reinforcement; prohibited for live_capacity.
- **Geofabrik GmbH / OpenStreetMap contributors — geofabrik_germany**: public_screening; prohibited for capacity, feasibility, official_coordinates.
- **Deutscher Wetterdienst — dwd_open_data**: operator_published; prohibited for nodal_headroom, connection_feasibility.
- **ENTSO-E — entsoe_transparency**: operator_published; prohibited for distribution_nodal_headroom, connection_feasibility.
- **TenneT TSO GmbH — tennet_transparency**: constraint_detected; prohibited for distribution_nodal_headroom, connection_feasibility.
- **Amprion GmbH — amprion_transparency**: constraint_detected; prohibited for distribution_nodal_headroom, connection_feasibility.
- **wesernetz Bremen GmbH — wesernetz_publications**: operator_published; prohibited for live_capacity, nodal_headroom.
- **E.DIS Netz GmbH — edis_publications**: operator_published; prohibited for live_capacity, nodal_headroom.

## Release boundary

No public, mapped, synthetic, congestion, allocation, or reinforcement record is reported as available connection capacity. Unknown information remains unknown.
