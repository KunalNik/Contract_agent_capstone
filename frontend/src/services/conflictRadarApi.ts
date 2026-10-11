// Cross-Contract Conflict Radar API client.
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '';

export interface ConflictClause {
  clause_id: string;
  clause_type: string | null;
  content: string | null;
}

export interface Conflict {
  conflict_type: string;
  severity: 'LOW' | 'MEDIUM' | 'HIGH';
  explanation: string;
  suggested_resolution: string;
  verification_reason: string;
  detected_at: string | null;
  clause: ConflictClause;
  governing_clause: ConflictClause;
}

export interface GoverningContract {
  contract_id: string;
  name: string;
}

export interface ConflictReport {
  contract_id: string;
  governing_contract: GoverningContract | null;
  status: 'not_run' | 'completed' | 'partial';
  checked_at: string | null;
  pairs_checked: number;
  pairs_failed: number;
  pairs_truncated: boolean;
  conflicts: Conflict[];
}

const contractUrl = (contractId: string) =>
  `${API_BASE_URL}/api/intelligence/contracts/${encodeURIComponent(contractId)}`;

async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `Request failed (${response.status})`);
  }
  return response.json();
}

export const conflictRadarApi = {
  getConflicts: (contractId: string) =>
    fetch(`${contractUrl(contractId)}/conflicts`).then((r) => parse<ConflictReport>(r)),

  linkGoverningContract: (contractId: string, governingContractId: string) =>
    fetch(`${contractUrl(contractId)}/governing-contract`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ governing_contract_id: governingContractId }),
    }).then((r) => parse<{ contract_id: string; governing_contract: GoverningContract | null }>(r)),

  checkConflicts: (contractId: string, model: string) =>
    fetch(`${contractUrl(contractId)}/conflicts?model=${encodeURIComponent(model)}`, { method: 'POST' })
      .then((r) => parse<ConflictReport>(r)),
};
