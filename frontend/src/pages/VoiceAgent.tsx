import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { RetellWebClient } from 'retell-client-js-sdk';
import { Button } from '@/components/ui/button';
import { ArrowLeft, Mic, PhoneOff, Loader2, Volume2, CalendarCheck } from 'lucide-react';
import { toast } from 'sonner';
import { apiClient, type Booking } from '@/lib/api-client';

const glassCard = "backdrop-filter backdrop-blur-2xl bg-white/5 border border-white/10 shadow-[0_8px_32px_0_rgba(0,0,0,0.3)] rounded-2xl overflow-hidden transition-all duration-500";
const glassContainer = "min-h-screen bg-slate-950 bg-[radial-gradient(ellipse_at_top_right,_var(--tw-gradient-stops))] from-indigo-900 via-slate-950 to-black p-6 font-sans flex flex-col items-center pt-10 text-slate-200 selection:bg-indigo-500/30";

type CallState = 'idle' | 'connecting' | 'active' | 'ended';

interface Utterance {
  role: 'agent' | 'user';
  content: string;
}

export default function VoiceAgent() {
  const navigate = useNavigate();
  const [callState, setCallState] = useState<CallState>('idle');
  const [transcript, setTranscript] = useState<Utterance[]>([]);
  const [agentSpeaking, setAgentSpeaking] = useState(false);
  const [bookings, setBookings] = useState<Booking[]>([]);
  const clientRef = useRef<RetellWebClient | null>(null);

  const loadBookings = useCallback(async () => {
    const { data } = await apiClient.getBookings();
    if (data) setBookings(data);
  }, []);

  // Show what's already been booked, and refresh once a call ends — the
  // booking (if any) was confirmed to the caller mid-call, this just makes
  // it visible without a manual reload.
  useEffect(() => {
    loadBookings();
  }, [loadBookings]);

  // Set up the SDK client and its event listeners once.
  useEffect(() => {
    const client = new RetellWebClient();
    clientRef.current = client;

    client.on('call_started', () => setCallState('active'));
    client.on('agent_start_talking', () => setAgentSpeaking(true));
    client.on('agent_stop_talking', () => setAgentSpeaking(false));
    client.on('update', (update: { transcript?: Utterance[] }) => {
      if (update.transcript) setTranscript(update.transcript);
    });
    client.on('call_ended', () => {
      setCallState('ended');
      setAgentSpeaking(false);
      loadBookings();
    });
    client.on('error', (error: unknown) => {
      console.error('Voice call error:', error);
      toast.error('Voice call error — ending call.');
      client.stopCall();
      setCallState('ended');
    });

    return () => {
      client.stopCall();
    };
  }, []);

  const startCall = useCallback(async () => {
    setCallState('connecting');
    setTranscript([]);

    const { data, error } = await apiClient.startVoiceCall();
    if (error || !data) {
      toast.error(error?.message || 'Could not start voice call');
      setCallState('idle');
      return;
    }

    try {
      await clientRef.current?.startCall({ accessToken: data.access_token });
    } catch (err) {
      console.error('Failed to start call:', err);
      toast.error('Could not access microphone or start the call.');
      setCallState('idle');
    }
  }, []);

  const endCall = useCallback(() => {
    clientRef.current?.stopCall();
    setCallState('ended');
  }, []);

  const statusLabel = {
    idle: 'Ready to talk',
    connecting: 'Connecting…',
    active: agentSpeaking ? 'Assistant is speaking' : 'Listening…',
    ended: 'Call ended',
  }[callState];

  return (
    <div className={glassContainer}>
      <div className="w-full max-w-2xl space-y-6">
        {/* Header */}
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => navigate('/chat')}
            className="rounded-full bg-white/5 hover:bg-white/10 border border-white/10 text-white transition-all"
          >
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div>
            <h1 className="text-2xl font-semibold text-white">Voice Agent</h1>
            <p className="text-sm text-slate-400">
              Talk to OmniRAG directly — answers grounded in your ingested documents, with automation triggers for bookings.
            </p>
          </div>
        </div>

        {/* Call control */}
        <div className={`${glassCard} p-10 flex flex-col items-center gap-6`}>
          <button
            onClick={callState === 'idle' || callState === 'ended' ? startCall : undefined}
            disabled={callState === 'connecting' || callState === 'active'}
            className={`relative h-28 w-28 rounded-full flex items-center justify-center transition-all duration-300 ${
              callState === 'active'
                ? 'bg-indigo-500/20 border-2 border-indigo-400 shadow-[0_0_40px_rgba(99,102,241,0.4)]'
                : 'bg-indigo-600 hover:bg-indigo-500 border-2 border-indigo-400/50 shadow-[0_0_25px_rgba(99,102,241,0.3)] cursor-pointer'
            }`}
            aria-label={callState === 'active' ? 'Call in progress' : 'Start voice call'}
          >
            {callState === 'connecting' ? (
              <Loader2 className="h-10 w-10 text-white animate-spin" />
            ) : callState === 'active' ? (
              <Volume2 className={`h-10 w-10 text-indigo-300 ${agentSpeaking ? 'animate-pulse' : ''}`} />
            ) : (
              <Mic className="h-10 w-10 text-white" />
            )}
          </button>

          <p className="text-sm font-medium text-slate-300">{statusLabel}</p>

          {callState === 'active' && (
            <Button
              onClick={endCall}
              variant="destructive"
              className="gap-2 rounded-full"
            >
              <PhoneOff className="h-4 w-4" />
              End Call
            </Button>
          )}

          {(callState === 'idle' || callState === 'ended') && (
            <p className="text-xs text-slate-500 max-w-sm text-center">
              {callState === 'ended'
                ? 'Call ended. Click the microphone to start a new one.'
                : 'Click the microphone and allow browser mic access to start.'}
            </p>
          )}
        </div>

        {/* Live transcript */}
        {transcript.length > 0 && (
          <div className={`${glassCard} p-6`}>
            <h2 className="text-sm font-semibold text-slate-300 mb-4 uppercase tracking-wider">Live Transcript</h2>
            <div className="space-y-3">
              {transcript.map((turn, i) => (
                <div
                  key={i}
                  className={`flex ${turn.role === 'agent' ? 'justify-start' : 'justify-end'}`}
                >
                  <div
                    className={`max-w-[80%] rounded-2xl px-4 py-2 text-sm ${
                      turn.role === 'agent'
                        ? 'bg-white/10 text-slate-200'
                        : 'bg-indigo-600/80 text-white'
                    }`}
                  >
                    {turn.content}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Confirmed bookings — persisted records, not just a stub trigger */}
        {bookings.length > 0 && (
          <div className={`${glassCard} p-6`}>
            <h2 className="text-sm font-semibold text-slate-300 mb-4 uppercase tracking-wider flex items-center gap-2">
              <CalendarCheck className="h-4 w-4" /> Recent Bookings
            </h2>
            <div className="space-y-2">
              {bookings.map((b) => (
                <div
                  key={b.id}
                  className="flex items-center justify-between rounded-xl bg-white/5 border border-white/10 px-4 py-3 text-sm"
                >
                  <div>
                    <p className="text-slate-200 font-medium">{b.service}</p>
                    <p className="text-slate-500 text-xs">
                      {b.customer_name || 'Unknown caller'} · {b.address || 'address not captured'}
                      {b.phone ? ` · ${b.phone}` : ''}
                    </p>
                    {(b.preferred_day || b.preferred_time) && (
                      <p className="text-slate-600 text-xs">
                        {b.preferred_day || ''}{b.preferred_day && b.preferred_time ? ', ' : ''}{b.preferred_time || ''}
                      </p>
                    )}
                  </div>
                  <span className="text-xs px-2 py-1 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                    {b.status}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
