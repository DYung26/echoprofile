const status = document.querySelector("#status");
document.querySelector("#connect").addEventListener("click", async () => {
  status.textContent = "Connecting…";
  try {
    const result = await chrome.runtime.sendMessage({ type: "echoprofile.reconnect" });
    status.textContent = result?.ok ? "Pairing requested. Check EchoProfile server status." : "Could not reconnect.";
  } catch (error) {
    status.textContent = String(error?.message || error);
  }
});
