import { useCallback, useEffect, useRef, useState } from "react";

/**
 * A small websocket hook with automatic reconnect (exponential backoff)
 * and resubscribe-on-reconnect, used by the dashboard, review room, and
 * chat consumers.
 */
export function useWebSocket(path, { token, onMessage } = {}) {
  const [connected, setConnected] = useState(false);
  const wsRef = useRef(null);
  const attemptRef = useRef(0);
  const onMessageRef = useRef(onMessage);

  // Consumers commonly pass inline callbacks. Keep the latest callback without
  // treating that render-only change as a reason to recreate the socket.
  useEffect(() => {
    onMessageRef.current = onMessage;
  }, [onMessage]);

  useEffect(() => {
    let disposed = false;
    let reconnectTimer = null;

    const connect = () => {
      if (disposed) return;

      const base = import.meta.env.VITE_WS_BASE_URL || `ws://${window.location.host}`;
      const url = `${base}${path}${token ? `?token=${token}` : ""}`;
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        if (disposed || wsRef.current !== ws) return;
        setConnected(true);
        attemptRef.current = 0;
      };

      ws.onmessage = (event) => {
        onMessageRef.current?.(JSON.parse(event.data));
      };

      ws.onclose = () => {
        if (wsRef.current === ws) {
          wsRef.current = null;
        }
        if (disposed) return;

        setConnected(false);
        const delay = Math.min(1000 * 2 ** attemptRef.current, 15000);
        attemptRef.current += 1;
        reconnectTimer = window.setTimeout(connect, delay);
      };
    };

    connect();

    return () => {
      disposed = true;
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [path, token]);

  const send = useCallback((data) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data));
    }
  }, []);

  return { connected, send };
}
