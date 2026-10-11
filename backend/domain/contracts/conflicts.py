"""Domain types for the Cross-Contract Conflict Radar.

A child contract (for example a SOW) is linked to the contract that governs it
(for example an MSA). Candidate clause pairs are drawn from the two contracts,
judged by an LLM, double-checked, and the confirmed conflicts are stored.
"""
from dataclasses import dataclass, field
from typing import List

CONFLICT_TYPES = (
    "contradictory_obligation",
    "inconsistent_amount",
    "inconsistent_timeline",
    "conflicting_definition",
    "conflicting_governing_law",
    "other",
)
SEVERITIES = ("LOW", "MEDIUM", "HIGH")


@dataclass(frozen=True)
class ClauseRef:
    clause_id: str
    clause_type: str
    content: str


@dataclass(frozen=True)
class ClausePair:
    """A clause from the child contract and one from its governing contract."""
    clause: ClauseRef
    governing_clause: ClauseRef


@dataclass(frozen=True)
class ConflictFinding:
    pair: ClausePair
    conflict_type: str
    severity: str
    explanation: str
    suggested_resolution: str
    verification_reason: str


@dataclass
class ConflictCheckResult:
    contract_id: str
    governing_contract_id: str
    pairs_checked: int
    pairs_failed: int
    findings: List[ConflictFinding] = field(default_factory=list)
    # True when more candidate pairs existed than were checked (per-check cost cap)
    pairs_truncated: bool = False

    @property
    def status(self) -> str:
        return "partial" if self.pairs_failed else "completed"
