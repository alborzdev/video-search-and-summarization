// SPDX-License-Identifier: MIT
import React, { useEffect, useRef, useState } from 'react';

interface LiveStreamModalProps {
  isOpen: boolean;
  streamId: string;
  title: string;
  vstApiUrl?: string | null;
  onClose: () => void;
}

type SignalingMessage = {
  apiKey?: string;
  data?: Record<string, unknown>;
};

const createPeerId = (): string => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `vss-live-${Date.now()}-${Math.random().toString(36).slice(2)}`;
};

const createWebSocketUrl = (vstApiUrl: string, streamId: string, peerId: string): string => {
  const url = new URL(vstApiUrl);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  url.pathname = `${url.pathname.replace(/\/$/, '')}/v1/live/ws`;
  url.search = '';
  url.searchParams.set('connectionId', peerId);
  url.searchParams.set('streamId', streamId);
  return url.toString();
};

export const LiveStreamModal: React.FC<LiveStreamModalProps> = ({ isOpen, streamId, title, vstApiUrl, onClose }) => {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [status, setStatus] = useState<'connecting' | 'playing' | 'error'>('connecting');
  const [errorMessage, setErrorMessage] = useState('');

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog || !isOpen) return;
    try {
      if (!dialog.open) dialog.showModal();
    } catch {
      dialog.setAttribute('open', '');
    }
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen || !streamId || !vstApiUrl) return;

    let disposed = false;
    let peerConnection: RTCPeerConnection | null = null;
    let mediaSessionId: string | null = null;
    let websocket: WebSocket | null = null;
    const peerId = createPeerId();
    const pendingCandidates: RTCIceCandidateInit[] = [];
    const fallbackStream = new MediaStream();

    setStatus('connecting');
    setErrorMessage('');

    const fail = (message: string) => {
      if (disposed) return;
      setStatus('error');
      setErrorMessage(message);
    };

    const send = (apiKey: string, data: Record<string, unknown> = {}) => {
      if (websocket?.readyState !== WebSocket.OPEN) return;
      websocket.send(JSON.stringify({ apiKey, peerId, data }));
    };

    const addRemoteCandidate = async (candidate: RTCIceCandidateInit) => {
      if (!peerConnection?.remoteDescription) {
        pendingCandidates.push(candidate);
        return;
      }
      try {
        await peerConnection.addIceCandidate(candidate);
      } catch {
        fail('The live stream connection could not exchange network candidates.');
      }
    };

    const startPeerConnection = async (iceServers: RTCIceServer[]) => {
      if (disposed || peerConnection) return;

      const pc = new RTCPeerConnection({ iceServers });
      peerConnection = pc;
      pc.addTransceiver('audio', { direction: 'recvonly' });
      pc.addTransceiver('video', { direction: 'recvonly' });

      pc.ontrack = (event) => {
        const video = videoRef.current;
        if (!video) return;
        const stream = event.streams[0];
        if (stream) {
          video.srcObject = stream;
        } else {
          fallbackStream.addTrack(event.track);
          video.srcObject = fallbackStream;
        }
        void video.play().catch(() => {
          video.muted = true;
          void video.play();
        });
      };

      pc.onicecandidate = (event) => {
        if (!event.candidate) return;
        send('api/v1/live/iceCandidate', {
          peerId,
          candidate: event.candidate.toJSON(),
        });
      };

      pc.onconnectionstatechange = () => {
        if (pc.connectionState === 'connected') setStatus('playing');
        if (pc.connectionState === 'failed' || pc.connectionState === 'disconnected') {
          fail('The live stream connection was interrupted.');
        }
      };

      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      send('api/v1/live/stream/start', {
        clientIpAddr: null,
        peerId,
        sessionDescription: pc.localDescription,
        options: { quality: 'auto', rtptransport: 'udp', timeout: 60 },
        streamId,
      });
    };

    try {
      websocket = new WebSocket(createWebSocketUrl(vstApiUrl, streamId, peerId));
    } catch {
      fail('The live stream endpoint is not configured correctly.');
      return;
    }

    websocket.onopen = () => {
      send('api/v1/live/iceServers', { peerId });
    };

    websocket.onerror = () => {
      fail('Could not connect to the live stream service.');
    };

    websocket.onmessage = (event) => {
      void (async () => {
        let message: SignalingMessage;
        try {
          message = JSON.parse(String(event.data)) as SignalingMessage;
        } catch {
          return;
        }

        const data = message.data ?? {};
        if (message.apiKey === 'api/v1/live/iceServers') {
          const iceServers = Array.isArray(data.iceServers) ? (data.iceServers as RTCIceServer[]) : [];
          try {
            await startPeerConnection(iceServers);
          } catch {
            fail('Could not initialize live video playback.');
          }
          return;
        }

        if (message.apiKey === 'api/v1/live/setAnswer') {
          if (!peerConnection) return;
          mediaSessionId = typeof data.mediaSessionId === 'string' ? data.mediaSessionId : null;
          if (typeof data.sdp !== 'string' || typeof data.type !== 'string') {
            fail('The live stream service returned an invalid answer.');
            return;
          }
          try {
            await peerConnection.setRemoteDescription({
              sdp: data.sdp,
              type: data.type as RTCSdpType,
            });
            for (const candidate of pendingCandidates.splice(0)) {
              await peerConnection.addIceCandidate(candidate);
            }
          } catch {
            fail('The live stream answer could not be applied.');
          }
          return;
        }

        if (message.apiKey === 'api/v1/live/iceCandidate') {
          const candidates = Array.isArray(data) ? data : Object.values(data);
          for (const candidate of candidates) {
            if (candidate && typeof candidate === 'object' && 'candidate' in candidate) {
              await addRemoteCandidate(candidate as RTCIceCandidateInit);
            }
          }
          return;
        }

        if (message.apiKey === 'api/v1/live/stream/status' && data.error) {
          fail(String(data.error));
        }
      })();
    };

    return () => {
      disposed = true;
      if (websocket?.readyState === WebSocket.OPEN && mediaSessionId) {
        send('api/v1/live/stream/stop', { peerId, mediaSessionId });
      }
      websocket?.close();
      peerConnection?.close();
      if (videoRef.current) videoRef.current.srcObject = null;
    };
  }, [isOpen, streamId, vstApiUrl]);

  if (!isOpen) return null;

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby="live-stream-modal-title"
      data-testid="live-stream-modal"
      className="z-50 grid place-items-center overflow-hidden backdrop:bg-black/60 backdrop:backdrop-blur-sm"
      style={{
        position: 'fixed',
        inset: 0,
        width: '100vw',
        height: '100vh',
        maxWidth: 'none',
        maxHeight: 'none',
        margin: 0,
        padding: 0,
        border: 'none',
        background: 'transparent',
      }}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="relative mx-4 flex w-[min(80vw,1400px)] max-h-[90vh] flex-col overflow-hidden rounded-2xl bg-white shadow-2xl dark:bg-neutral-900">
        <div className="shrink-0 border-b-2 border-brand-green px-6 py-4 flex items-center justify-between text-black dark:text-white">
          <div>
            <h4 id="live-stream-modal-title" className="text-lg font-semibold">
              {title}
            </h4>
            <p className="text-xs text-gray-500 dark:text-gray-400">Live camera</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex h-10 w-10 items-center justify-center rounded-lg text-2xl text-gray-600 hover:bg-brand-green-dark hover:text-white dark:text-gray-300"
            aria-label="Close live stream"
          >
            ×
          </button>
        </div>
        <div className="relative aspect-video min-h-0 bg-black">
          <video
            ref={videoRef}
            controls
            autoPlay
            playsInline
            className="h-full w-full object-contain"
            onPlaying={() => setStatus('playing')}
          />
          {status !== 'playing' && (
            <div className="absolute inset-0 flex items-center justify-center bg-black/80 px-6 text-center text-white">
              {status === 'connecting' ? 'Connecting to live camera…' : errorMessage}
            </div>
          )}
        </div>
      </div>
    </dialog>
  );
};
