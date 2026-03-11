// ============================================================================
// TASKMASTER — Background Service Worker v3
// Added: time-per-domain tracking, random mid-task screenshots
// ============================================================================

const API_BASE              = "http://localhost:5000";
const GEMINI_API_KEY        = ""; // your key here
const GEMINI_MODEL          = "gemini-2.5-flash";
const INACTIVITY_LIMIT_MINS = 15;
const LONG_PAUSE_LIMIT_MINS = 15;

// ── IN-MEMORY STATE ───────────────────────────────────────────────────────────


let lastActivityTime = Date.now();
let checkinPending   = false;

// URL + domain time tracking
let visitedUrls      = [];   // raw URLs
let domainTime       = {};   // { "youtube.com": 180000, "notion.so": 420000 } in ms
let currentDomain    = null; // domain currently active
let domainSwitchedAt = null; // when we switched to currentDomain

// Mid-task screenshots
let midTaskShots     = [];   // array of base64 jpeg strings, max 3
let nextShotAt       = null; // timestamp for next random capture

// ── HELPERS ───────────────────────────────────────────────────────────────────

function getDomain(url) {
  try { return new URL(url).hostname.replace(/^www\./, ""); }
  catch { return null; }
}

function flushCurrentDomain() {
  if (currentDomain && domainSwitchedAt) {
    domainTime[currentDomain] = (domainTime[currentDomain] || 0) + (Date.now() - domainSwitchedAt);
  }
}

function switchDomain(url) {
  const domain = getDomain(url);
  if (!domain || domain === currentDomain) return;
  flushCurrentDomain();
  currentDomain    = domain;
  domainSwitchedAt = Date.now();
  if (!visitedUrls.includes(url)) visitedUrls.push(url);
  if (visitedUrls.length > 50) visitedUrls.shift();
}

function resetTrackingState() {
  flushCurrentDomain();
  visitedUrls      = [];
  domainTime       = {};
  currentDomain    = null;
  domainSwitchedAt = null;
  midTaskShots     = [];
  nextShotAt       = null;
  checkinPending   = false;
}

function scheduleNextShot(taskMins) {
  // Schedule 2-3 random screenshots during the task window
  // Space them out: first between 20-40% mark, second between 50-70% mark
  const taskMs    = taskMins * 60 * 1000;
  const first     = taskMs * (0.20 + Math.random() * 0.20);
  const second    = taskMs * (0.50 + Math.random() * 0.20);
  const shotTimes = [first, second];
  // store as offsets from now — background will check each alarm tick
  chrome.storage.local.get(["taskStartTime"], (data) => {
    const start = data.taskStartTime || Date.now();
    const shots = shotTimes.map(offset => start + offset);
    chrome.storage.local.set({ scheduledShots: shots, shotsTaken: 0 });
  });
}

async function captureMidShot() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab) return;
    const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: "jpeg", quality: 60 });
    const base64  = dataUrl.split(",")[1];
    if (midTaskShots.length < 3) midTaskShots.push(base64);
    // increment shotsTaken
    chrome.storage.local.get(["shotsTaken"], (data) => {
      chrome.storage.local.set({ shotsTaken: (data.shotsTaken || 0) + 1 });
    });
  } catch (err) {
    console.warn("Mid-task shot failed:", err);
  }
}

function buildDomainSummary() {
  flushCurrentDomain(); // include time on current domain
  const entries = Object.entries(domainTime)
    .sort((a, b) => b[1] - a[1]) // sort by time spent desc
    .map(([domain, ms]) => `${domain} (${Math.round(ms / 60000)}min)`);
  return entries.length ? entries.join(", ") : "no domain data";
}

// ── INIT ─────────────────────────────────────────────────────────────────────

chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.local.set({
    focusMode:      false,
    isPaused:       false,
    currentTaskId:  null,
    taskStartTime:  null,
    totalPausedMs:  0,
    pausedAt:       null,
    tasks:          [],
    lastSynced:     null,
    scheduledShots: [],
    shotsTaken:     0,
  });
  chrome.alarms.create("inactivityCheck", { periodInMinutes: 1 });
  chrome.alarms.create("pauseCheck",      { periodInMinutes: 1 });
  chrome.alarms.create("shotCheck",       { periodInMinutes: 1 });
  console.log("TASKMASTER v3 installed.");
});

chrome.runtime.onStartup.addListener(() => {
  pingLaptop();
  syncTasks();
  chrome.alarms.create("inactivityCheck", { periodInMinutes: 1 });
  chrome.alarms.create("pauseCheck",      { periodInMinutes: 1 });
  chrome.alarms.create("shotCheck",       { periodInMinutes: 1 });
});

// ── MESSAGE HANDLER ───────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {

  if (msg.type === "ACTIVITY_PING") {
    lastActivityTime = Date.now();
    if (sender.tab?.url) switchDomain(sender.tab.url);
    return;
  }

  if (msg.type === "GET_STATE") {
    chrome.storage.local.get(
      ["focusMode","isPaused","currentTaskId","tasks","taskStartTime","totalPausedMs","pausedAt"],
      (data) => sendResponse(data)
    );
    return true;
  }

  if (msg.type === "SET_FOCUS") {
    if (!msg.value) {
      resetTrackingState();
      chrome.storage.local.set({
        focusMode: false, isPaused: false,
        currentTaskId: null, taskStartTime: null,
        totalPausedMs: 0, pausedAt: null,
        scheduledShots: [], shotsTaken: 0,
      });
    } else {
      lastActivityTime = Date.now();
      pingLaptop();
      chrome.storage.local.set({ focusMode: true, isPaused: false });
    }
    sendResponse({ ok: true });
    return;
  }

  if (msg.type === "SET_PAUSE") {
    if (msg.value) {
      flushCurrentDomain(); // stop counting domain time while paused
      currentDomain    = null;
      domainSwitchedAt = null;
      chrome.storage.local.set({ isPaused: true, pausedAt: Date.now() });
    } else {
      chrome.storage.local.get(["pausedAt","totalPausedMs"], (data) => {
        const extra = Date.now() - (data.pausedAt || Date.now());
        const total = (data.totalPausedMs || 0) + extra;
        chrome.storage.local.set({ isPaused: false, pausedAt: null, totalPausedMs: total });
        lastActivityTime = Date.now();
      });
    }
    sendResponse({ ok: true });
    return;
  }

  if (msg.type === "START_TASK") {
    resetTrackingState();
    lastActivityTime = Date.now();
    const now = Date.now();
    chrome.storage.local.set({
      currentTaskId:  msg.taskId,
      taskStartTime:  now,
      focusMode:      true,
      isPaused:       false,
      totalPausedMs:  0,
      pausedAt:       null,
      scheduledShots: [],
      shotsTaken:     0,
    });
    // schedule mid-task screenshots after we know task minutes
    chrome.storage.local.get(["tasks"], (data) => {
      const task = (data.tasks || []).find(t => t.id === msg.taskId);
      if (task) scheduleNextShot(task.minutes);
    });
    sendResponse({ ok: true });
    return;
  }

  if (msg.type === "COMPLETE_TASK") {
    handleTaskCompletion(msg.taskId, sendResponse);
    return true;
  }

  if (msg.type === "CONFIRM_DONE") {
    completeTaskInAPI(msg.taskId).then(() => {
      resetTrackingState();
      chrome.storage.local.set({
        currentTaskId: null, taskStartTime: null,
        focusMode: false, isPaused: false,
        totalPausedMs: 0, pausedAt: null,
        scheduledShots: [], shotsTaken: 0,
      });
      syncTasks().then((tasks) => sendResponse({ ok: true, tasks }));
    });
    return true;
  }

  if (msg.type === "SYNC_TASKS") {
    syncTasks().then((tasks) => sendResponse({ tasks }));
    return true;
  }

  if (msg.type === "ADD_TASK") {
    addTaskToAPI(msg.name, msg.minutes).then((task) => sendResponse({ task }));
    return true;
  }
});

// ── TAB TRACKING ──────────────────────────────────────────────────────────────

chrome.tabs.onActivated.addListener(({ tabId }) => {
  chrome.storage.local.get(["focusMode","isPaused"], (data) => {
    if (!data.focusMode || data.isPaused) return;
    chrome.tabs.get(tabId, (tab) => {
      if (tab?.url) switchDomain(tab.url);
    });
  });
});

// ── ALARMS ───────────────────────────────────────────────────────────────────

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "inactivityCheck") checkInactivity();
  if (alarm.name === "pauseCheck")      checkLongPause();
  if (alarm.name === "shotCheck")       checkMidShot();
});

function checkInactivity() {
  chrome.storage.local.get(["focusMode","isPaused","currentTaskId"], (data) => {
    if (!data.focusMode || data.isPaused || !data.currentTaskId) return;
    if (checkinPending) return;
    const mins = (Date.now() - lastActivityTime) / 60000;
    if (mins >= INACTIVITY_LIMIT_MINS) {
      checkinPending = true;
      triggerCheckin(data.currentTaskId);
    }
  });
}

function checkLongPause() {
  chrome.storage.local.get(
    ["focusMode","isPaused","pausedAt","currentTaskId","taskStartTime","totalPausedMs","tasks"],
    (data) => {
      if (!data.focusMode || !data.isPaused || !data.pausedAt) return;
      const pausedMins = (Date.now() - data.pausedAt) / 60000;
      if (pausedMins >= LONG_PAUSE_LIMIT_MINS) {
        const task = (data.tasks || []).find(t => t.id === data.currentTaskId);
        if (!task) return;
        const totalPausedMs = (data.totalPausedMs || 0) + (Date.now() - data.pausedAt);
        const elapsedSecs   = (Date.now() - data.taskStartTime - totalPausedMs) / 1000;
        const remainingMins = Math.max(0, Math.round((task.minutes * 60 - elapsedSecs) / 60));
        firePauseAlert(task.name, Math.round(pausedMins), remainingMins);
      }
    }
  );
}

function checkMidShot() {
  chrome.storage.local.get(
    ["focusMode","isPaused","scheduledShots","shotsTaken","currentTaskId"],
    (data) => {
      if (!data.focusMode || data.isPaused || !data.currentTaskId) return;
      const shots = data.scheduledShots || [];
      const taken = data.shotsTaken || 0;
      if (taken >= shots.length) return;
      const nextShot = shots[taken];
      if (Date.now() >= nextShot) captureMidShot();
    }
  );
}

// ── CHECKIN ───────────────────────────────────────────────────────────────────

async function triggerCheckin(taskId) {
  chrome.storage.local.get(["tasks"], async (data) => {
    const task     = (data.tasks || []).find(t => t.id === taskId);
    const taskName = task ? task.name : "your current task";
    const mins     = Math.round((Date.now() - lastActivityTime) / 60000);
    const message  = await geminiCheckin(taskName, mins);

    chrome.runtime.sendMessage({ type: "SHOW_CHECKIN", message, taskId })
      .catch(() => {
        chrome.notifications.create("inactivity_" + Date.now(), {
          type: "basic", iconUrl: "icon.png",
          title: "TASKMASTER", message, priority: 2,
        });
      });
  });
}

// ── TASK COMPLETION ───────────────────────────────────────────────────────────

async function handleTaskCompletion(taskId, sendResponse) {
  chrome.storage.local.get(
    ["tasks","taskStartTime","totalPausedMs","pausedAt"],
    async (data) => {
      const task = (data.tasks || []).find(t => t.id === taskId);
      if (!task) {
        sendResponse({ verdict: { approved: false, hardReject: true, message: "Task not found." } });
        return;
      }

      // ── TIME ENFORCEMENT ──────────────────────────────────────────────────
      const totalPausedMs = data.totalPausedMs || 0;
      const elapsedMs     = Date.now() - (data.taskStartTime || Date.now()) - totalPausedMs;
      const elapsedMins   = elapsedMs / 60000;
      const taskMins      = task.minutes;
      const minPct        = taskMins < 30 ? 0.50 : taskMins <= 120 ? 0.60 : 0.70;
      const minMins       = taskMins * minPct;

      if (elapsedMins < minMins) {
        const needed = Math.ceil(minMins - elapsedMins);
        sendResponse({
          verdict: {
            approved:   false,
            hardReject: true,
            message:    `You've only worked ${Math.round(elapsedMins)} min out of ${taskMins} min. Need at least ${Math.round(minMins)} min (${Math.round(minPct*100)}%). Come back in ${needed} min.`,
          }
        });
        return;
      }

      // ── SCREENSHOT + VERIFY ───────────────────────────────────────────────
      try {
        const [tab]      = await chrome.tabs.query({ active: true, currentWindow: true });
        const finalShot  = await chrome.tabs.captureVisibleTab(tab.windowId, { format: "jpeg", quality: 80 });
        const domainSummary = buildDomainSummary();
        const verdict    = await geminiVerifyScreenshot(finalShot, midTaskShots, task.name, elapsedMins, taskMins, domainSummary);
        sendResponse({ verdict });
      } catch (err) {
        console.error("Screenshot failed:", err);
        sendResponse({ verdict: { approved: true, hardReject: false, message: "Couldn't capture screenshot. Trusting you." } });
      }
    }
  );
}

// ── GEMINI ────────────────────────────────────────────────────────────────────

async function geminiCheckin(taskName, minsInactive) {
  const prompt = `You are TASKMASTER, a friendly-but-firm AI accountability agent.
The user has been inactive for ${minsInactive} minutes while working on: "${taskName}".
Write a SHORT (1-2 sentences) check-in message. Direct, slightly firm, warm.
Ask if they're still working. No bullets. No markdown.`;
  try {
    return await callGeminiText(prompt) || `Hey — ${minsInactive} min inactive. Still on "${taskName}"?`;
  } catch {
    return `Hey — ${minsInactive} min inactive. Still on "${taskName}"?`;
  }
}

async function geminiVerifyScreenshot(finalShotDataUrl, midShots, taskName, elapsedMins, taskMins, domainSummary) {
  const finalBase64 = finalShotDataUrl.split(",")[1];

  const prompt = `You are TASKMASTER, a strict AI accountability agent verifying task completion.

Task: "${taskName}"
Allocated time: ${taskMins} minutes
Time actually worked: ${Math.round(elapsedMins)} minutes
Time spent per website: ${domainSummary}

You have ${1 + midShots.length} screenshot(s) to analyze:
- Screenshot 1 is the FINAL screen when the user clicked "Done"
${midShots.map((_, i) => `- Screenshot ${i + 2} was taken at a RANDOM point DURING the task`).join("\n")}

Instructions:
- Look at ALL screenshots together, not just the final one
- If mid-task screenshots show clearly off-task activity (social media, videos, gaming, shopping) that's strong evidence against approval even if the final screenshot looks good
- If the user spent most of their time on irrelevant websites per the domain data, be skeptical
- Be reasonable — research, reading, note-taking all count. Occasional tab switches are fine.
- Reply ONLY in raw JSON (no markdown, no backticks):
{ "approved": true/false, "message": "2-3 sentence honest verdict mentioning what you saw across the screenshots" }`;

  // Build parts array — final shot first, then mid shots
  const parts = [
    { text: prompt },
    { inline_data: { mime_type: "image/jpeg", data: finalBase64 } },
    ...midShots.map(b64 => ({ inline_data: { mime_type: "image/jpeg", data: b64 } })),
  ];

  try {
    const res  = await fetch(
      `https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent?key=${GEMINI_API_KEY}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ contents: [{ parts }] }),
      }
    );
    const data   = await res.json();
    const text   = data.candidates?.[0]?.content?.parts?.[0]?.text?.trim();
    const parsed = JSON.parse(text);
    return { ...parsed, hardReject: false };
  } catch {
    return { approved: true, hardReject: false, message: "Couldn't verify. Marking done." };
  }
}

async function callGeminiText(prompt) {
  const res  = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent?key=${GEMINI_API_KEY}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ contents: [{ parts: [{ text: prompt }] }] }),
    }
  );
  const data = await res.json();
  return data.candidates?.[0]?.content?.parts?.[0]?.text?.trim();
}

// ── ALERTS ────────────────────────────────────────────────────────────────────

async function firePauseAlert(taskName, pausedMins, remainingMins) {
  try {
    await fetch(`${API_BASE}/alerts/pause`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ taskName, pausedMins, remainingMins }),
    });
  } catch (err) {
    console.error("Pause alert failed:", err);
  }
}

// ── API ───────────────────────────────────────────────────────────────────────

async function syncTasks() {
  try {
    const res   = await fetch(`${API_BASE}/tasks`);
    const data  = await res.json();
    const tasks = data.tasks || [];
    chrome.storage.local.set({ tasks, lastSynced: Date.now() });
    return tasks;
  } catch (err) {
    console.error("Sync failed:", err);
    return [];
  }
}

async function pingLaptop() {
  try {
    await fetch(`${API_BASE}/tasks/laptop-ping`, { method: "POST" });
  } catch (err) {
    console.error("Laptop ping failed:", err);
  }
}

async function addTaskToAPI(name, minutes) {
  try {
    const res  = await fetch(`${API_BASE}/tasks/add`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, minutes }),
    });
    const data = await res.json();
    await syncTasks();
    return data.task;
  } catch (err) {
    console.error("Add task failed:", err);
    return null;
  }
}

async function completeTaskInAPI(taskId) {
  try {
    await fetch(`${API_BASE}/tasks/complete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: taskId, verified: true }),
    });
    await syncTasks();
  } catch (err) {
    console.error("Complete task sync failed:", err);
  }
}

function resetCheckin() {
  checkinPending   = false;
  lastActivityTime = Date.now();
}