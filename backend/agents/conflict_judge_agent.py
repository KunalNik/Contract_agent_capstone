"""LLM judge for clause conflicts between a contract and its governing contract.

Two passes per candidate pair, because single-pass LLM conflict detection
produces many false positives:
  1. judge  - does this pair conflict, and how?
  2. verify - a skeptical second look at a flagged conflict; only confirmed
              conflicts are reported.
"""
from typing import Any, Optional

from backend.domain.contracts.conflicts import CONFLICT_TYPES, SEVERITIES, ClausePair, ConflictFinding
from backend.governance.llm_judge import ask_json
from backend.shared.utils.logger import get_logger

logger = get_logger(__name__)

MAX_CLAUSE_CHARS = 1500

JUDGE_INSTRUCTION = (
    "You are a contracts lawyer checking a subordinate contract (for example a statement of work) "
    "against the contract that governs it (for example a master services agreement). "
    "Decide whether the two clauses below CONFLICT: they cannot both be complied with, or they set "
    "different values for the same term (amounts, caps, deadlines, payment periods, governing law, "
    "definitions). Clauses that are merely different in wording, or where one only adds detail "
    "consistent with the other, do NOT conflict. "
    f"conflict_type must be one of: {', '.join(CONFLICT_TYPES)}. "
    f"severity must be one of: {', '.join(SEVERITIES)}. "
    'Respond ONLY with JSON: {"conflict": true|false, "conflict_type": "...", "severity": "...", '
    '"explanation": "one or two sentences quoting the conflicting terms", '
    '"suggested_resolution": "a concrete edit that removes the conflict"}'
)

VERIFY_INSTRUCTION = (
    "You are a skeptical senior contracts lawyer reviewing a junior colleague's finding. "
    "Confirm the conflict ONLY if the two clauses genuinely govern the same subject and their terms "
    "cannot both apply. Reject it if the clauses address different subjects, if one is consistent "
    "with or merely more specific than the other, or if the finding misreads the text. "
    'Respond ONLY with JSON: {"confirmed": true|false, "reason": "one sentence"}'
)


def _clip(text: str) -> str:
    return text if len(text) <= MAX_CLAUSE_CHARS else text[:MAX_CLAUSE_CHARS] + " [...]"


def _pair_text(pair: ClausePair) -> str:
    return (
        f"SUBORDINATE CONTRACT CLAUSE ({pair.clause.clause_type or 'unclassified'}):\n"
        f"{_clip(pair.clause.content)}\n\n"
        f"GOVERNING CONTRACT CLAUSE ({pair.governing_clause.clause_type or 'unclassified'}):\n"
        f"{_clip(pair.governing_clause.content)}"
    )


def _is_true(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.strip().lower() == "true")


class ConflictJudge:
    def __init__(self, llm):
        self.llm = llm

    def assess(self, pair: ClausePair) -> Optional[ConflictFinding]:
        """Return a confirmed finding, or None. LLM or parsing errors propagate."""
        pair_text = _pair_text(pair)
        verdict = ask_json(JUDGE_INSTRUCTION, pair_text, llm=self.llm)
        if not _is_true(verdict.get("conflict")):
            return None

        conflict_type = verdict.get("conflict_type") if verdict.get("conflict_type") in CONFLICT_TYPES else "other"
        severity = str(verdict.get("severity", "")).upper()
        severity = severity if severity in SEVERITIES else "MEDIUM"
        explanation = str(verdict.get("explanation", "")).strip()

        check = ask_json(
            VERIFY_INSTRUCTION,
            f"{pair_text}\n\nFINDING ({conflict_type}, {severity}): {explanation}",
            llm=self.llm,
        )
        if not _is_true(check.get("confirmed")):
            logger.info(f"Conflict rejected on verification: {pair.clause.clause_id} vs "
                        f"{pair.governing_clause.clause_id}")
            return None

        return ConflictFinding(
            pair=pair,
            conflict_type=conflict_type,
            severity=severity,
            explanation=explanation,
            suggested_resolution=str(verdict.get("suggested_resolution", "")).strip(),
            verification_reason=str(check.get("reason", "")).strip(),
        )
