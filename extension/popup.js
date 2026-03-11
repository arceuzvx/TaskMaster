// ============================================================================
// TASKMASTER — Popup JS v2
// Fixes: pause timer, hardReject (no "mark done anyway"), CONFIRM_DONE sync
// ============================================================================

let state = {
  tasks:         [],
  focusMode:     false,
  isPaused:      false,
  currentTaskId: null,
  taskStartTime: null,
  totalPausedMs: 0,
  pausedAt:      null,
};

let timerInterval = null;

// ── INIT ─────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", async () => {
  await loadState();
  renderAll();
  setupListeners();

  timerInterval = setInterval(() => {
    if (state.currentTaskId && state.focusMode && !state.isPaused) {
      updateTimer();
    }
  }, 1000);

  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === "SHOW_CHECKIN") showCheckin(msg.message, msg.taskId);
  });
});

async function loadState() {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage({ type: "GET_STATE" }, (data) => {
      if (data) Object.assign(state, data);
      resolve();
    });
  });
}

// ── RENDER ────────────────────────────────────────────────────────────────────

function renderAll() {
  renderFocusBar();
  renderActivePanel();
  renderTaskList();
  renderFooter();
}

function renderFocusBar() {
  const bar   = document.getElementById("focus-bar");
  const label = document.getElementById("focus-label");
  const sub   = document.getElementById("focus-sub");

  if (state.focusMode) {
    bar.classList.add("active");
    label.textContent = state.isPaused ? "PAUSED" : "FOCUS ON";
    sub.textContent   = state.isPaused
      ? "Timer paused — hit resume when back"
      : "Watching you work...";
    document.getElementById("pause-btn").textContent = state.isPaused ? "▶ Resume" : "⏸ Pause";
  } else {
    bar.classList.remove("active");
    label.textContent = "FOCUS OFF";
    sub.textContent   = "Click to start watching";
  }
}

function renderActivePanel() {
  const panel = document.getElementById("active-panel");
  if (state.currentTaskId && state.focusMode) {
    const task = state.tasks.find(t => t.id === state.currentTaskId);
    panel.style.display = "block";
    document.getElementById("active-task-name").textContent = task ? task.name : "Task";
    updateTimer();
  } else {
    panel.style.display = "none";
  }
}

function updateTimer() {
  if (!state.taskStartTime || !state.currentTaskId) return;
  const task = state.tasks.find(t => t.id === state.currentTaskId);
  if (!task) return;

  const totalPausedMs   = state.totalPausedMs || 0;
  const currentPauseMs  = (state.isPaused && state.pausedAt)
    ? Date.now() - state.pausedAt
    : 0;
  const effectivePaused = totalPausedMs + currentPauseMs;
  const elapsed         = Math.floor((Date.now() - state.taskStartTime - effectivePaused) / 1000);
  const remaining       = Math.max(0, task.minutes * 60 - elapsed);

  const m = Math.floor(remaining / 60).toString().padStart(2, "0");
  const s = (remaining % 60).toString().padStart(2, "0");

  const timerEl = document.getElementById("active-timer");
  timerEl.textContent = `${m}:${s}`;
  timerEl.className   = "active-timer";
  if (remaining <= 60)        timerEl.classList.add("danger");
  else if (remaining <= 300)  timerEl.classList.add("warning");
}

function renderTaskList() {
  const list  = document.getElementById("task-list");
  const empty = document.getElementById("empty-state");
  const tasks = state.tasks || [];

  const pending = tasks.filter(t => t.status === "pending");
  const rest    = tasks.filter(t => t.status !== "pending");
  const sorted  = [...pending, ...rest];

  if (sorted.length === 0) {
    empty.style.display = "flex";
    list.innerHTML      = "";
    list.appendChild(empty);
    return;
  }

  empty.style.display = "none";
  list.innerHTML      = sorted.map(taskHTML).join("");

  sorted.forEach(task => {
    const startBtn = document.getElementById(`start-${task.id}`);
    if (startBtn) startBtn.addEventListener("click", () => startTask(task.id));

    const doneBtn = document.getElementById(`quick-done-${task.id}`);
    if (doneBtn) doneBtn.addEventListener("click", () => initiateCompletion(task.id));
  });
}

function taskHTML(task) {
  const statusClass = {
    pending:   "status-pending",
    done:      "status-done",
    missed:    "status-missed",
    postponed: "status-postponed",
  }[task.status] || "status-pending";

  const isActive  = task.id === state.currentTaskId;
  const isPending = task.status === "pending";

  const actions = isPending
    ? `<button class="task-action-btn start-btn" id="start-${task.id}" title="Start">▶</button>
       <button class="task-action-btn" id="quick-done-${task.id}" title="Mark done">✓</button>`
    : "";

  return `
    <div class="task-item ${task.status} ${isActive ? "active-task" : ""}">
      <div class="task-status-dot ${statusClass}"></div>
      <div class="task-info">
        <div class="task-name">${escHtml(task.name)}</div>
        <div class="task-meta">${task.minutes}min · ${task.source || "telegram"} · ${task.status}</div>
      </div>
      <div class="task-actions">${actions}</div>
    </div>
  `;
}

function renderFooter() {
  chrome.storage.local.get(["lastSynced"], (data) => {
    const el = document.getElementById("footer-status");
    if (data.lastSynced) {
      const d = new Date(data.lastSynced);
      el.textContent = `synced ${d.getHours()}:${d.getMinutes().toString().padStart(2,"0")}`;
    } else {
      el.textContent = "not synced yet";
    }
  });
  document.getElementById("sync-dot").className = "sync-dot synced";
}

// ── ACTIONS ───────────────────────────────────────────────────────────────────

function startTask(taskId) {
  chrome.runtime.sendMessage({ type: "START_TASK", taskId }, () => {
    state.currentTaskId = taskId;
    state.taskStartTime = Date.now();
    state.totalPausedMs = 0;
    state.pausedAt      = null;
    state.focusMode     = true;
    state.isPaused      = false;
    hideCheckin();
    renderAll();
  });
}

function initiateCompletion(taskId) {
  document.getElementById("verify-panel").style.display   = "block";
  document.getElementById("verify-spinner").style.display = "flex";
  document.getElementById("verify-result").style.display  = "none";
  document.getElementById("active-panel").style.display   = "none";

  chrome.runtime.sendMessage({ type: "COMPLETE_TASK", taskId }, ({ verdict }) => {
    document.getElementById("verify-spinner").style.display = "none";
    document.getElementById("verify-result").style.display  = "block";
    document.getElementById("verify-icon").textContent      = verdict.approved ? "✅" : "⚠️";
    document.getElementById("verify-message").textContent   = verdict.message;

    const actionsEl = document.getElementById("verify-actions");
    actionsEl.style.display = "flex";

    if (verdict.approved) {
      // Approved — show confirm button
      actionsEl.innerHTML = `<button class="btn btn-approve" id="confirm-done-btn">Confirm Done →</button>`;
      document.getElementById("confirm-done-btn").addEventListener("click", () => confirmTaskDone(taskId));

    } else if (verdict.hardReject) {
      // Hard reject (time not met or task not found) — no override, just dismiss
      actionsEl.innerHTML = `<button class="btn btn-retry" id="dismiss-btn">Got it</button>`;
      document.getElementById("dismiss-btn").addEventListener("click", () => {
        document.getElementById("verify-panel").style.display = "none";
        renderActivePanel();
      });

    } else {
      // Soft reject (Gemini not convinced) — Try Again only, NO "mark done anyway"
      actionsEl.innerHTML = `<button class="btn btn-retry" id="retry-btn">↺ Try Again</button>`;
      document.getElementById("retry-btn").addEventListener("click", () => {
        document.getElementById("verify-panel").style.display = "none";
        renderActivePanel();
      });
    }
  });
}

function confirmTaskDone(taskId) {
  const task = state.tasks.find(t => t.id === taskId);
  if (task) task.status = "done";

  document.getElementById("verify-panel").style.display = "none";

  chrome.runtime.sendMessage({ type: "CONFIRM_DONE", taskId }, ({ tasks }) => {
    state.currentTaskId = null;
    state.taskStartTime = null;
    state.totalPausedMs = 0;
    state.pausedAt      = null;
    state.focusMode     = false;
    state.isPaused      = false;
    if (tasks) state.tasks = tasks;
    renderAll();
  });
}

// ── CHECKIN ───────────────────────────────────────────────────────────────────

function showCheckin(message, taskId) {
  document.getElementById("checkin-message").textContent = message;
  document.getElementById("checkin-reply").value         = "";
  document.getElementById("checkin-panel").style.display = "block";
  document.getElementById("checkin-reply").focus();
}

function hideCheckin() {
  document.getElementById("checkin-panel").style.display = "none";
}

// ── LISTENERS ─────────────────────────────────────────────────────────────────

function setupListeners() {
  document.getElementById("focus-bar").addEventListener("click", toggleFocus);

  document.getElementById("pause-btn").addEventListener("click", (e) => {
    e.stopPropagation();
    togglePause();
  });

  document.getElementById("done-btn").addEventListener("click", () => {
    if (state.currentTaskId) initiateCompletion(state.currentTaskId);
  });

  document.getElementById("add-btn").addEventListener("click", () => {
    document.getElementById("add-form").style.display = "block";
    document.getElementById("task-name-input").focus();
  });

  document.getElementById("cancel-add-btn").addEventListener("click", () => {
    document.getElementById("add-form").style.display = "none";
  });

  document.getElementById("confirm-add-btn").addEventListener("click", addTask);

  document.getElementById("task-name-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") addTask();
  });

  document.getElementById("still-working-btn").addEventListener("click", () => {
    chrome.runtime.sendMessage({ type: "ACTIVITY_PING" });
    chrome.storage.local.set({ checkinPending: false });
    hideCheckin();
  });

  document.getElementById("took-break-btn").addEventListener("click", () => {
    chrome.runtime.sendMessage({ type: "ACTIVITY_PING" });
    chrome.storage.local.set({ checkinPending: false });
    hideCheckin();
  });

  document.getElementById("sync-btn").addEventListener("click", syncNow);
  document.getElementById("refresh-btn").addEventListener("click", syncNow);
}

function toggleFocus() {
  const newVal    = !state.focusMode;
  state.focusMode = newVal;
  if (!newVal) {
    state.isPaused      = false;
    state.currentTaskId = null;
    state.totalPausedMs = 0;
    state.pausedAt      = null;
  }
  chrome.runtime.sendMessage({ type: "SET_FOCUS", value: newVal });
  renderAll();
}

function togglePause() {
  state.isPaused = !state.isPaused;
  if (state.isPaused) {
    state.pausedAt = Date.now();
  } else {
    const extra     = state.pausedAt ? Date.now() - state.pausedAt : 0;
    state.totalPausedMs = (state.totalPausedMs || 0) + extra;
    state.pausedAt  = null;
  }
  chrome.runtime.sendMessage({ type: "SET_PAUSE", value: state.isPaused });
  renderFocusBar();
}

async function addTask() {
  const name = document.getElementById("task-name-input").value.trim();
  const mins = parseInt(document.getElementById("task-mins-input").value);
  if (!name || !mins || mins < 1) return;

  document.getElementById("add-form").style.display       = "none";
  document.getElementById("task-name-input").value        = "";
  document.getElementById("sync-dot").className           = "sync-dot syncing";

  chrome.runtime.sendMessage({ type: "ADD_TASK", name, minutes: mins }, () => {
    chrome.runtime.sendMessage({ type: "SYNC_TASKS" }, ({ tasks }) => {
      state.tasks = tasks || state.tasks;
      document.getElementById("sync-dot").className = "sync-dot synced";
      renderTaskList();
      renderFooter();
    });
  });
}

function syncNow() {
  document.getElementById("sync-dot").className = "sync-dot syncing";
  chrome.runtime.sendMessage({ type: "SYNC_TASKS" }, ({ tasks }) => {
    state.tasks = tasks || state.tasks;
    document.getElementById("sync-dot").className = "sync-dot synced";
    renderAll();
  });
}

function escHtml(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}