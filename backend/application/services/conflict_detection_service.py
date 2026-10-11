"""Cross-Contract Conflict Radar: link contracts and detect conflicting clauses."""
import contextvars
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

from backend.agents.conflict_judge_agent import ConflictJudge
from backend.domain.contracts.conflicts import ClausePair, ConflictCheckResult, ConflictFinding
from backend.infrastructure.conflict_repository import ConflictRepository
from backend.shared.utils.logger import get_logger

logger = get_logger(__name__)

# Candidate selection bounds: pairs above this similarity are judged even when
# their clause types differ; the cap keeps LLM cost per check predictable.
MIN_SIMILARITY = 0.80
MAX_PAIRS = 25
MAX_WORKERS = 4


class ContractNotFoundError(Exception):
    pass


class GoverningContractNotLinkedError(Exception):
    pass


class ConflictDetectionFailedError(Exception):
    pass


class ConflictDetectionService:
    def __init__(self, repository: Optional[ConflictRepository] = None):
        self.repository = repository or ConflictRepository()

    def link_governing_contract(self, contract_id: str, governing_contract_id: str, tenant_id: str) -> Dict[str, Any]:
        if contract_id == governing_contract_id:
            raise ValueError("A contract cannot govern itself")
        if not self.repository.link_governing_contract(contract_id, governing_contract_id, tenant_id):
            raise ContractNotFoundError(f"Contract {contract_id} or {governing_contract_id} not found")
        logger.info(f"Linked contract {contract_id} to governing contract {governing_contract_id}")
        return {"contract_id": contract_id,
                "governing_contract": self.repository.get_governing_contract(contract_id, tenant_id)}

    def detect_conflicts(self, contract_id: str, tenant_id: str, judge: ConflictJudge,
                         model: str) -> ConflictCheckResult:
        """Blocking: run from a worker thread. Replaces previously stored results."""
        if not self.repository.contract_exists(contract_id, tenant_id):
            raise ContractNotFoundError(f"Contract {contract_id} not found")
        governing = self.repository.get_governing_contract(contract_id, tenant_id)
        if not governing:
            raise GoverningContractNotLinkedError(
                f"Contract {contract_id} has no governing contract; link one first")

        # One extra row tells us whether the cap cut anything off
        pairs = self.repository.find_candidate_pairs(contract_id, tenant_id, MIN_SIMILARITY, MAX_PAIRS + 1)
        truncated = len(pairs) > MAX_PAIRS
        pairs = pairs[:MAX_PAIRS]
        logger.info(f"Conflict check for {contract_id} against {governing['contract_id']}: "
                    f"{len(pairs)} candidate pairs{' (capped)' if truncated else ''}")

        findings, failed = self._assess_all(pairs, judge)
        if pairs and failed == len(pairs):
            # Every judgement failed: don't report (or store) this as "no conflicts"
            raise ConflictDetectionFailedError(f"All {failed} clause comparisons failed; see server logs")

        result = ConflictCheckResult(
            contract_id=contract_id,
            governing_contract_id=governing["contract_id"],
            pairs_checked=len(pairs),
            pairs_failed=failed,
            findings=findings,
            pairs_truncated=truncated,
        )
        self.repository.save_results(result, tenant_id, model)
        return result

    def get_conflicts(self, contract_id: str, tenant_id: str) -> Dict[str, Any]:
        stored = self.repository.get_results(contract_id, tenant_id)
        if stored is None:
            raise ContractNotFoundError(f"Contract {contract_id} not found")
        return {
            "contract_id": contract_id,
            "governing_contract": self.repository.get_governing_contract(contract_id, tenant_id),
            "status": stored.get("status") or "not_run",
            "checked_at": stored.get("checked_at"),
            "pairs_checked": stored.get("pairs_checked") or 0,
            "pairs_failed": stored.get("pairs_failed") or 0,
            "pairs_truncated": bool(stored.get("pairs_truncated")),
            "conflicts": stored.get("conflicts") or [],
        }

    @staticmethod
    def _assess_all(pairs: List[ClausePair], judge: ConflictJudge) -> Tuple[List[ConflictFinding], int]:
        def assess(pair: ClausePair) -> Optional[ConflictFinding]:
            try:
                return judge.assess(pair)
            except Exception as e:
                logger.error(f"Conflict judgement failed for {pair.clause.clause_id} vs "
                             f"{pair.governing_clause.clause_id}: {e}")
                raise

        findings: List[ConflictFinding] = []
        failed = 0
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            # A fresh context copy per task keeps correlation and tenant ids in worker logs
            futures = [pool.submit(contextvars.copy_context().run, assess, pair) for pair in pairs]
            for future in futures:
                try:
                    finding = future.result()
                except Exception:
                    failed += 1
                    continue
                if finding:
                    findings.append(finding)
        return findings, failed
