"""
================================================================================
 Foundry IQ Tool - Agent-callable wrapper
================================================================================
 Exposes Foundry IQ grounded retrieval as a callable tool for reasoning agents.
================================================================================
"""

from services.foundry_iq_service import get_foundry_iq


def foundry_iq_lookup(query: str, context: str = "") -> str:
    """
    Tool: Look up grounded knowledge from Foundry IQ.

    Used by reasoning agents to fetch domain-specific context
    (COBOL patterns, validation rules, migration best practices).

    Args:
        query: What to look up.
        context: Optional surrounding context.

    Returns:
        Formatted grounded knowledge string for prompt injection.
    """
    service = get_foundry_iq()
    return service.ground_reasoning_step(
        step_name=f"agent_lookup::{query[:40]}",
        input_data=context or query,
    )


def foundry_iq_status() -> dict:
    """Tool: Check Foundry IQ health & configuration."""
    service = get_foundry_iq()
    return {
        "enabled": service.enabled,
        "endpoint": service.endpoint or "not-configured",
        "healthy": service.health_check(),
    }
