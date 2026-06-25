"""Agent runtime registry and doctor checks."""

from .registry import (
    AGENT_SPECS,
    AgentCompatibility,
    DispatchReadiness,
    AgentSpec,
    CommandOutput,
    DoctorCheck,
    DoctorResult,
    assess_agent_compatibility,
    assess_dispatch_readiness,
    doctor_agent,
    get_agent_spec,
    list_agent_compatibility,
    list_agent_specs,
)

__all__ = [
    "AGENT_SPECS",
    "AgentCompatibility",
    "DispatchReadiness",
    "AgentSpec",
    "CommandOutput",
    "DoctorCheck",
    "DoctorResult",
    "assess_agent_compatibility",
    "assess_dispatch_readiness",
    "doctor_agent",
    "get_agent_spec",
    "list_agent_compatibility",
    "list_agent_specs",
]
