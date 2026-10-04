// DEV/TEST ONLY — see proctor-harness.html. Exercises the real useProctoring hook
// (camera -> WebSocket -> ML pipeline) without Firebase login or Firestore.
import React, { useEffect } from "react";
import ReactDOM from "react-dom/client";
import useProctoring from "../hooks/useProctoring.js";

const params = new URLSearchParams(window.location.search);
const UID  = params.get("uid")  || "harness-student";
const EXAM = params.get("exam") || "harness-exam";
const getToken = async () => "harness-token";   // backend runs with WS_AUTH=0 for this test

function Harness() {
  const p = useProctoring({ uid: UID, examId: EXAM, getToken });

  // Expose state to the Playwright test
  useEffect(() => {
    window.__proctor = {
      camera: p.camera, monitor: p.monitor,
      calibrating: p.calibrating, calibProgress: p.calibProgress,
      tracks: p.stream ? p.stream.getTracks().map(t => t.readyState) : [],
    };
  });
  useEffect(() => { window.__proctorApi = p; });

  // "refresh" simulation: ?resume=1 re-acquires the camera and reconnects immediately
  useEffect(() => {
    if (params.get("resume") === "1") p.requestCamera().then(ok => ok && p.startMonitoring());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div style={{ fontFamily: "monospace", padding: 16 }}>
      <h3>Proctoring harness — {UID} / {EXAM}</h3>
      <button id="enable" onClick={p.requestCamera}>Enable camera</button>{" "}
      <button id="start" onClick={async () => { await document.documentElement.requestFullscreen().catch(() => {}); p.startMonitoring(); }}>Start</button>{" "}
      <button id="stop" onClick={p.stop}>Stop</button>
      <p>camera: <b id="camera">{p.camera}</b> | monitor: <b id="monitor">{p.monitor}</b> | calibrating: <b id="calib">{String(p.calibrating)}</b></p>
      <video
        id="preview" autoPlay muted playsInline width="320"
        ref={el => { if (el && p.stream && el.srcObject !== p.stream) el.srcObject = p.stream; }}
      />
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<Harness />);
