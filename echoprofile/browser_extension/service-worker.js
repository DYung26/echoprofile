const DEFAULT_SERVER = "http://127.0.0.1:8756";
const RECONNECT_ALARM = "echoprofile-reconnect";
let socket;
let reconnectDelay = 1000;

async function settings() {
  const values = await chrome.storage.local.get({ serverUrl: DEFAULT_SERVER, token: "" });
  return values;
}

function send(message) {
  if (!socket || socket.readyState !== WebSocket.OPEN) throw new Error("EchoProfile bridge is disconnected");
  socket.send(JSON.stringify(message));
}

async function connect() {
  if (socket && [WebSocket.CONNECTING, WebSocket.OPEN].includes(socket.readyState)) return;
  const { serverUrl, token } = await settings();
  if (!token) return;
  const wsUrl = serverUrl.replace(/^http/, "ws").replace(/\/$/, "") + "/extension/connect";
  console.log("EchoProfile connecting", wsUrl);
  const current = new WebSocket(wsUrl);
  socket = current;
  current.onopen = () => {
    console.log("EchoProfile WebSocket opened");
    reconnectDelay = 1000;
    current.send(JSON.stringify({ type: "authenticate", token, version: chrome.runtime.getManifest().version }));
  };
  current.onmessage = async event => {
    let message;
    try { message = JSON.parse(event.data); } catch { return; }
    if (message.type === "authenticated") return;
    if (message.type === "heartbeat") { send({ type: "heartbeat-ack" }); return; }
    if (message.type !== "command" || !message.id) return;
    try {
      const result = await execute(message.action, message.payload || {});
      send({ type: "result", id: message.id, ok: true, result });
    } catch (error) {
      send({ type: "result", id: message.id, ok: false, error: String(error?.message || error) });
    }
  };
  current.onclose = event => {
    console.warn("EchoProfile WebSocket closed", event.code, event.reason);
    if (socket === current) socket = undefined;
    chrome.alarms.create(RECONNECT_ALARM, { delayInMinutes: Math.max(reconnectDelay / 60000, 0.5) });
    reconnectDelay = Math.min(reconnectDelay * 2, 30000);
  };
  current.onerror = error => { console.error("EchoProfile WebSocket error", error); current.close(); };
}

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (!tab?.id) throw new Error("No active browser tab");
  return tab;
}

async function inPage(tabId, fn, args = []) {
  const [result] = await chrome.scripting.executeScript({ target: { tabId }, func: fn, args });
  return result?.result;
}

async function execute(action, payload) {
  switch (action) {
    case "status": {
      const tabs = await chrome.tabs.query({});
      return { connected: true, extension: chrome.runtime.getManifest().name, tabs: tabs.length };
    }
    case "tabs.list":
      return (await chrome.tabs.query({})).map(({ id, windowId, index, active, title, url, status }) => ({ id, windowId, index, active, title, url, status }));
    case "tabs.active": {
      const tab = await activeTab();
      return { id: tab.id, windowId: tab.windowId, title: tab.title, url: tab.url };
    }
    case "tabs.new": {
      const tab = await chrome.tabs.create({ url: payload.url || "about:blank", active: payload.active !== false });
      return { id: tab.id, url: tab.url };
    }
    case "tabs.close":
      await chrome.tabs.remove(Number(payload.tabId));
      return { closed: Number(payload.tabId) };
    case "tabs.activate": {
      const tabId = Number(payload.tabId);
      const tab = await chrome.tabs.get(tabId);
      await chrome.tabs.update(tabId, { active: true });
      await chrome.windows.update(tab.windowId, { focused: true });
      return { active: tabId };
    }
    case "navigate": {
      const tab = payload.tabId ? await chrome.tabs.get(Number(payload.tabId)) : await activeTab();
      const updated = await chrome.tabs.update(tab.id, { url: payload.url });
      return { tabId: updated.id, url: payload.url };
    }
    case "page.title": {
      const tab = payload.tabId ? await chrome.tabs.get(Number(payload.tabId)) : await activeTab();
      return { title: tab.title, url: tab.url };
    }
    case "page.text": {
      const tab = payload.tabId ? await chrome.tabs.get(Number(payload.tabId)) : await activeTab();
      return await inPage(tab.id, () => document.body?.innerText || "");
    }
    case "page.html": {
      const tab = payload.tabId ? await chrome.tabs.get(Number(payload.tabId)) : await activeTab();
      return await inPage(tab.id, () => document.documentElement?.outerHTML || "");
    }
    case "page.click": {
      const tab = payload.tabId ? await chrome.tabs.get(Number(payload.tabId)) : await activeTab();
      return await inPage(tab.id, selector => {
        const element = document.querySelector(selector);
        if (!element) throw new Error(`Element not found: ${selector}`);
        element.click();
        return { clicked: selector };
      }, [payload.selector]);
    }
    case "page.fill": {
      const tab = payload.tabId ? await chrome.tabs.get(Number(payload.tabId)) : await activeTab();
      return await inPage(tab.id, ({ selector, value }) => {
        const element = document.querySelector(selector);
        if (!element) throw new Error(`Element not found: ${selector}`);
        element.focus();
        if (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement) {
          const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(element), "value")?.set;
          setter?.call(element, value);
          element.dispatchEvent(new Event("input", { bubbles: true }));
          element.dispatchEvent(new Event("change", { bubbles: true }));
        } else if (element.isContentEditable) {
          element.textContent = value;
          element.dispatchEvent(new InputEvent("input", { bubbles: true, data: value, inputType: "insertText" }));
        } else throw new Error("Target is not an editable field");
        return { filled: selector };
      }, [{ selector: payload.selector, value: String(payload.value ?? "") }]);
    }
    case "page.press": {
      const tab = payload.tabId ? await chrome.tabs.get(Number(payload.tabId)) : await activeTab();
      const key = String(payload.key || "Enter");
      if (payload.selector) {
        await inPage(tab.id, selector => {
          const element = document.querySelector(selector);
          if (!element) throw new Error(`Element not found: ${selector}`);
          element.focus();
        }, [payload.selector]);
      }
      await chrome.debugger.attach({ tabId: tab.id }, "1.3");
      try {
        const keyCodes = { Enter: 13, Tab: 9, Backspace: 8, Escape: 27, ArrowUp: 38, ArrowDown: 40, ArrowLeft: 37, ArrowRight: 39, Delete: 46, Space: 32 };
        const virtualKeyCode = keyCodes[key] || (key.length === 1 ? key.toUpperCase().charCodeAt(0) : 0);
        const code = payload.code || (key.length === 1 ? `Key${key.toUpperCase()}` : key);
        const keyParams = { key, code, windowsVirtualKeyCode: virtualKeyCode, nativeVirtualKeyCode: virtualKeyCode };
        await chrome.debugger.sendCommand({ tabId: tab.id }, "Input.dispatchKeyEvent", { ...keyParams, type: "keyDown" });
        if (key.length === 1) await chrome.debugger.sendCommand({ tabId: tab.id }, "Input.dispatchKeyEvent", { ...keyParams, type: "char", text: key });
        await chrome.debugger.sendCommand({ tabId: tab.id }, "Input.dispatchKeyEvent", { ...keyParams, type: "keyUp" });
      } finally {
        await chrome.debugger.detach({ tabId: tab.id }).catch(() => {});
      }
      if (key === "Enter") {
        await inPage(tab.id, selector => {
          const element = selector ? document.querySelector(selector) : document.activeElement;
          if (element?.form) element.form.requestSubmit();
          else if (element instanceof HTMLButtonElement || element instanceof HTMLAnchorElement) element.click();
        }, [payload.selector]);
      }
      return { pressed: String(payload.key || "Enter"), tabId: tab.id };
    }
    case "page.screenshot": {
      const tab = payload.tabId ? await chrome.tabs.get(Number(payload.tabId)) : await activeTab();
      await chrome.debugger.attach({ tabId: tab.id }, "1.3");
      try {
        const shot = await chrome.debugger.sendCommand({ tabId: tab.id }, "Page.captureScreenshot", {
          format: payload.format || "png",
          captureBeyondViewport: payload.fullPage === true
        });
        return { dataUrl: `data:image/${payload.format || "png"};base64,${shot.data}` };
      } finally {
        await chrome.debugger.detach({ tabId: tab.id }).catch(() => {});
      }
    }
    case "page.scroll": {
      const tab = payload.tabId ? await chrome.tabs.get(Number(payload.tabId)) : await activeTab();
      return await inPage(tab.id, ({ x, y }) => { window.scrollBy(x, y); return { x: window.scrollX, y: window.scrollY }; }, [{ x: Number(payload.x || 0), y: Number(payload.y || 0) }]);
    }
    default:
      throw new Error(`Unsupported EchoProfile extension action: ${action}`);
  }
}

chrome.alarms.onAlarm.addListener(alarm => { if (alarm.name === RECONNECT_ALARM) connect(); });
chrome.runtime.onInstalled.addListener(() => connect());
chrome.action.onClicked.addListener(() => chrome.runtime.openOptionsPage());
chrome.runtime.onStartup.addListener(() => connect());
chrome.runtime.onMessage.addListener((message, _sender, reply) => {
  if (message?.type === "echoprofile.reconnect") {
    const previous = socket;
    socket = undefined;
    if (previous && [WebSocket.CONNECTING, WebSocket.OPEN].includes(previous.readyState)) previous.close(1000, "Settings changed");
    connect().then(() => reply({ ok: true }));
    return true;
  }
});
connect();
