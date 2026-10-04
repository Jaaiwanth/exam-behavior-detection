// src/hooks/useProctoring.js — webcam + monitoring WebSocket for the exam room
//
// One camera stream, one WebSocket, one capture loop:
//
//   requestCamera()   getUserMedia once (permission prompt); reused for preview AND frames
//   startMonitoring() open /ws/student/{uid}?exam_id=..&session_id=.. , authenticate with the
//                     Firebase ID token, then send a JPEG frame every 500 ms (~2 FPS)
//   stop()            close the socket cleanly and stop every camera track
//
// The student never receives a score or warning from the server — only calibration progress.
// Socket drops reconnect automatically with backoff; the exam UI never depends on the socket.

import { useCallback, useEffect, useRef, useState } from "react";
import { auth } from "../firebase";
import { openSocket, sendJSON } from "../api/websocket.js";

const FRAME_INTERVAL_MS = 500;      // ~2 FPS, the rate the ML pipeline expects
const JPEG_QUALITY = 0.7;
const MAX_BUFFERED_BYTES = 1_000_000;
const MAX_BACKOFF_MS = 10_000;

// Close codes sent by the backend
const CLOSE_REPLACED = 4000;        // the same student connected from another tab/device
const CLOSE_NOT_AUTHENTICATED = 4401;
const CLOSE_FORBIDDEN = 4403;

function describeCameraError(err) {
  switch (err?.name) {
    case "NotAllowedError":
    case "PermissionDeniedError":
      return { state: "denied", message: "Camera permission was denied. Allow camera access in your browser's address bar, then try again." };
    case "NotFoundError":
    case "DevicesNotFoundError":
      return { state: "error", message: "No camera was found on this device." };
    case "NotReadableError":
    case "TrackStartError":
      return { state: "error", message: "Your camera is being used by another application. Close it and try again." };
    default:
      return { state: "error", message: `Could not start the camera (${err?.message || err}).` };
  }
}

const firebaseToken = async () => auth.currentUser?.getIdToken();

/** getToken is injectable only so the dev harness can run without a Firebase login. */
export default function useProctoring({ uid, examId, getToken = firebaseToken }) {
  const [camera, setCamera]             = useState("idle");   // idle | requesting | ready | denied | error | lost
  const [cameraError, setCameraError]   = useState("");
  const [stream, setStream]             = useState(null);
  const [monitor, setMonitor]           = useState("off");    // off | connecting | live | reconnecting | unavailable
  const [calibrating, setCalibrating]   = useState(false);
  const [calibProgress, setCalibProgress] = useState(0);

  const streamRef    = useRef(null);
  const videoRef     = useRef(null);   // detached <video> the frames are drawn from
  const canvasRef    = useRef(null);
  const wsRef        = useRef(null);
  const authedRef    = useRef(false);
  const activeRef    = useRef(false);  // monitoring requested and not stopped
  const timerRef     = useRef(null);
  const retryRef     = useRef({ timer: null, attempts: 0 });
  const connectRef   = useRef(() => {});

  /* ── camera ──────────────────────────────────────────────────── */
  const releaseStream = useCallback(() => {
    streamRef.current?.getTracks().forEach(t => { t.onended = null; t.stop(); });
    streamRef.current = null;
    if (videoRef.current) { videoRef.current.srcObject = null; videoRef.current = null; }
    setStream(null);
  }, []);

  const requestCamera = useCallback(async () => {
    // Reuse a live stream — never open a second camera.
    const live = streamRef.current?.getVideoTracks().some(t => t.readyState === "live");
    if (live) { setCamera("ready"); return true; }

    releaseStream();
    setCamera("requesting");
    setCameraError("");
    try {
      const s = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" },
        audio: false,
      });
      streamRef.current = s;
      s.getVideoTracks().forEach(t => {
        t.onended = () => {            // unplugged / revoked / taken by another app
          setCamera("lost");
          setCameraError("Your camera was disconnected.");
        };
      });

      const v = document.createElement("video");
      v.muted = true;
      v.playsInline = true;
      v.srcObject = s;
      await v.play().catch(() => {});
      videoRef.current = v;

      setStream(s);
      setCamera("ready");
      return true;
    } catch (err) {
      const { state, message } = describeCameraError(err);
      setCamera(state);
      setCameraError(message);
      return false;
    }
  }, [releaseStream]);

  /* ── frame capture ───────────────────────────────────────────── */
  const startCapture = useCallback(() => {
    clearInterval(timerRef.current);
    timerRef.current = setInterval(() => {
      const ws = wsRef.current, video = videoRef.current;
      if (!authedRef.current || !ws || ws.readyState !== WebSocket.OPEN) return;
      if (!video || video.readyState < 2 || !video.videoWidth) return;
      if (ws.bufferedAmount > MAX_BUFFERED_BYTES) return;          // network is behind: drop a frame
      if (streamRef.current?.getVideoTracks().every(t => t.readyState !== "live")) return;

      const canvas = canvasRef.current || (canvasRef.current = document.createElement("canvas"));
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      canvas.getContext("2d").drawImage(video, 0, 0);
      sendJSON(ws, { type: "frame", data: canvas.toDataURL("image/jpeg", JPEG_QUALITY) });
    }, FRAME_INTERVAL_MS);
  }, []);

  /* ── websocket ───────────────────────────────────────────────── */
  const scheduleReconnect = useCallback(() => {
    if (!activeRef.current) return;
    const r = retryRef.current;
    const delay = Math.min(1000 * 2 ** r.attempts, MAX_BACKOFF_MS);
    r.attempts += 1;
    setMonitor("reconnecting");
    clearTimeout(r.timer);
    r.timer = setTimeout(() => connectRef.current(), delay);
  }, []);

  const connect = useCallback(() => {
    if (!activeRef.current) return;
    const existing = wsRef.current;
    if (existing && (existing.readyState === WebSocket.OPEN || existing.readyState === WebSocket.CONNECTING)) return;

    authedRef.current = false;
    setMonitor(m => (m === "live" || m === "reconnecting" ? "reconnecting" : "connecting"));

    const path = `/ws/student/${encodeURIComponent(uid)}?exam_id=${encodeURIComponent(examId)}` +
                 `&session_id=${encodeURIComponent(`${examId}__${uid}`)}`;
    let ws;
    ws = openSocket(
      path,
      (msg) => {
        if (wsRef.current !== ws) return;
        if (msg.type === "auth_ok") {
          authedRef.current = true;
          retryRef.current.attempts = 0;
          setMonitor("live");
        } else if (msg.type === "status") {
          setCalibrating(!!msg.calibrating);
          setCalibProgress(msg.calib_progress || 0);
        }
      },
      async () => {
        try {
          const token = await getToken();
          if (!token) throw new Error("not signed in");
          sendJSON(ws, { type: "auth", token });
        } catch {
          ws.close();
        }
      },
      (event) => {
        if (wsRef.current === ws) wsRef.current = null;
        authedRef.current = false;
        if (!activeRef.current) return;                      // we closed it on purpose
        const code = event?.code;
        if (code === CLOSE_REPLACED || code === CLOSE_FORBIDDEN) { setMonitor("unavailable"); return; }
        if (code === CLOSE_NOT_AUTHENTICATED && retryRef.current.attempts >= 3) { setMonitor("unavailable"); return; }
        scheduleReconnect();
      },
      () => { /* errors are followed by onclose, which handles the retry */ },
    );
    wsRef.current = ws;
  }, [uid, examId, getToken, scheduleReconnect]);

  useEffect(() => { connectRef.current = connect; }, [connect]);

  const startMonitoring = useCallback(() => {
    activeRef.current = true;
    retryRef.current.attempts = 0;
    connect();
    startCapture();
  }, [connect, startCapture]);

  /** Close the socket cleanly and release the camera. Safe to call repeatedly. */
  const stop = useCallback(() => {
    activeRef.current = false;
    clearInterval(timerRef.current);
    clearTimeout(retryRef.current.timer);
    const ws = wsRef.current;
    wsRef.current = null;
    authedRef.current = false;
    if (ws) { try { ws.close(1000, "exam finished"); } catch { /* already closed */ } }
    releaseStream();
    setMonitor("off");
    setCamera("idle");
    setCalibrating(false);
  }, [releaseStream]);

  useEffect(() => stop, [stop]);   // unmount cleanup

  return {
    camera, cameraError, stream,
    monitor, calibrating, calibProgress,
    requestCamera, startMonitoring, stop,
  };
}
