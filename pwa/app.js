// Simple frontend. Auto-detect API when possible; default to localhost:8000 during local dev.
const API = (() => {
  try {
    const u = new URL(location.href);
    // If we're serving the PWA on 5500 (python http.server), assume backend is on 8000.
    if (u.port === "5500") return "http://127.0.0.1:8000";
    // Otherwise talk to same origin (works if you ever proxy or deploy together).
    return `${u.protocol}//${u.hostname}${u.port ? ":" + u.port : ""}`;
  } catch {
    return "http://127.0.0.1:8000";
  }
})();

// ---- DOM ----
const $date      = document.getElementById("date");
const $btnToday  = document.getElementById("btnToday");
const $btnLoad   = document.getElementById("btnLoad");
const $status    = document.getElementById("status");
const $list      = document.getElementById("list");

// ---- Utils ----
const toLocalISODate = (d = new Date()) => {
  // Convert to local YYYY-MM-DD (avoids UTC shift issues of toISOString())
  const tz = d.getTimezoneOffset() * 60000;
  return new Date(d.getTime() - tz).toISOString().slice(0, 10);
};

const setStatus = (msg) => { $status.textContent = msg; };

const setLoading = (on) => {
  $btnToday.disabled = on;
  $btnLoad.disabled = on;
};

const li = (text) => {
  const el = document.createElement("li");
  el.textContent = text;
  return el;
};

const fetchJSON = async (url) => {
  const res = await fetch(url, { headers: { "Accept": "application/json" } });
  if (!res.ok) {
    const txt = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status} • ${txt || url}`);
  }
  return res.json();
};

// Render helper that tolerates a few payload shapes
function renderMatches(payload) {
  // Expected: { date: "YYYY-MM-DD", matches: [...] }
  let date = payload?.date ?? toLocalISODate();
  let matches = Array.isArray(payload) ? payload : (payload?.matches ?? []);

  $list.innerHTML = "";
  setStatus(`date: ${date} • matches: ${matches.length}`);

  if (!matches.length) {
    $list.appendChild(li("No matches for this date."));
    return;
  }

  for (const m of matches) {
    const when = new Date(m.date_utc || m.date || m.kickoff || Date.now());
    const timeLocal = when.toLocaleString();

    const league =
      m.league_name ||
      m.league?.name ||
      m.competition ||
      "—";

    const home = m.home_team || m.home || m.teams?.home?.name || "Home";
    const away = m.away_team || m.away || m.teams?.away?.name || "Away";

    const score =
      m.home_goals == null || m.away_goals == null
        ? "vs"
        : `${m.home_goals}–${m.away_goals}`;

    const line = `[${league}] ${home} ${score} ${away} — ${timeLocal}`;
    $list.appendChild(li(line));
  }
}

// ---- Actions ----
async function fetchToday() {
  try {
    setLoading(true);
    setStatus("loading /api/matches/today …");
    const data = await fetchJSON(`${API}/api/matches/today`);
    renderMatches(data);
  } catch (err) {
    console.error(err);
    setStatus(`error: ${err.message}`);
    $list.innerHTML = "";
  } finally {
    setLoading(false);
  }
}

async function fetchDate(d) {
  try {
    setLoading(true);
    setStatus(`loading /api/matches/date?d=${d} …`);
    const data = await fetchJSON(`${API}/api/matches/date?d=${encodeURIComponent(d)}`);
    renderMatches(data);
  } catch (err) {
    console.error(err);
    setStatus(`error: ${err.message}`);
    $list.innerHTML = "";
  } finally {
    setLoading(false);
  }
}

// ---- Wire up ----
$date.value = toLocalISODate();       // default to local today
$btnToday.addEventListener("click", () => fetchToday());
$btnLoad.addEventListener("click", () => fetchDate($date.value || toLocalISODate()));

// Initial load
fetchToday().catch(err => setStatus(`error: ${err.message}`));