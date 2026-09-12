import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { onAuthStateChanged } from 'firebase/auth';
import { auth } from '@/auth/firebase';
import { apiClient as api, onSessionExpired, ModerationQueueItem, AgreementRate } from '@/lib/api-client';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Textarea } from '@/components/ui/textarea';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import { Separator } from '@/components/ui/separator';
import { ScrollArea } from '@/components/ui/scroll-area';
import { ArrowLeft, ShieldCheck, CheckCircle2, XCircle, AlertTriangle, RefreshCw, Inbox } from 'lucide-react';
import { toast } from 'sonner';

// Same glassy dark theme as the rest of the app (DocumentIngestion.tsx).
const glassCard = "backdrop-filter backdrop-blur-2xl bg-white/5 border border-white/10 shadow-[0_8px_32px_0_rgba(0,0,0,0.3)] rounded-2xl overflow-hidden";
const glassContainer = "min-h-screen bg-slate-950 bg-[radial-gradient(ellipse_at_top_right,_var(--tw-gradient-stops))] from-indigo-900 via-slate-950 to-black p-6 font-sans text-slate-200 selection:bg-indigo-500/30";

const ACTION_STYLE: Record<string, string> = {
  APPROVE: "bg-emerald-500/20 text-emerald-300 border-emerald-500/30",
  REJECT: "bg-red-500/20 text-red-300 border-red-500/30",
  ESCALATE: "bg-amber-500/20 text-amber-300 border-amber-500/30",
};

type PendingAction = 'reject' | 'escalate' | null;

export default function Moderation() {
  const navigate = useNavigate();
  const [queue, setQueue] = useState<ModerationQueueItem[]>([]);
  const [selected, setSelected] = useState<ModerationQueueItem | null>(null);
  const [agreement, setAgreement] = useState<AgreementRate | null>(null);
  const [loading, setLoading] = useState(true);
  const [accessDenied, setAccessDenied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [pendingAction, setPendingAction] = useState<PendingAction>(null);
  const [reasonCode, setReasonCode] = useState('');
  const [notes, setNotes] = useState('');
  const [fraudFlag, setFraudFlag] = useState(false);

  useEffect(() => {
    const unsubscribe = onSessionExpired(() => {
      toast.error("Session expired. Please sign in again.");
      navigate("/auth");
    });
    return unsubscribe;
  }, [navigate]);

  const load = useCallback(async () => {
    setLoading(true);
    const [queueRes, agreementRes] = await Promise.all([
      api.getModerationQueue(),
      api.getAgreementRate(),
    ]);
    if (queueRes.error) {
      if (queueRes.error.status === 401 || queueRes.error.status === 403) {
        setAccessDenied(true);
        toast.error("Access restricted: this account doesn't have Trust & Safety admin access.");
      } else {
        toast.error(queueRes.error.message || "Failed to load the review queue.");
      }
    } else {
      setAccessDenied(false);
      setQueue(queueRes.data || []);
    }
    if (!agreementRes.error) {
      setAgreement(agreementRes.data || null);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const resetActionForm = () => {
    setPendingAction(null);
    setReasonCode('');
    setNotes('');
    setFraudFlag(false);
  };

  const selectCampaign = (item: ModerationQueueItem) => {
    setSelected(item);
    resetActionForm();
  };

  const afterDecision = (campaignId: string, verb: string) => {
    toast.success(`Campaign ${campaignId} ${verb}. Recorded to the audit ledger.`);
    setQueue((prev) => prev.filter((c) => c.campaign_id !== campaignId));
    setSelected(null);
    resetActionForm();
    api.getAgreementRate().then((res) => {
      if (!res.error) setAgreement(res.data || null);
    });
  };

  const handleApprove = async () => {
    if (!selected) return;
    setBusy(true);
    const res = await api.approveCampaign(selected.campaign_id);
    setBusy(false);
    if (res.error) {
      toast.error(res.error.message || "Approve failed.");
      return;
    }
    afterDecision(selected.campaign_id, "approved");
  };

  const handleReject = async () => {
    if (!selected || !reasonCode.trim()) {
      toast.error("A reason code is required to reject.");
      return;
    }
    setBusy(true);
    const res = await api.rejectCampaign(selected.campaign_id, reasonCode.trim());
    setBusy(false);
    if (res.error) {
      toast.error(res.error.message || "Reject failed.");
      return;
    }
    afterDecision(selected.campaign_id, "rejected");
  };

  const handleEscalate = async () => {
    if (!selected || !notes.trim()) {
      toast.error("Notes are required to escalate.");
      return;
    }
    setBusy(true);
    const res = await api.escalateCampaign(selected.campaign_id, fraudFlag, notes.trim());
    setBusy(false);
    if (res.error) {
      toast.error(res.error.message || "Escalate failed.");
      return;
    }
    afterDecision(selected.campaign_id, "escalated");
  };

  return (
    <div className={glassContainer}>
      <div className="max-w-6xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <Button variant="ghost" size="icon" onClick={() => navigate('/chat')} className="text-slate-300 hover:text-white">
              <ArrowLeft className="w-5 h-5" />
            </Button>
            <ShieldCheck className="w-7 h-7 text-emerald-400" />
            <div>
              <h1 className="text-xl font-bold tracking-wide">Trust & Safety — Campaign Review</h1>
              <p className="text-sm text-slate-400">AI recommends. A human decides. Every decision is permanent.</p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            {agreement && agreement.total_compared > 0 && (
              <div className="text-right">
                <p className="text-xs text-slate-400">AI / human agreement</p>
                <p className="text-lg font-semibold text-indigo-300">
                  {Math.round((agreement.agreement_rate || 0) * 100)}%
                  <span className="text-xs text-slate-500 font-normal"> ({agreement.agreed}/{agreement.total_compared})</span>
                </p>
              </div>
            )}
            <Button variant="outline" size="icon" onClick={load} disabled={loading} className="border-white/10 text-slate-300">
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </Button>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
          {/* Queue */}
          <div className={`${glassCard} lg:col-span-2 flex flex-col`} style={{ maxHeight: '75vh' }}>
            <div className="px-4 py-3 border-b border-white/10 flex items-center justify-between">
              <span className="font-semibold text-sm">Pending review ({queue.length})</span>
            </div>
            <ScrollArea className="flex-1">
              {accessDenied && !loading && (
                <div className="p-8 text-center text-slate-500">
                  <ShieldCheck className="w-8 h-8 mx-auto mb-2 opacity-50" />
                  <p className="text-sm text-slate-400">Access restricted</p>
                  <p className="text-xs mt-1">This account doesn't have the Trust &amp; Safety admin role.</p>
                </div>
              )}
              {!accessDenied && queue.length === 0 && !loading && (
                <div className="p-8 text-center text-slate-500">
                  <Inbox className="w-8 h-8 mx-auto mb-2 opacity-50" />
                  <p className="text-sm">Queue is empty. Every campaign has been reviewed.</p>
                </div>
              )}
              <div className="divide-y divide-white/5">
                {queue.map((item) => (
                  <button
                    key={item.campaign_id}
                    onClick={() => selectCampaign(item)}
                    className={`w-full text-left px-4 py-3 hover:bg-white/5 transition-colors ${selected?.campaign_id === item.campaign_id ? 'bg-white/10' : ''}`}
                  >
                    <div className="flex items-center justify-between gap-2 mb-1">
                      <span className="text-sm font-medium truncate">{item.title || item.campaign_id}</span>
                      <Badge className={`shrink-0 ${ACTION_STYLE[item.recommended_action] || ''}`}>{item.recommended_action}</Badge>
                    </div>
                    <p className="text-xs text-slate-400 truncate">{item.rationale || 'No rationale recorded.'}</p>
                    <p className="text-xs text-slate-500 mt-1">
                      risk {item.risk_score?.toFixed(2) ?? 'n/a'} · {item.source}
                    </p>
                  </button>
                ))}
              </div>
            </ScrollArea>
          </div>

          {/* Detail */}
          <div className={`${glassCard} lg:col-span-3 p-6`}>
            {!selected ? (
              <div className="h-full flex items-center justify-center text-slate-500 py-20">
                <p className="text-sm">Select a campaign from the queue to review it.</p>
              </div>
            ) : (
              <div className="space-y-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h2 className="text-lg font-semibold">{selected.title || selected.campaign_id}</h2>
                    <p className="text-xs text-slate-500">{selected.campaign_id}</p>
                  </div>
                  <Badge className={ACTION_STYLE[selected.recommended_action] || ''}>
                    AI recommends: {selected.recommended_action}
                  </Badge>
                </div>

                <p className="text-sm text-slate-300 leading-relaxed">
                  {selected.description || <span className="italic text-slate-500">No description recorded for this campaign.</span>}
                </p>

                <div className="grid grid-cols-3 gap-3 text-sm">
                  <div>
                    <p className="text-slate-500 text-xs">Target amount</p>
                    <p className="font-medium">{selected.target_amount != null ? `$${selected.target_amount.toLocaleString()}` : 'n/a'}</p>
                  </div>
                  <div>
                    <p className="text-slate-500 text-xs">Risk score</p>
                    <p className="font-medium">{selected.risk_score?.toFixed(2) ?? 'n/a'} ({selected.risk_category || 'n/a'})</p>
                  </div>
                  <div>
                    <p className="text-slate-500 text-xs">Source</p>
                    <p className="font-medium">{selected.source}</p>
                  </div>
                </div>

                <div className="bg-black/20 rounded-xl p-3 border border-white/5">
                  <p className="text-xs text-slate-500 mb-1">AI rationale</p>
                  <p className="text-sm text-slate-300">{selected.rationale || 'No rationale recorded.'}</p>
                </div>

                <Separator className="bg-white/10" />

                {pendingAction === null && (
                  <div className="flex flex-wrap gap-2">
                    <Button onClick={handleApprove} disabled={busy} className="bg-emerald-600 hover:bg-emerald-700 gap-2">
                      <CheckCircle2 className="w-4 h-4" /> Approve
                    </Button>
                    <Button onClick={() => setPendingAction('reject')} disabled={busy} variant="destructive" className="gap-2">
                      <XCircle className="w-4 h-4" /> Reject
                    </Button>
                    <Button onClick={() => setPendingAction('escalate')} disabled={busy} className="bg-amber-600 hover:bg-amber-700 gap-2">
                      <AlertTriangle className="w-4 h-4" /> Escalate
                    </Button>
                  </div>
                )}

                {pendingAction === 'reject' && (
                  <div className="space-y-2">
                    <label className="text-xs text-slate-400">Reason code</label>
                    <Input
                      value={reasonCode}
                      onChange={(e) => setReasonCode(e.target.value)}
                      placeholder="e.g. financial_scheme, insufficient_documentation"
                      className="bg-black/20 border-white/10"
                    />
                    <div className="flex gap-2">
                      <Button onClick={handleReject} disabled={busy} variant="destructive">Confirm reject</Button>
                      <Button onClick={resetActionForm} disabled={busy} variant="outline" className="bg-slate-800 hover:bg-slate-700 text-white border-white/10">Cancel</Button>
                    </div>
                  </div>
                )}

                {pendingAction === 'escalate' && (
                  <div className="space-y-2">
                    <label className="text-xs text-slate-400">Notes</label>
                    <Textarea
                      value={notes}
                      onChange={(e) => setNotes(e.target.value)}
                      placeholder="What needs a closer look?"
                      className="bg-black/20 border-white/10"
                    />
                    <div className="flex items-center gap-2">
                      <Checkbox id="fraud_flag" checked={fraudFlag} onCheckedChange={(c) => setFraudFlag(!!c)} />
                      <label htmlFor="fraud_flag" className="text-xs text-slate-400">Flag for suspected fraud</label>
                    </div>
                    <div className="flex gap-2">
                      <Button onClick={handleEscalate} disabled={busy} className="bg-amber-600 hover:bg-amber-700">Confirm escalate</Button>
                      <Button onClick={resetActionForm} disabled={busy} variant="outline" className="bg-slate-800 hover:bg-slate-700 text-white border-white/10">Cancel</Button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
