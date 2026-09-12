const endpoint = document.getElementById("endpoint");
const code = document.getElementById("code");
const result = document.getElementById("result");

async function load() {
  const cfg = await chrome.storage.local.get({endpoint: "http://127.0.0.1:47123"});
  endpoint.value = cfg.endpoint;
}

async function setEndpoint() {
  const value = endpoint.value.trim().replace(/\/$/, "") || "http://127.0.0.1:47123";
  await chrome.storage.local.set({endpoint: value});
  endpoint.value = value;
}

document.getElementById("pair").onclick = async () => {
  try {
    await setEndpoint();
    result.className = "muted";
    result.textContent = "Pairing…";
    const response = await chrome.runtime.sendMessage({type: "NEXTPLAN_PAIR", code: code.value.trim()});
    if (response?.status !== "paired") throw new Error(response?.error || "Pairing failed");
    result.className = "muted ok";
    result.textContent = "Paired successfully.";
    code.value = "";
  } catch (err) {
    result.className = "muted bad";
    result.textContent = err.message;
  }
};

document.getElementById("test").onclick = async () => {
  try {
    await setEndpoint();
    const response = await chrome.runtime.sendMessage({type: "NEXTPLAN_TEST"});
    if (response?.status !== "ok") throw new Error(response?.error || "Local Core unavailable");
    result.className = "muted ok";
    result.textContent = `Local Core healthy · ${response.runtime || "local"}`;
  } catch (err) {
    result.className = "muted bad";
    result.textContent = err.message;
  }
};

load();
