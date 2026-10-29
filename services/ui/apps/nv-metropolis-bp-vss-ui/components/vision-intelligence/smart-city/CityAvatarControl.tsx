import React, { useEffect, useRef, useState } from 'react';
import styles from './CityAvatarControl.module.css';

type Status = { available: boolean; running: boolean; busy: boolean; canStart: boolean; active: number;
  message: string; source_status?: string; source_error?: string };

async function read(response: Response): Promise<Status> {
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Check the live avatar connection.');
  return data;
}

export function CityAvatarControl() {
  const [status, setStatus] = useState<Status | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const mutation = useRef(0);
  const pending = useRef(false);
  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    let request: AbortController | undefined;
    let generation = 0;
    const poll = async () => {
      if (disposed || document.hidden) return;
      const version = mutation.current;
      const mine = ++generation;
      const current = new AbortController();
      request = current;
      const timeout = setTimeout(() => current.abort(), 6500);
      try {
        const data = await read(await fetch('/api/vision/city-avatars', { cache: 'no-store', signal: current.signal }));
        if (!disposed && mine === generation && version === mutation.current && !pending.current) setStatus(data);
      } catch {
        if (!disposed && mine === generation && version === mutation.current && !pending.current) setStatus(null);
      } finally {
        clearTimeout(timeout);
        if (!disposed && !document.hidden && mine === generation) timer = setTimeout(poll, 2000);
      }
    };
    const visible = () => { ++generation; clearTimeout(timer); request?.abort(); if (!document.hidden) void poll(); };
    document.addEventListener('visibilitychange', visible);
    void poll();
    return () => { disposed = true; clearTimeout(timer); request?.abort(); document.removeEventListener('visibilitychange', visible); };
  }, []);
  const toggle = async () => {
    if (pending.current) return;
    pending.current = true; ++mutation.current; setBusy(true); setError('');
    try {
      setStatus(await read(await fetch('/api/vision/city-avatars', { method: 'POST',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ operation: status?.running ? 'stop' : 'start' }),
        signal: AbortSignal.timeout(7500) })));
    } catch (reason) {
      setStatus(null); setError(reason instanceof Error ? reason.message : 'Check status before retrying.');
    } finally { pending.current = false; setBusy(false); }
  };
  const message = error || (!status?.available ? 'Start Smart City Demo to connect.' : status.busy ? 'Preparing live avatars…' :
    /failed|attention|error/i.test(status.message) ? status.message :
    status.running ? `${status.active} live ${status.active === 1 ? 'avatar' : 'avatars'} · ${status.source_status || 'Waiting for Anvil data'}` :
    status.canStart ? 'Anvil input · Local network' : 'Wait for city preparation or the scenario to finish.');
  return <div className={styles.control}>
    <button type="button" onClick={() => void toggle()} disabled={busy || !status?.available || status.busy || !status.running && !status.canStart}>
      {busy || status?.busy ? 'Preparing avatars…' : status?.running ? 'Stop live avatars' : 'Start live avatars'}
    </button>
    <span role="status" title={status?.source_error || message}>{message}</span>
  </div>;
}
