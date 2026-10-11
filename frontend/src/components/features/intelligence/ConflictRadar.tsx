import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, Link2, RefreshCw, Radar } from 'lucide-react';
import { Button } from '../../shared/ui/button';
import { Badge } from '../../shared/ui/badge';
import { conflictRadarApi, type Conflict, type ConflictReport } from '../../../services/conflictRadarApi';

interface ContractOption {
  contract_id: string;
  filename: string;
}

interface ConflictRadarProps {
  contractId: string;
  model: string;
  /** Other known contracts, offered as governing-contract suggestions */
  contractOptions: ContractOption[];
}

const SEVERITY_STYLES: Record<Conflict['severity'], string> = {
  HIGH: 'bg-red-100 text-red-800',
  MEDIUM: 'bg-yellow-100 text-yellow-800',
  LOW: 'bg-slate-100 text-slate-700',
};

const label = (value: string) => value.replace(/_/g, ' ');

const ClauseColumn: React.FC<{ title: string; clause: Conflict['clause'] }> = ({ title, clause }) => (
  <div className="flex-1 min-w-0 rounded-md border border-slate-200 bg-slate-50 p-3">
    <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</p>
    {clause.clause_type && <p className="mt-1 text-xs text-slate-500">{clause.clause_type}</p>}
    <p className="mt-2 text-sm text-slate-800 whitespace-pre-wrap break-words">{clause.content || '—'}</p>
  </div>
);

const ConflictCard: React.FC<{ conflict: Conflict }> = ({ conflict }) => (
  <div className="rounded-lg border border-slate-200 p-4 space-y-3">
    <div className="flex flex-wrap items-center gap-2">
      <Badge className={SEVERITY_STYLES[conflict.severity] ?? SEVERITY_STYLES.MEDIUM}>{conflict.severity}</Badge>
      <span className="text-sm font-medium text-slate-800 capitalize">{label(conflict.conflict_type)}</span>
    </div>
    <p className="text-sm text-slate-700">{conflict.explanation}</p>
    <div className="flex flex-col md:flex-row gap-3">
      <ClauseColumn title="This contract" clause={conflict.clause} />
      <ClauseColumn title="Governing contract" clause={conflict.governing_clause} />
    </div>
    {conflict.suggested_resolution && (
      <p className="text-sm text-slate-700">
        <span className="font-semibold">Suggested fix: </span>{conflict.suggested_resolution}
      </p>
    )}
    {conflict.verification_reason && (
      <p className="text-xs text-slate-500">Verified: {conflict.verification_reason}</p>
    )}
  </div>
);

export const ConflictRadar: React.FC<ConflictRadarProps> = ({ contractId, model, contractOptions }) => {
  const [report, setReport] = useState<ConflictReport | null>(null);
  const [governingInput, setGoverningInput] = useState('');
  const [busy, setBusy] = useState<'loading' | 'linking' | 'checking' | null>('loading');
  const [error, setError] = useState<string | null>(null);
  // Responses for a contract the user has since navigated away from are dropped
  const latestContractId = useRef(contractId);
  const showReport = useCallback((id: string, next: ConflictReport) => {
    if (latestContractId.current === id) setReport(next);
  }, []);

  const run = useCallback(async (state: 'loading' | 'linking' | 'checking', action: () => Promise<void>) => {
    setBusy(state);
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }, []);

  useEffect(() => {
    latestContractId.current = contractId;
    setReport(null);
    setGoverningInput('');
    run('loading', async () => showReport(contractId, await conflictRadarApi.getConflicts(contractId)));
  }, [contractId, run, showReport]);

  const link = () =>
    run('linking', async () => {
      await conflictRadarApi.linkGoverningContract(contractId, governingInput.trim());
      setGoverningInput('');
      showReport(contractId, await conflictRadarApi.getConflicts(contractId));
    });

  const check = () =>
    run('checking', async () => showReport(contractId, await conflictRadarApi.checkConflicts(contractId, model)));

  const options = contractOptions.filter((c) => c.contract_id !== contractId);
  const governing = report?.governing_contract;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Radar className="w-5 h-5 text-indigo-600" />
        <h3 className="text-lg font-semibold text-slate-800">Cross-Contract Conflict Radar</h3>
      </div>
      <p className="text-sm text-slate-600">
        Link this contract (for example a SOW) to the contract that governs it (for example an MSA), then check
        both for clauses that contradict each other.
      </p>

      <div className="rounded-lg border border-slate-200 p-4 space-y-3">
        <p className="text-sm text-slate-700">
          <span className="font-semibold">Governing contract: </span>
          {governing ? `${governing.name} (${governing.contract_id})` : 'not linked'}
        </p>
        <div className="flex flex-col sm:flex-row gap-2">
          <input
            list="conflict-radar-contracts"
            value={governingInput}
            onChange={(e) => setGoverningInput(e.target.value)}
            placeholder="Governing contract ID"
            aria-label="Governing contract ID"
            className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
          <datalist id="conflict-radar-contracts">
            {options.map((c) => (
              <option key={c.contract_id} value={c.contract_id}>{c.filename}</option>
            ))}
          </datalist>
          <Button variant="outline" onClick={link} disabled={!governingInput.trim() || busy !== null}>
            <Link2 /> {governing ? 'Change link' : 'Link'}
          </Button>
        </div>
      </div>

      <Button onClick={check} disabled={!governing || busy !== null} className="w-full">
        <RefreshCw className={busy === 'checking' ? 'animate-spin' : ''} />
        {busy === 'checking' ? 'Checking clauses…' : 'Check for conflicts'}
      </Button>

      {error && (
        <div className="flex items-start gap-2 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" /> {error}
        </div>
      )}

      {busy === 'loading' && <p className="text-sm text-slate-500">Loading conflict results…</p>}

      {report && report.status !== 'not_run' && busy !== 'checking' && (
        <div className="space-y-3">
          <p className="text-sm text-slate-600">
            {report.conflicts.length} conflict{report.conflicts.length === 1 ? '' : 's'} found across{' '}
            {report.pairs_checked} compared clause pair{report.pairs_checked === 1 ? '' : 's'}
            {report.checked_at && ` · checked ${new Date(report.checked_at).toLocaleString()}`}
          </p>
          {report.status === 'partial' && (
            <p className="text-sm text-yellow-700">
              {report.pairs_failed} clause pair{report.pairs_failed === 1 ? '' : 's'} could not be checked; results may
              be incomplete. Run the check again to retry.
            </p>
          )}
          {report.pairs_truncated && (
            <p className="text-sm text-yellow-700">
              This contract has more comparable clause pairs than one check covers; only the{' '}
              {report.pairs_checked} closest matches were compared.
            </p>
          )}
          {report.pairs_checked === 0 ? (
            // Nothing compared is not the same as "no conflicts": never show it as a clean result
            <div className="flex items-start gap-2 rounded-md border border-yellow-200 bg-yellow-50 p-3 text-sm text-yellow-800">
              <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
              <span>
                No clauses could be compared, so this does not mean the contracts agree. None of the clauses extracted
                from this contract matched a clause type in the governing contract. Clause extraction currently
                recognises only a few clause types, so some clauses may not have been found.
              </span>
            </div>
          ) : report.conflicts.length === 0 && report.status === 'partial' ? (
            // Some pairs were never judged, so an empty list is not a clean result
            <div className="flex items-start gap-2 rounded-md border border-yellow-200 bg-yellow-50 p-3 text-sm text-yellow-800">
              <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
              <span>
                No conflicts found in the {report.pairs_checked - report.pairs_failed} pair
                {report.pairs_checked - report.pairs_failed === 1 ? '' : 's'} that could be checked, but{' '}
                {report.pairs_failed} could not be checked, so this is not a full result.
              </span>
            </div>
          ) : report.conflicts.length === 0 ? (
            <div className="flex items-center gap-2 text-sm text-green-700">
              <CheckCircle2 className="w-4 h-4" /> No conflicts found with the governing contract.
            </div>
          ) : (
            report.conflicts.map((c) => (
              <ConflictCard key={`${c.clause.clause_id}-${c.governing_clause.clause_id}`} conflict={c} />
            ))
          )}
        </div>
      )}
    </div>
  );
};
