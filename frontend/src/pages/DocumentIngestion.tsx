import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiClient as api, onSessionExpired } from '@/lib/api-client';
import { Button } from '@/components/ui/button';
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Calendar } from "@/components/ui/calendar";
import { cn } from "@/lib/utils";
import { format } from "date-fns";
import { FileText, Download, CloudOff, ArrowLeft, FolderSearch, Calendar as CalendarIcon, UploadCloud, FileUp, Sparkles, Database, CheckCircle, Clock, AlertCircle, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import DocumentViewer from '@/components/DocumentViewer';

// Ultra-premium Glassy styles
const glassCard = "backdrop-filter backdrop-blur-2xl bg-white/5 border border-white/10 shadow-[0_8px_32px_0_rgba(0,0,0,0.3)] rounded-2xl overflow-hidden transition-all duration-500 hover:shadow-[0_8px_32px_0_rgba(99,102,241,0.2)] hover:-translate-y-1 hover:border-indigo-500/30 hover:bg-white/10";
const glassContainer = "min-h-screen bg-slate-950 bg-[radial-gradient(ellipse_at_top_right,_var(--tw-gradient-stops))] from-indigo-900 via-slate-950 to-black p-6 font-sans flex flex-col items-center pt-10 text-slate-200 selection:bg-indigo-500/30";

export default function DocumentIngestion() {
    const navigate = useNavigate();
    const [status, setStatus] = useState<any>(null);
    const [loading, setLoading] = useState(true);
    const [syncing, setSyncing] = useState(false);
    const [viewingDoc, setViewingDoc] = useState<{ docId: string; docName: string } | null>(null);
    const [targetFolder, setTargetFolder] = useState("");
    const [minDate, setMinDate] = useState<Date | undefined>(undefined);
    const [syncingFiles, setSyncingFiles] = useState<Set<string>>(new Set());
    const fileInputRef = React.useRef<HTMLInputElement>(null);

    // Handle session expiry - redirect to auth page
    useEffect(() => {
        const unsubscribe = onSessionExpired(() => {
            toast.error("Session expired. Please sign in again.");
            navigate("/auth");
        });
        return unsubscribe;
    }, [navigate]);

    const fetchStatus = async () => {
        setLoading(true);
        try {
            const dateStr = minDate ? format(minDate, "yyyy-MM-dd") : undefined;
            const res = await api.getDocumentStatus(targetFolder, dateStr);
            if (res.error) {
                console.error(res.error);
                return;
            }
            setStatus(res.data);
            if (res.data?.is_syncing) {
                setSyncing(true);
            } else {
                setSyncing(false);
            }
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchStatus();
    }, []);

    const handleSyncBatch = async () => {
        const itemIds = files
            .map((f: any) => f.item_id)
            .filter((id: any) => id); // Filter out null/undefined item_ids

        if (itemIds.length === 0) {
            toast.error("No files listed to sync");
            return;
        }

        setSyncing(true);
        const res = await api.syncBatch(itemIds);
        if (res.error) {
            toast.error(res.error.message);
            setSyncing(false);
        } else {
            toast.success(`Started syncing ${itemIds.length} files`);
            setTimeout(fetchStatus, 1000);
        }
    };

    const handleSync = async () => {
        setSyncing(true);
        const res = await api.triggerDocumentSync();
        if (res.error) {
            toast.error(res.error.message);
            setSyncing(false);
        } else {
            toast.success("Sync started");
            fetchStatus();
        }
    };

    const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;

        setSyncing(true);
        const res = await api.uploadFile(file);
        
        if (res.error) {
            toast.error(`Upload failed: ${res.error.message}`);
        } else {
            toast.success(`Successfully uploaded ${file.name}`);
            
            // Add a mock file to the list to show it locally
            setStatus((prev: any) => ({
                ...prev,
                files: [
                    { 
                        item_id: res.data.doc_id || Date.now().toString(), 
                        fileName: file.name, 
                        filestatus: 'ready', 
                        filepath: '/Local Uploads',
                        doc_id: res.data.doc_id
                    },
                    ...(prev?.files || [])
                ]
            }));
        }
        setSyncing(false);
        if (fileInputRef.current) {
            fileInputRef.current.value = '';
        }
    };

    const handleSyncSingle = async (itemId: string, fileName: string) => {
        if (!itemId) {
            toast.error("Cannot sync file: Missing Item ID");
            return;
        }
        
        // Add to syncing set to disable button
        setSyncingFiles(prev => new Set(prev).add(itemId));
        
        toast.promise(api.syncSingleFile(itemId), {
            loading: `Syncing ${fileName}...`,
            success: () => {
                fetchStatus();
                // Remove from syncing set
                setSyncingFiles(prev => {
                    const next = new Set(prev);
                    next.delete(itemId);
                    return next;
                });
                return `Successfully synced ${fileName}`;
            },
            error: (err) => {
                // Remove from syncing set on error too
                setSyncingFiles(prev => {
                    const next = new Set(prev);
                    next.delete(itemId);
                    return next;
                });
                return `Failed to sync: ${err.message}`;
            }
        });
    };

    // Counts
    const files = status?.files || [];
    const readyCount = files.filter((f: any) => f.filestatus === 'ready').length;
    const processingCount = files.filter((f: any) => f.filestatus === 'processing').length;
    const queuedCount = files.filter((f: any) => ['queued', 'pending'].includes(f.filestatus)).length;
    const errorCount = files.filter((f: any) => f.filestatus === 'error').length;
    const unsyncedCount = files.filter((f: any) => f.filestatus === 'not_synced').length;

    return (
        <div className={glassContainer}>
            <div className="w-full max-w-6xl space-y-8 animate-in fade-in slide-in-from-bottom-8 duration-700">
                {/* Header */}
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-5">
                        <Button 
                            variant="ghost" 
                            size="icon" 
                            onClick={() => navigate('/chat')}
                            className="h-12 w-12 rounded-full bg-white/5 hover:bg-white/10 border border-white/10 text-white transition-all shadow-lg hover:shadow-indigo-500/20"
                        >
                            <ArrowLeft className="h-5 w-5" />
                        </Button>
                        <div>
                            <div className="flex items-center gap-3">
                                <h1 className="text-4xl font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-indigo-300 via-white to-purple-300 tracking-tight drop-shadow-sm">
                                    Knowledge Base
                                </h1>
                                <span className="flex h-6 items-center rounded-full bg-indigo-500/10 px-2.5 text-xs font-semibold text-indigo-300 ring-1 ring-inset ring-indigo-500/20">
                                    <Sparkles className="h-3 w-3 mr-1" /> Premium
                                </span>
                            </div>
                            <p className="text-slate-400 mt-1 text-sm font-medium">Upload, process, and manage your documents for AI context</p>
                        </div>
                    </div>
                </div>

                {/* Status Bar */}
                <div className={`${glassCard} py-5 px-8 flex items-center justify-between`}>
                    <div className="flex items-center gap-8">
                        <div className="flex items-center gap-4">
                            <div className="relative flex h-4 w-4">
                              <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${syncing ? 'bg-indigo-400' : files.length > 0 ? 'bg-emerald-400' : 'bg-slate-500'}`}></span>
                              <span className={`relative inline-flex rounded-full h-4 w-4 ${syncing ? 'bg-indigo-500' : files.length > 0 ? 'bg-emerald-500' : 'bg-slate-600'}`}></span>
                            </div>
                            <div className="flex flex-col">
                                <span className="text-2xl font-bold text-white leading-none">{files.length}</span>
                                <span className="text-[10px] uppercase font-bold tracking-widest text-slate-400 mt-1">Total Documents</span>
                            </div>
                        </div>
                        <div className="h-10 w-px bg-white/10" />
                        <div className="flex flex-col">
                            <span className="text-[10px] uppercase font-bold tracking-widest text-slate-400">System Status</span>
                            <span className="text-sm font-medium text-slate-300 mt-0.5 flex items-center gap-2">
                                <Database className="h-3.5 w-3.5 text-indigo-400" />
                                {loading ? 'Checking...' : syncing ? 'Processing...' : 'Online & Ready'}
                            </span>
                        </div>
                    </div>
                    <div className="flex items-center gap-4">
                        <Button
                            onClick={fetchStatus}
                            variant="ghost"
                            disabled={loading}
                            className="text-slate-300 hover:text-white hover:bg-white/10 rounded-xl px-5 h-12 text-sm font-semibold transition-all border border-transparent hover:border-white/10"
                        >
                            <RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
                            Refresh
                        </Button>
                        <Button
                            onClick={() => fileInputRef.current?.click()}
                            disabled={syncing || loading}
                            className="relative group bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl px-6 h-12 text-sm font-semibold transition-all shadow-[0_0_20px_rgba(79,70,229,0.4)] hover:shadow-[0_0_30px_rgba(79,70,229,0.6)] border border-indigo-400/50 hover:-translate-y-0.5 overflow-hidden"
                        >
                            <div className="absolute inset-0 w-full h-full bg-gradient-to-r from-transparent via-white/20 to-transparent -translate-x-full group-hover:animate-[shimmer_1.5s_infinite]" />
                            <FileUp className={`mr-2 h-4 w-4 relative z-10 ${syncing ? 'animate-bounce' : ''}`} />
                            <span className="relative z-10">{syncing ? 'Uploading...' : 'Upload PDF Document'}</span>
                        </Button>
                        <input
                            type="file"
                            accept=".pdf"
                            ref={fileInputRef}
                            style={{ display: 'none' }}
                            onChange={handleFileUpload}
                        />
                    </div>
                </div>

                {/* Filter Controls */}
                <div className={`${glassCard} py-3 px-6 flex items-center gap-4`}>
                    <div className="flex-1 flex items-center gap-3">
                        <FolderSearch className="h-4 w-4 text-gray-400" />
                        <Input 
                            placeholder="Target Folder (e.g. CEO Office/IR/IPO) - Leave empty for recent files" 
                            value={targetFolder}
                            onChange={(e) => setTargetFolder(e.target.value)}
                            onKeyDown={(e) => e.key === 'Enter' && fetchStatus()}
                            className="bg-transparent border-none shadow-none focus-visible:ring-0 text-gray-700 placeholder:text-gray-400 h-8 p-0"
                        />
                    </div>
                    <div className="h-6 w-px bg-gray-300/50" />
                    <Popover>
                        <PopoverTrigger asChild>
                            <Button
                                variant={"outline"}
                                className={cn(
                                    "w-[240px] justify-start text-left font-normal bg-transparent border-none shadow-none hover:bg-transparent hover:text-blue-600 p-0 h-8",
                                    !minDate && "text-muted-foreground"
                                )}
                            >
                                <CalendarIcon className="mr-2 h-4 w-4 text-gray-400" />
                                {minDate ? format(minDate, "PPP") : <span className="text-gray-400">Filter by Modified Date</span>}
                            </Button>
                        </PopoverTrigger>
                        <PopoverContent className="w-auto p-0" align="end">
                            <Calendar
                                mode="single"
                                selected={minDate}
                                onSelect={setMinDate}
                                initialFocus
                            />
                        </PopoverContent>
                    </Popover>
                    <div className="h-6 w-px bg-gray-300/50" />
                    <Button 
                         variant="ghost" 
                         size="sm"
                         onClick={fetchStatus}
                         className="text-blue-600 hover:text-blue-700 hover:bg-blue-50 -mr-2"
                    >
                        Apply Filters
                    </Button>
                </div>

                {/* Cards Grid */}
                <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
                    <StatusCard title="READY" count={readyCount} icon={<CheckCircle className="text-emerald-500 h-4 w-4" />} />
                    <StatusCard title="PROCESSING" count={processingCount} icon={<RefreshCw className="text-blue-500 h-4 w-4 animate-spin-slow" />} />
                    <StatusCard title="QUEUED" count={queuedCount} icon={<Clock className="text-amber-500 h-4 w-4" />} />
                    <StatusCard title="ERRORS" count={errorCount} icon={<AlertCircle className="text-rose-500 h-4 w-4" />} />
                    <StatusCard title="UNSYNCED" count={unsyncedCount} icon={<CloudOff className="text-gray-400 h-4 w-4" />} />
                </div>

                {/* Main Content */}
                <div className={`${glassCard} min-h-[450px] flex flex-col p-8 relative`}>
                    <div className="relative z-10 w-full h-full flex flex-col">
                        <h2 className="text-xl font-bold text-white mb-6 flex items-center gap-2">
                            <FolderSearch className="h-5 w-5 text-indigo-400" />
                            Document Library
                        </h2>
                        {loading && !status ? (
                            <div className="flex-1 flex flex-col items-center justify-center text-center space-y-6 py-12">
                                <div className="relative">
                                    <div className="absolute inset-0 bg-indigo-500 rounded-full blur-xl opacity-20 animate-pulse"></div>
                                    <RefreshCw className="h-12 w-12 text-indigo-400 animate-spin relative z-10" />
                                </div>
                                <p className="text-slate-400 text-sm font-medium tracking-wide">Syncing local documents...</p>
                            </div>
                        ) : files.length === 0 ? (
                            <div 
                                onClick={() => fileInputRef.current?.click()}
                                className="flex-1 flex flex-col items-center justify-center text-center space-y-6 py-16 border-2 border-dashed border-white/10 hover:border-indigo-500/50 rounded-2xl bg-white/[0.02] hover:bg-white/[0.04] transition-all cursor-pointer group"
                            >
                                <div className="w-24 h-24 bg-indigo-500/10 rounded-3xl flex items-center justify-center shadow-[0_0_40px_rgba(99,102,241,0.15)] group-hover:scale-110 transition-transform duration-500 border border-indigo-500/20">
                                    <FileUp className="h-10 w-10 text-indigo-400 group-hover:animate-bounce" />
                                </div>
                                <div>
                                    <h3 className="text-xl font-bold text-white">Your library is empty</h3>
                                    <p className="text-slate-400 mt-2 text-sm max-w-md mx-auto">Upload your first PDF document to securely ingest it into the local Qdrant vector database.</p>
                                </div>
                                <Button className="mt-4 bg-white/10 hover:bg-white/20 text-white rounded-full px-8 pointer-events-none border border-white/10">
                                    Click to Browse
                                </Button>
                            </div>
                        ) : (
                            <div className="w-full">
                                <div className="grid grid-cols-1 gap-3 w-full max-h-[500px] overflow-y-auto pr-2 custom-scrollbar">
                                    {files.map((file: any, i: number) => (
                                        <div
                                            key={i}
                                            className={`flex items-center justify-between p-4 bg-white/[0.03] hover:bg-white/[0.08] rounded-xl transition-all duration-300 border border-white/5 hover:border-indigo-500/30 shadow-sm group cursor-pointer ${file.filestatus === 'not_synced' ? 'opacity-50 hover:opacity-100' : ''}`}
                                            onClick={() => file.doc_id && setViewingDoc({ docId: file.doc_id, docName: file.fileName })}
                                        >
                                            <div className="flex items-center gap-4 overflow-hidden">
                                                <div className={`p-3 rounded-xl shadow-inner border border-white/10 ${file.filestatus === 'not_synced' ? 'bg-slate-800' : 'bg-gradient-to-br from-indigo-500/20 to-purple-500/20'}`}>
                                                    <FileText className={`h-5 w-5 ${file.filestatus === 'not_synced' ? 'text-slate-500' : 'text-indigo-300'}`} />
                                                </div>
                                                <div className="flex flex-col gap-1 min-w-0">
                                                    <span className={`text-base font-bold truncate ${file.filestatus === 'not_synced' ? 'text-slate-500' : 'text-slate-200 group-hover:text-white group-hover:translate-x-1'} transition-all duration-300`}>{file.fileName}</span>
                                                    <span className="text-[11px] text-slate-500 truncate max-w-[400px] font-mono flex items-center gap-1.5">
                                                        <FolderSearch className="h-3 w-3" />
                                                        {file.filepath || '/Local Uploads'}
                                                    </span>
                                                </div>
                                            </div>
                                            
                                            <div className="flex items-center gap-4">
                                                <span className={`px-3 py-1 rounded-full text-[10px] font-bold tracking-widest border shadow-[inset_0_1px_0_rgba(255,255,255,0.1)] ${
                                                    file.filestatus === 'ready' ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30' :
                                                    file.filestatus === 'processing' ? 'bg-blue-500/20 text-blue-300 border-blue-500/30 animate-pulse' :
                                                    file.filestatus === 'error' ? 'bg-rose-500/20 text-rose-300 border-rose-500/30' :
                                                    file.filestatus === 'not_synced' ? 'bg-slate-500/20 text-slate-400 border-slate-500/30' :
                                                    'bg-slate-800 text-slate-300 border-slate-700'
                                                }`}>
                                                    {file.filestatus.toUpperCase().replace('_', ' ')}
                                                </span>

                                                {file.filestatus === 'not_synced' && (
                                                    <Button
                                                        size="sm"
                                                        variant="outline"
                                                        disabled={syncingFiles.has(file.item_id)}
                                                        className="h-7 px-3 text-xs bg-white hover:bg-blue-50 hover:text-blue-600 border-gray-200 disabled:opacity-50 disabled:cursor-not-allowed"
                                                        onClick={(e) => {
                                                            e.stopPropagation();
                                                            handleSyncSingle(file.item_id, file.fileName);
                                                        }}
                                                    >
                                                        <Download className={`h-3 w-3 mr-1.5 ${syncingFiles.has(file.item_id) ? 'animate-pulse' : ''}`} /> 
                                                        {syncingFiles.has(file.item_id) ? 'Syncing...' : 'Sync'}
                                                    </Button>
                                                )}
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            </div>


            {viewingDoc && (
                <DocumentViewer
                    docId={viewingDoc.docId}
                    docName={viewingDoc.docName}
                    onClose={() => setViewingDoc(null)}
                />
            )}
        </div>
    );
}

function StatusCard({ title, count, icon }: { title: string, count: number, icon: React.ReactNode }) {
    return (
        <div className={`${glassCard} p-6 flex flex-col justify-between h-32 cursor-default group hover:-translate-y-2 hover:shadow-[0_10px_40px_rgba(99,102,241,0.15)] transition-all duration-500 relative overflow-hidden`}>
            <div className="absolute -right-4 -top-4 opacity-[0.03] group-hover:scale-150 group-hover:opacity-[0.08] transition-all duration-700 pointer-events-none text-white">
                {icon}
            </div>
            <div className="flex justify-between items-start relative z-10">
                <span className="text-[11px] font-bold text-slate-400 tracking-[0.2em] uppercase">{title}</span>
                <div className="p-2 rounded-lg bg-white/5 border border-white/10 text-white">
                    {icon}
                </div>
            </div>
            <span className="text-4xl font-extrabold text-white group-hover:text-transparent group-hover:bg-clip-text group-hover:bg-gradient-to-r group-hover:from-indigo-300 group-hover:to-white transition-all duration-300 tracking-tight relative z-10">{count}</span>
        </div>
    )
}
