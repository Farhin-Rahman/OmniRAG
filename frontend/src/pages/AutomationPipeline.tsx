import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import {
  ArrowLeft, CheckCircle, Clock, AlertCircle, Zap,
  FileText, Cpu, Database, Search, ArrowRight, Copy, Check, Webhook
} from 'lucide-react';
import { toast } from 'sonner';
import { config } from '@/config';

const glassCard = "backdrop-filter backdrop-blur-2xl bg-white/5 border border-white/10 shadow-[0_8px_32px_0_rgba(0,0,0,0.3)] rounded-2xl overflow-hidden transition-all duration-500 hover:border-indigo-500/30 hover:bg-white/10";
const glassContainer = "min-h-screen bg-slate-950 bg-[radial-gradient(ellipse_at_top_right,_var(--tw-gradient-stops))] from-indigo-900 via-slate-950 to-black p-6 font-sans flex flex-col items-center pt-10 text-slate-200 selection:bg-indigo-500/30";

interface Document {
  doc_id: string;
  doc_name: string;
  status: string;
  created_at: string;
}

const PIPELINE_STEPS = [
  { icon: FileText,  label: 'Upload',  desc: 'File received via UI, API, or webhook' },
  { icon: Cpu,       label: 'Parse',   desc: 'PyMuPDF extracts text' },
  { icon: Database,  label: 'Chunk',   desc: 'Text split into searchable chunks' },
  { icon: Zap,       label: 'Embed',   desc: 'BGE-M3 encodes text' },
  { icon: Search,    label: 'Index',   desc: 'Vectors stored in Qdrant' },
];

function StatusBadge({ status }: { status: string }) {
  if (status === 'ready')
    return <span className="flex items-center gap-1 text-xs text-green-600 font-medium"><CheckCircle className="h-3.5 w-3.5" /> Ready</span>;
  if (status === 'queued' || status === 'processing')
    return <span className="flex items-center gap-1 text-xs text-yellow-600 font-medium"><Clock className="h-3.5 w-3.5 animate-pulse" /> {status}</span>;
  return <span className="flex items-center gap-1 text-xs text-red-500 font-medium"><AlertCircle className="h-3.5 w-3.5" /> {status}</span>;
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <button onClick={copy} className="p-1 rounded hover:bg-white/50 transition-colors">
      {copied ? <Check className="h-3.5 w-3.5 text-green-500" /> : <Copy className="h-3.5 w-3.5 text-gray-400" />}
    </button>
  );
}

export default function AutomationPipeline() {
  const navigate = useNavigate();
  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [queryInput, setQueryInput] = useState('');
  const [webhookSecret, setWebhookSecret] = useState('');
  const [queryResult, setQueryResult] = useState<{ answer: string; sources: string[] } | null>(null);
  const [querying, setQuerying] = useState(false);

  const fetchDocuments = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${config.apiBaseUrl}/documents?limit=8`);
      if (res.ok) {
        const data = await res.json();
        setDocuments(data.documents || []);
      }
    } catch {
      toast.error('Failed to fetch documents');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchDocuments(); }, [fetchDocuments]);

  const ready = documents.filter(d => d.status === 'ready').length;
  const processing = documents.filter(d => d.status !== 'ready' && d.status !== 'error').length;

  const runWebhookQuery = async () => {
    if (!queryInput.trim()) return;
    setQuerying(true);
    setQueryResult(null);
    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (webhookSecret) headers['X-Webhook-Secret'] = webhookSecret;
      const res = await fetch(`${config.apiBaseUrl}/webhooks/query`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ question: queryInput }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        toast.error(err.detail || 'Query failed');
        return;
      }
      const data = await res.json();
      setQueryResult(data);
    } catch {
      toast.error('Network error');
    } finally {
      setQuerying(false);
    }
  };

  const baseUrl = config.apiBaseUrl;
  const curlIngest = `curl -X POST ${baseUrl}/webhooks/ingest-url \\
  -H "Content-Type: application/json" \\
  -H "X-Webhook-Secret: YOUR_SECRET" \\
  -d '{"url": "https://example.com/doc.pdf"}'`;

  const curlQuery = `curl -X POST ${baseUrl}/webhooks/query \\
  -H "Content-Type: application/json" \\
  -H "X-Webhook-Secret: YOUR_SECRET" \\
  -d '{"question": "What are the key compliance requirements?"}'`;

  return (
    <div className={glassContainer}>
      <div className="w-full max-w-4xl space-y-6">

        {/* Header */}
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon" onClick={() => navigate('/chat')} className="rounded-full bg-white/5 hover:bg-white/10 border border-white/10 text-white transition-all">
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div>
            <h1 className="text-2xl font-semibold text-white">Automation Pipeline</h1>
            <p className="text-sm text-slate-400">Live view of document ingestion, AI processing, and webhook integrations</p>
          </div>
        </div>

        {/* Pipeline diagram */}
        <div className={`${glassCard} p-6`}>
          <h2 className="text-sm font-semibold text-slate-300 mb-4 uppercase tracking-wider">Document Ingestion Pipeline</h2>
          <div className="flex items-start gap-1 overflow-x-auto pb-2">
            {PIPELINE_STEPS.map((step, i) => {
              const Icon = step.icon;
              return (
                <div key={step.label} className="flex items-center gap-1 flex-shrink-0">
                  <div className="flex flex-col items-center text-center w-28 group">
                    <div className="h-10 w-10 rounded-full bg-indigo-500/10 border border-indigo-500/20 shadow-[0_0_15px_rgba(99,102,241,0.1)] flex items-center justify-center mb-2 group-hover:scale-110 transition-transform">
                      <Icon className="h-5 w-5 text-indigo-400" />
                    </div>
                    <span className="text-xs font-semibold text-slate-200">{step.label}</span>
                    <span className="text-[10px] text-slate-400 mt-0.5 leading-tight">{step.desc}</span>
                  </div>
                  {i < PIPELINE_STEPS.length - 1 && (
                    <ArrowRight className="h-4 w-4 text-gray-300 flex-shrink-0 mt-[-20px]" />
                  )}
                </div>
              );
            })}
          </div>

          {/* Live stats */}
          <div className="flex gap-4 mt-5 pt-4 border-t border-white/10">
            <div className="text-center">
              <p className="text-2xl font-bold text-white">{documents.length}</p>
              <p className="text-xs text-slate-400">Total documents</p>
            </div>
            <div className="text-center">
              <p className="text-2xl font-bold text-emerald-400">{ready}</p>
              <p className="text-xs text-slate-400">Indexed & ready</p>
            </div>
            <div className="text-center">
              <p className="text-2xl font-bold text-amber-400">{processing}</p>
              <p className="text-xs text-slate-400">Processing</p>
            </div>
            <div className="ml-auto self-end">
              <Button size="sm" variant="outline" onClick={fetchDocuments} disabled={loading} className="text-xs bg-white/5 border-white/10 hover:bg-white/10 text-white">
                {loading ? 'Refreshing…' : 'Refresh'}
              </Button>
            </div>
          </div>
        </div>

        {/* Recent documents */}
        <div className={`${glassCard} p-6`}>
          <h2 className="text-sm font-semibold text-slate-300 mb-4 uppercase tracking-wider">Recent Documents</h2>
          {loading ? (
            <p className="text-sm text-slate-400">Loading…</p>
          ) : documents.length === 0 ? (
            <p className="text-sm text-slate-400">No documents ingested yet. Upload a file or trigger the webhook to get started.</p>
          ) : (
            <div className="space-y-2">
              {documents.map(doc => (
                <div key={doc.doc_id} className="flex items-center justify-between py-2 px-3 rounded-lg bg-white/5 border border-white/10 hover:bg-white/10 transition-colors">
                  <div className="flex items-center gap-2 min-w-0">
                    <FileText className="h-4 w-4 text-indigo-400 flex-shrink-0" />
                    <span className="text-sm text-slate-200 truncate">{doc.doc_name}</span>
                  </div>
                  <div className="flex items-center gap-3 flex-shrink-0 ml-2">
                    <span className="text-[11px] text-slate-500 hidden sm:block">
                      {new Date(doc.created_at).toLocaleDateString()}
                    </span>
                    <StatusBadge status={doc.status} />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Webhook endpoints */}
        <div className={`${glassCard} p-6`}>
          <div className="flex items-center gap-2 mb-4">
            <Webhook className="h-4 w-4 text-indigo-400" />
            <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider">Webhook Endpoints</h2>
          </div>
          <p className="text-sm text-slate-400 mb-5">
            These endpoints let you trigger the AI pipeline from Make, n8n, Zapier, or any HTTP client.
            Authenticate with the <code className="text-xs bg-white/10 px-1 py-0.5 rounded text-indigo-300">X-Webhook-Secret</code> header.
          </p>

          {/* Ingest endpoint */}
          <div className="mb-5">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs font-mono bg-indigo-500/20 text-indigo-300 px-2 py-0.5 rounded border border-indigo-500/30">POST</span>
              <code className="text-xs font-mono text-slate-300">/api/webhooks/ingest-url</code>
            </div>
            <p className="text-xs text-slate-400 mb-2">Download a file from a URL and queue it through the RAG pipeline. Returns immediately — processing runs in the background.</p>
            <div className="relative bg-gray-900 rounded-lg p-3 text-[11px] font-mono text-gray-300 overflow-x-auto">
              <div className="absolute top-2 right-2"><CopyButton text={curlIngest} /></div>
              <pre className="whitespace-pre-wrap">{curlIngest}</pre>
            </div>
          </div>

          {/* Query endpoint */}
          <div>
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs font-mono bg-indigo-500/20 text-indigo-300 px-2 py-0.5 rounded border border-indigo-500/30">POST</span>
              <code className="text-xs font-mono text-slate-300">/api/webhooks/query</code>
            </div>
            <p className="text-xs text-slate-400 mb-2">Run a RAG query and get an AI-generated answer as plain JSON — ready to use in the next step of your automation.</p>
            <div className="relative bg-gray-900 rounded-lg p-3 text-[11px] font-mono text-gray-300 overflow-x-auto">
              <div className="absolute top-2 right-2"><CopyButton text={curlQuery} /></div>
              <pre className="whitespace-pre-wrap">{curlQuery}</pre>
            </div>
          </div>
        </div>

        {/* Live webhook test */}
        <div className={`${glassCard} p-6`}>
          <h2 className="text-sm font-semibold text-slate-300 mb-1 uppercase tracking-wider">Live Webhook Test</h2>
          <p className="text-xs text-slate-400 mb-4">Fire a real query against your document knowledge base through the webhook endpoint.</p>

          <div className="space-y-3">
            <div>
              <label className="text-xs text-slate-400 block mb-1">Webhook Secret (leave empty if WEBHOOK_SECRET not set)</label>
              <input
                value={webhookSecret}
                onChange={e => setWebhookSecret(e.target.value)}
                placeholder="your-webhook-secret"
                type="password"
                className="w-full text-xs px-3 py-2 rounded-lg border border-white/10 bg-white/5 focus:outline-none focus:ring-1 focus:ring-indigo-500 text-white placeholder-slate-600"
              />
            </div>
            <div>
              <label className="text-xs text-slate-400 block mb-1">Question</label>
              <div className="flex gap-2">
                <input
                  value={queryInput}
                  onChange={e => setQueryInput(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && runWebhookQuery()}
                  placeholder="Ask something about your documents…"
                  className="flex-1 text-sm px-3 py-2 rounded-lg border border-white/10 bg-white/5 focus:outline-none focus:ring-1 focus:ring-indigo-500 text-white placeholder-slate-600"
                />
                <Button onClick={runWebhookQuery} disabled={querying || !queryInput.trim()} size="sm" className="bg-indigo-600 hover:bg-indigo-700 text-white border-0">
                  {querying ? 'Querying…' : 'Send'}
                </Button>
              </div>
            </div>
          </div>

          {queryResult && (
            <div className="mt-4 p-4 rounded-lg bg-black/40 border border-white/10">
              <p className="text-xs font-semibold text-slate-400 mb-1">Response JSON</p>
              <pre className="text-xs text-emerald-400 whitespace-pre-wrap font-mono">
                {JSON.stringify(queryResult, null, 2)}
              </pre>
            </div>
          )}
        </div>

      </div>
    </div>
  );
}
