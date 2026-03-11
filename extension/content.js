// ============================================================================
// TASKMASTER — Content Script
// Tracks mouse/keyboard activity and pings background worker
// ============================================================================

let pingThrottle = null;

function sendActivityPing() {
  if (pingThrottle) return;
  pingThrottle = setTimeout(() => { pingThrottle = null; }, 10000); // max 1 ping per 10s
  chrome.runtime.sendMessage({ type: "ACTIVITY_PING" }).catch(() => {});
}

document.addEventListener("mousemove",  sendActivityPing, { passive: true });
document.addEventListener("keydown",    sendActivityPing, { passive: true });
document.addEventListener("click",      sendActivityPing, { passive: true });
document.addEventListener("scroll",     sendActivityPing, { passive: true });
document.addEventListener("touchstart", sendActivityPing, { passive: true });