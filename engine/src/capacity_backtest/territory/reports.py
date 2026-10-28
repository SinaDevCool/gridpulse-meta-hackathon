"""Human-readable territory-resolution reporting."""

from __future__ import annotations


def render_resolution_markdown(result: dict[str, object]) -> str:
    limitations = "\n".join(f"- {item}" for item in result.get("limitations", []))
    return f"""# GridPulse operator-territory resolution

- Site: `{result.get('site_id')}`
- Status: **{result.get('status')}**
- Geographic DSO ID: `{result.get('geographic_dso') or 'unresolved'}`
- Candidate connection operator: `{result.get('candidate_connection_operator') or 'unresolved'}`
- Public screening allowed: **{result.get('public_screening_allowed')}**
- Physical nodal run allowed: **{result.get('physical_nodal_run_allowed')}**
- Operator-confirmed claim allowed: **{result.get('operator_confirmed_claim_allowed')}**

## Limitations

{limitations or '- None recorded'}
"""
