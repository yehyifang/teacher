const roles = {
  strict_teacher: "老師（嚴格）",
  guided_tutor: "家教老師（引導）",
  relaxed_counselor: "課後輔導員（輕鬆）"
};

const messagesEl = document.querySelector("#messages");
const form = document.querySelector("#chatForm");
const input = document.querySelector("#promptInput");
const sendButton = document.querySelector("#sendButton");
const clearButton = document.querySelector("#clearButton");
const activeRoleName = document.querySelector("#activeRoleName");
const statusDot = document.querySelector("#statusDot");
const statusText = document.querySelector("#statusText");
const roleButtons = Array.from(document.querySelectorAll(".role-card"));

let selectedRole = "strict_teacher";
let messages = [];
let isStreaming = false;

function scrollToBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function addMessage(role, content, options = {}) {
  const wrapper = document.createElement("article");
  wrapper.className = `message ${role}${options.error ? " error" : ""}`;

  const meta = document.createElement("div");
  meta.className = "message-meta";
  meta.textContent = role === "user" ? "你" : roles[selectedRole];

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = content;

  wrapper.append(meta, bubble);
  messagesEl.append(wrapper);
  scrollToBottom();
  return bubble;
}

function setStreaming(value) {
  isStreaming = value;
  sendButton.disabled = value;
  sendButton.textContent = value ? "回應中" : "送出";
  input.disabled = value;
}

function updateRole(role) {
  selectedRole = role;
  activeRoleName.textContent = roles[role];
  roleButtons.forEach(button => {
    const active = button.dataset.role === role;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-checked", String(active));
  });
}

function parseSseEvents(buffer) {
  const blocks = buffer.split("\n\n");
  const rest = blocks.pop() || "";
  const events = blocks.map(block => {
    let event = "message";
    const data = [];

    block.split("\n").forEach(line => {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      if (line.startsWith("data:")) data.push(line.slice(5).trim());
    });

    return { event, data: data.join("\n") };
  });

  return { events, rest };
}

async function sendMessage(prompt) {
  messages.push({ role: "user", content: prompt });
  addMessage("user", prompt);

  const assistantBubble = addMessage("assistant", "");
  let assistantText = "";
  setStreaming(true);

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role: selectedRole, messages })
    });

    if (!response.ok || !response.body) throw new Error(`伺服器回應失敗：HTTP ${response.status}`);

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const parsed = parseSseEvents(buffer);
      buffer = parsed.rest;

      for (const item of parsed.events) {
        if (!item.data) continue;
        const payload = JSON.parse(item.data);

        if (item.event === "token") {
          assistantText += payload.text || "";
          assistantBubble.textContent = assistantText;
          scrollToBottom();
        }

        if (item.event === "error") {
          throw new Error(payload.detail ? `${payload.message}\n${payload.detail}` : payload.message);
        }
      }
    }

    messages.push({ role: "assistant", content: assistantText || "（沒有收到文字回應）" });
    assistantBubble.textContent = assistantText || "（沒有收到文字回應）";
  } catch (error) {
    assistantBubble.parentElement.classList.add("error");
    assistantBubble.textContent = error.message || "聊天時發生錯誤。";
  } finally {
    setStreaming(false);
    input.focus();
  }
}

roleButtons.forEach(button => {
  button.addEventListener("click", () => {
    if (!isStreaming) updateRole(button.dataset.role);
  });
});

form.addEventListener("submit", event => {
  event.preventDefault();
  const prompt = input.value.trim();
  if (!prompt || isStreaming) return;
  input.value = "";
  sendMessage(prompt);
});

input.addEventListener("keydown", event => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

clearButton.addEventListener("click", () => {
  if (isStreaming) return;
  messages = [];
  messagesEl.textContent = "";
  addMessage("assistant", "你好，我可以用不同教學風格陪你學習。選一個角色後，直接輸入題目或你卡住的地方。");
});

async function checkHealth() {
  try {
    const response = await fetch("/api/health");
    const health = await response.json();
    statusDot.className = `status-dot ${health.geminiKeyConfigured ? "is-ok" : "is-error"}`;
    statusText.textContent = health.geminiKeyConfigured ? `已連線：${health.model}` : "缺少 GEMINI_API_KEY";
  } catch {
    statusDot.className = "status-dot is-error";
    statusText.textContent = "服務未連線";
  }
}

updateRole(selectedRole);
addMessage("assistant", "你好，我是嚴格老師。請把題目、你的解法或不懂的地方貼上來，我會直接指出問題並帶你修正。");
checkHealth();
