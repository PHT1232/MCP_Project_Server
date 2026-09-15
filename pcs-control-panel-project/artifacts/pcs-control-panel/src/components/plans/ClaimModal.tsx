import { useState } from 'react';
import { Loader2, X } from 'lucide-react';
import { Button, Field } from '../../App';

const DEFAULT_LEASE_SECONDS = 1800;

export interface ClaimModalProps {
  taskLabel: string;
  reclaim: boolean;
  pending: boolean;
  onSubmit: (claimedBy: string, leaseSeconds: number) => void;
  onClose: () => void;
}

/** Captures `claimed_by` + lease duration before an initial claim or a reclaim of an expired lease (FR47). */
export function ClaimModal({ taskLabel, reclaim, pending, onSubmit, onClose }: ClaimModalProps) {
  const [claimedBy, setClaimedBy] = useState('');
  const [leaseSeconds, setLeaseSeconds] = useState(String(DEFAULT_LEASE_SECONDS));
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    const trimmed = claimedBy.trim();
    const seconds = Number(leaseSeconds);
    if (!trimmed) {
      setError('Claimant name is required.');
      return;
    }
    if (!Number.isFinite(seconds) || seconds <= 0) {
      setError('Lease seconds must be a positive number.');
      return;
    }
    setError(null);
    onSubmit(trimmed, seconds);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#17292f]/40 p-4" onClick={onClose}>
      <div
        data-testid="modal-claim-task"
        role="dialog"
        aria-modal="true"
        aria-labelledby="claim-modal-title"
        className="w-full max-w-sm rounded-lg border border-[#d8dcd5] bg-[#faf9f4] p-5 shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 id="claim-modal-title" className="text-base font-bold">{reclaim ? 'Reclaim task' : 'Claim task'}</h2>
          <button data-testid="button-close-claim-modal" onClick={onClose} className="rounded p-1 text-[#879397] hover:bg-[#e8edff]"><X size={16} /></button>
        </div>
        <p className="mt-1 text-xs text-[#7d898d]">{taskLabel}</p>
        <div className="mt-4 space-y-3">
          <Field testId="input-claimed-by" label="Claimed by" value={claimedBy} onChange={setClaimedBy} placeholder="e.g. agent-7 or your name" />
          <Field testId="input-lease-seconds" label="Lease duration (seconds)" value={leaseSeconds} onChange={setLeaseSeconds} type="number" hint="How long before this claim can be reclaimed by another worker." />
          {error && <p className="text-xs text-[#97433d]">{error}</p>}
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <Button testId="button-cancel-claim" variant="quiet" size="sm" onClick={onClose}>Cancel</Button>
          <Button testId="button-submit-claim" size="sm" onClick={submit} disabled={pending}>
            {pending ? <Loader2 className="animate-spin" size={13} /> : null}
            {reclaim ? 'Reclaim' : 'Claim'}
          </Button>
        </div>
      </div>
    </div>
  );
}
