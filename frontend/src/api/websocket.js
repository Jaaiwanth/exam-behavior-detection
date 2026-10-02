// src/api/websocket.js
// Thin WebSocket wrapper used by both student and faculty pages.

const WS_BASE = import.meta.env.VITE_WS_URL || "ws://localhost:8000";

/**
 * Open a WebSocket and attach handlers.
 * Returns the WebSocket instance so the caller can close it.
 *
 * @param {string}   path         - e.g. "/ws/student/s001"
 * @param {function} onMessage    - called with parsed JSON payload
 * @param {function} [onOpen]     - called when connection opens
 * @param {function} [onClose]    - called when connection closes
 * @param {function} [onError]    - called on error
 * @returns {WebSocket}
 */
export function openSocket(path, onMessage, onOpen, onClose, onError) {
  const ws = new WebSocket(`${WS_BASE}${path}`);

  ws.onopen = () => {
    console.log(`[WS] Connected: ${path}`);
    onOpen?.();
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      onMessage(data);
    } catch (e) {
      console.warn("[WS] Could not parse message:", e);
    }
  };

  ws.onclose = () => {
    console.log(`[WS] Disconnected: ${path}`);
    onClose?.();
  };

  ws.onerror = (err) => {
    console.error(`[WS] Error on ${path}:`, err);
    onError?.(err);
  };

  return ws;
}

/**
 * Send a JSON message over an open WebSocket.
 * Silently drops the message if the socket is not OPEN.
 */
export function sendJSON(ws, payload) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(payload));
  }
}
