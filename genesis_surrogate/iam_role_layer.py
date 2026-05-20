"""
iam_role_layer.py — Phase 5: IAM / Role Hierarchy + Tool Permission Map

Implements the surrogate IAM layer from the Part IV table in the whitepaper:
    - Mock identities, roles, approval powers, scope boundaries
    - Versioned SOPs as authoritative ground truth
    - Tool/API permission maps (None, read, propose, approve, execute, emergency_override)
    - Source trust zones (Z_CORE_TRUST, Z_VENDOR, Z_PUBLIC, Z_UNTRUSTED)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional


class PermissionLevel(str, Enum):
    NONE               = "none"
    READ               = "read"
    PROPOSE            = "propose"
    APPROVE            = "approve"
    EXECUTE            = "execute"
    EMERGENCY_OVERRIDE = "emergency_override"


class TrustZone(str, Enum):
    Z_CORE_TRUST = "Z_CORE_TRUST"   # Internal verified operators
    Z_VENDOR     = "Z_VENDOR"       # External vendors / maintenance
    Z_PUBLIC     = "Z_PUBLIC"       # Public-facing channels
    Z_UNTRUSTED  = "Z_UNTRUSTED"    # Unknown / adversarial sources


class RoleID(str, Enum):
    SUPPORT_AGENT    = "SUPPORT_AGENT"
    SUPERVISOR       = "SUPERVISOR"
    GRID_OPERATOR    = "GRID_OPERATOR"
    OT_ADMIN         = "OT_ADMIN"
    SECURITY_ANALYST = "SECURITY_ANALYST"
    EMERGENCY_COORD  = "EMERGENCY_COORD"


class ActionID(str, Enum):
    RESET_PASSWORD      = "RESET_PASSWORD"
    RUN_SCRIPT          = "RUN_SCRIPT"
    MODIFY_TRIP_SETTING = "MODIFY_TRIP_SETTING"   # High-sensitivity OT action
    SHED_LOAD           = "SHED_LOAD"             # High-sensitivity OT action
    READ_TELEMETRY      = "READ_TELEMETRY"
    ACKNOWLEDGE_ALARM   = "ACKNOWLEDGE_ALARM"
    MODIFY_SETPOINT     = "MODIFY_SETPOINT"
    ISOLATE_ASSET       = "ISOLATE_ASSET"
    EMERGENCY_TRIP      = "EMERGENCY_TRIP"        # Requires emergency_override


# ---------------------------------------------------------------------------
# Permission matrix: role → action → minimum permission level granted
# ---------------------------------------------------------------------------
PERMISSION_MATRIX: Dict[RoleID, Dict[ActionID, PermissionLevel]] = {
    RoleID.SUPPORT_AGENT: {
        ActionID.RESET_PASSWORD:      PermissionLevel.EXECUTE,
        ActionID.READ_TELEMETRY:      PermissionLevel.READ,
        ActionID.ACKNOWLEDGE_ALARM:   PermissionLevel.PROPOSE,
        ActionID.RUN_SCRIPT:          PermissionLevel.NONE,
        ActionID.MODIFY_TRIP_SETTING: PermissionLevel.NONE,
        ActionID.SHED_LOAD:           PermissionLevel.NONE,
        ActionID.MODIFY_SETPOINT:     PermissionLevel.NONE,
        ActionID.ISOLATE_ASSET:       PermissionLevel.NONE,
        ActionID.EMERGENCY_TRIP:      PermissionLevel.NONE,
    },
    RoleID.SUPERVISOR: {
        ActionID.RESET_PASSWORD:      PermissionLevel.EXECUTE,
        ActionID.READ_TELEMETRY:      PermissionLevel.READ,
        ActionID.ACKNOWLEDGE_ALARM:   PermissionLevel.APPROVE,
        ActionID.RUN_SCRIPT:          PermissionLevel.APPROVE,
        ActionID.MODIFY_TRIP_SETTING: PermissionLevel.PROPOSE,
        ActionID.SHED_LOAD:           PermissionLevel.PROPOSE,
        ActionID.MODIFY_SETPOINT:     PermissionLevel.APPROVE,
        ActionID.ISOLATE_ASSET:       PermissionLevel.PROPOSE,
        ActionID.EMERGENCY_TRIP:      PermissionLevel.NONE,
    },
    RoleID.GRID_OPERATOR: {
        ActionID.RESET_PASSWORD:      PermissionLevel.NONE,
        ActionID.READ_TELEMETRY:      PermissionLevel.READ,
        ActionID.ACKNOWLEDGE_ALARM:   PermissionLevel.EXECUTE,
        ActionID.RUN_SCRIPT:          PermissionLevel.PROPOSE,
        ActionID.MODIFY_TRIP_SETTING: PermissionLevel.APPROVE,
        ActionID.SHED_LOAD:           PermissionLevel.EXECUTE,
        ActionID.MODIFY_SETPOINT:     PermissionLevel.EXECUTE,
        ActionID.ISOLATE_ASSET:       PermissionLevel.APPROVE,
        ActionID.EMERGENCY_TRIP:      PermissionLevel.PROPOSE,
    },
    RoleID.OT_ADMIN: {
        ActionID.RESET_PASSWORD:      PermissionLevel.EXECUTE,
        ActionID.READ_TELEMETRY:      PermissionLevel.READ,
        ActionID.ACKNOWLEDGE_ALARM:   PermissionLevel.EXECUTE,
        ActionID.RUN_SCRIPT:          PermissionLevel.EXECUTE,
        ActionID.MODIFY_TRIP_SETTING: PermissionLevel.EXECUTE,
        ActionID.SHED_LOAD:           PermissionLevel.EXECUTE,
        ActionID.MODIFY_SETPOINT:     PermissionLevel.EXECUTE,
        ActionID.ISOLATE_ASSET:       PermissionLevel.EXECUTE,
        ActionID.EMERGENCY_TRIP:      PermissionLevel.APPROVE,
    },
    RoleID.SECURITY_ANALYST: {
        ActionID.RESET_PASSWORD:      PermissionLevel.PROPOSE,
        ActionID.READ_TELEMETRY:      PermissionLevel.READ,
        ActionID.ACKNOWLEDGE_ALARM:   PermissionLevel.EXECUTE,
        ActionID.RUN_SCRIPT:          PermissionLevel.NONE,
        ActionID.MODIFY_TRIP_SETTING: PermissionLevel.NONE,
        ActionID.SHED_LOAD:           PermissionLevel.NONE,
        ActionID.MODIFY_SETPOINT:     PermissionLevel.NONE,
        ActionID.ISOLATE_ASSET:       PermissionLevel.PROPOSE,
        ActionID.EMERGENCY_TRIP:      PermissionLevel.NONE,
    },
    RoleID.EMERGENCY_COORD: {
        ActionID.RESET_PASSWORD:      PermissionLevel.EXECUTE,
        ActionID.READ_TELEMETRY:      PermissionLevel.READ,
        ActionID.ACKNOWLEDGE_ALARM:   PermissionLevel.EXECUTE,
        ActionID.RUN_SCRIPT:          PermissionLevel.APPROVE,
        ActionID.MODIFY_TRIP_SETTING: PermissionLevel.EMERGENCY_OVERRIDE,
        ActionID.SHED_LOAD:           PermissionLevel.EMERGENCY_OVERRIDE,
        ActionID.MODIFY_SETPOINT:     PermissionLevel.APPROVE,
        ActionID.ISOLATE_ASSET:       PermissionLevel.EMERGENCY_OVERRIDE,
        ActionID.EMERGENCY_TRIP:      PermissionLevel.EMERGENCY_OVERRIDE,
    },
}

# Source trust zone → maximum authority level an input from that zone may assert
TRUST_ZONE_AUTHORITY_CAP: Dict[TrustZone, PermissionLevel] = {
    TrustZone.Z_CORE_TRUST: PermissionLevel.EMERGENCY_OVERRIDE,
    TrustZone.Z_VENDOR:     PermissionLevel.PROPOSE,
    TrustZone.Z_PUBLIC:     PermissionLevel.READ,
    TrustZone.Z_UNTRUSTED:  PermissionLevel.NONE,
}


@dataclass
class AccessRequest:
    role_id: RoleID
    action_id: ActionID
    source_trust_zone: TrustZone
    requested_permission: PermissionLevel
    context: Optional[str] = None      # Free-text context for audit log
    grid_route: Optional[str] = None   # Genesis route at time of request


@dataclass
class AccessDecision:
    granted: bool
    reason: str
    effective_permission: PermissionLevel
    requires_human_review: bool = False
    audit_entry: str = ""


class IAMLayer:
    """Policy Enforcement Point (PEP) for OT actions gated by C3-ICM + Genesis."""

    def evaluate(self, req: AccessRequest) -> AccessDecision:
        role_perms = PERMISSION_MATRIX.get(req.role_id, {})
        granted_level = role_perms.get(req.action_id, PermissionLevel.NONE)
        trust_cap = TRUST_ZONE_AUTHORITY_CAP[req.source_trust_zone]

        # Trust zone caps the effective permission
        effective = self._min_permission(granted_level, trust_cap)

        # If Genesis is in DEEP_PATH, block all execute/override actions
        if req.grid_route == "DEEP_PATH" and req.requested_permission in (
            PermissionLevel.EXECUTE, PermissionLevel.EMERGENCY_OVERRIDE
        ):
            return AccessDecision(
                granted=False,
                reason="BLOCKED: Genesis DEEP_PATH active — grid telemetry exceeds safe threshold",
                effective_permission=PermissionLevel.NONE,
                requires_human_review=True,
                audit_entry=self._audit(req, False, "Genesis DEEP block"),
            )

        PERMISSION_ORDER = [
            PermissionLevel.NONE, PermissionLevel.READ, PermissionLevel.PROPOSE,
            PermissionLevel.APPROVE, PermissionLevel.EXECUTE, PermissionLevel.EMERGENCY_OVERRIDE
        ]
        granted = PERMISSION_ORDER.index(effective) >= PERMISSION_ORDER.index(req.requested_permission)
        reason = "GRANTED" if granted else f"DENIED: role grants {effective.value}, requested {req.requested_permission.value}"

        return AccessDecision(
            granted=granted,
            reason=reason,
            effective_permission=effective,
            requires_human_review=(not granted and req.requested_permission != PermissionLevel.NONE),
            audit_entry=self._audit(req, granted, reason),
        )

    def _min_permission(self, a: PermissionLevel, b: PermissionLevel) -> PermissionLevel:
        order = [
            PermissionLevel.NONE, PermissionLevel.READ, PermissionLevel.PROPOSE,
            PermissionLevel.APPROVE, PermissionLevel.EXECUTE, PermissionLevel.EMERGENCY_OVERRIDE
        ]
        return order[min(order.index(a), order.index(b))]

    def _audit(self, req: AccessRequest, granted: bool, reason: str) -> str:
        return (
            f"role={req.role_id.value} action={req.action_id.value} "
            f"zone={req.source_trust_zone.value} "
            f"requested={req.requested_permission.value} "
            f"grid_route={req.grid_route} "
            f"decision={'GRANT' if granted else 'DENY'} reason={reason}"
        )
