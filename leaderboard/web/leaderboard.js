// Real-time AI Arena leaderboard.
//
// Reads from Firestore at  leaderboard/{track_id}/entries  ordered by
// final_score desc.  Re-renders automatically when new submissions land.
//
// Security: read-only access enforced by firestore.rules.  Writes happen
// server-side from the Cloud Run evaluator using a service-account token.
//
// Replace the firebaseConfig values with the ones from your Firebase
// console (Project settings → General → Your apps → SDK setup).

import { initializeApp } from
  "https://www.gstatic.com/firebasejs/10.13.2/firebase-app.js";
import {
  getFirestore, collection, query, orderBy, limit, onSnapshot,
} from "https://www.gstatic.com/firebasejs/10.13.2/firebase-firestore.js";

const firebaseConfig = {
  // Fill in from Firebase console after running `firebase init hosting`.
  apiKey:            "REPLACE_ME",
  authDomain:        "ai-arena-platform.firebaseapp.com",
  projectId:         "ai-arena-platform",
  storageBucket:     "ai-arena-platform.appspot.com",
  messagingSenderId: "77646749251",
  appId:             "REPLACE_ME",
};

const app = initializeApp(firebaseConfig);
const db = getFirestore(app);

const TRACK_LABELS = {
  hallucination_hunter: "Hallucination Hunter",
  prompt_golf:          "Prompt Golf",
  rag_treasure_hunt:    "RAG Treasure Hunt",
  meta_judge:           "Build Your Own AI Judge",
};

const $ = (id) => document.getElementById(id);
let unsubscribe = null;

function render(entries) {
  const tbody = $("rows");
  tbody.innerHTML = "";
  if (!entries.length) {
    tbody.innerHTML =
      '<tr><td colspan="5" class="empty">No submissions yet for this track.</td></tr>';
    return;
  }
  entries.forEach((e, i) => {
    const tr = document.createElement("tr");
    const ts = new Date(e.scored_at);
    tr.innerHTML = `
      <td class="rank">${i + 1}</td>
      <td class="student">${escapeHtml(e.student_id)}</td>
      <td class="score">${Number(e.final_score).toFixed(4)}</td>
      <td class="sub">${escapeHtml(e.submission_id)}</td>
      <td class="time">${ts.toLocaleString()}</td>
    `;
    tbody.appendChild(tr);
  });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

function subscribe(trackId) {
  if (unsubscribe) unsubscribe();
  $("track-title").textContent = TRACK_LABELS[trackId] || trackId;
  $("status").textContent = "live";
  $("status").className = "live";
  const q = query(
    collection(db, "leaderboard", trackId, "entries"),
    orderBy("final_score", "desc"),
    limit(100),
  );
  unsubscribe = onSnapshot(q,
    (snap) => render(snap.docs.map((d) => d.data())),
    (err) => {
      console.error("Firestore subscription error:", err);
      $("status").textContent = "offline";
      $("status").className = "offline";
    }
  );
}

document.querySelectorAll("#track-tabs button").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("#track-tabs button").forEach(
      (b) => b.classList.remove("active"));
    btn.classList.add("active");
    subscribe(btn.dataset.track);
  });
});

subscribe("hallucination_hunter");
