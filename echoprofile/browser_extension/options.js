const server = document.querySelector("#server");
const token = document.querySelector("#token");
const status = document.querySelector("#status");
(async () => {
  const values = await chrome.storage.local.get({ serverUrl: "http://127.0.0.1:8756", token: "" });
  server.value = values.serverUrl;
  token.value = values.token;
})();
document.querySelector("#save").addEventListener("click", async () => {
  await chrome.storage.local.set({ serverUrl: server.value.replace(/\/$/, ""), token: token.value.trim() });
  await chrome.runtime.sendMessage({ type: "echoprofile.reconnect" });
  status.textContent = "Saved. Check EchoProfile extension status.";
});
