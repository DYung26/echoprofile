const statusPill = document.querySelector("#status-pill");
const statusLabel = document.querySelector("#status-label");
const statusDescription = document.querySelector("#status-description");
const connectButton = document.querySelector("#connect");
const SERVER = "http://127.0.0.1:8756";

function renderStatus(state, description) {
  statusPill.className = `status-pill ${state}`;
  statusLabel.textContent = state === "connected" ? "Connected" : state === "disconnected" ? "Disconnected" : "Checking";
  statusDescription.textContent = description;
}

async function refreshStatus() {
  try {
    const response = await fetch(`${SERVER}/extension/status`, { cache: "no-store", credentials: "omit" });
    if (!response.ok) throw new Error(`Service returned ${response.status}`);
    const { connected } = await response.json();
    renderStatus(connected ? "connected" : "disconnected", connected
      ? "This browser is paired and ready to receive browser-control actions."
      : "The local service is reachable, but this browser has not connected yet.");
    return connected;
  } catch {
    renderStatus("disconnected", "EchoProfile is not reachable at 127.0.0.1:8756. Start its service, then reconnect.");
    return false;
  }
}

connectButton.addEventListener("click", async () => {
  connectButton.disabled = true;
  connectButton.innerHTML = '<span class="button-icon" aria-hidden="true">↻</span> Connecting…';
  renderStatus("checking", "Requesting a fresh connection to the local EchoProfile service…");
  try {
    const result = await chrome.runtime.sendMessage({ type: "echoprofile.reconnect" });
    if (!result?.ok) throw new Error("The extension could not start its connection.");
    for (let attempt = 0; attempt < 8; attempt += 1) {
      await new Promise(resolve => setTimeout(resolve, 750));
      if (await refreshStatus()) return;
    }
    renderStatus("disconnected", "Reconnect was requested, but the server has not confirmed the browser connection yet. Check that the EchoProfile service is running.");
  } catch (error) {
    renderStatus("disconnected", String(error?.message || error));
  } finally {
    connectButton.disabled = false;
    connectButton.innerHTML = '<span class="button-icon" aria-hidden="true">↻</span> Reconnect';
  }
});

refreshStatus();
setInterval(refreshStatus, 5000);
