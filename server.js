const http = require("http");
const fs = require("fs");
const path = require("path");
const { URL } = require("url");

loadEnvFile(path.join(__dirname, ".env"));

const PORT = Number(process.env.PORT || 3000);
const GEMINI_API_KEY = process.env.GEMINI_API_KEY || "";
const GEMINI_MODEL = process.env.GEMINI_MODEL || "gemini-2.5-flash-lite";
const PUBLIC_DIR = path.join(__dirname, "public");

const roles = {
  strict_teacher: {
    label: "老師（嚴格）",
    instruction:
      "你是嚴格但公正的老師。請用繁體中文回答。要求學生精準、條理清楚，會指出錯誤與盲點，語氣專業直接。回答時先給結論，再給重點步驟，必要時出一題練習檢查理解。"
  },
  guided_tutor: {
    label: "家教老師（引導）",
    instruction:
      "你是擅長引導的家教老師。請用繁體中文回答。不要急著只給答案，要用提示、問題與分段推理帶學生理解。語氣耐心，鼓勵學生自己走到答案。"
  },
  relaxed_counselor: {
    label: "課後輔導員（輕鬆）",
    instruction:
      "你是輕鬆親切的課後輔導員。請用繁體中文回答。用生活化比喻降低壓力，保持正確性，回答清楚但不要太嚴肅。可以給簡短整理與下一步建議。"
  }
};

function loadEnvFile(envPath) {
  if (!fs.existsSync(envPath)) return;
  const lines = fs.readFileSync(envPath, "utf8").split(/\r?\n/);
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const separatorIndex = trimmed.indexOf("=");
    if (separatorIndex === -1) continue;
    const key = trimmed.slice(0, separatorIndex).trim().replace(/^\uFEFF/, "");
    const value = trimmed.slice(separatorIndex + 1).trim().replace(/^["']|["']$/g, "");
    if (key && process.env[key] === undefined) process.env[key] = value;
  }
}

const mimeTypes = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".ico": "image/x-icon"
};

function sendJson(res, status, payload) {
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store"
  });
  res.end(JSON.stringify(payload));
}

function sendSse(res, event, data) {
  res.write(`event: ${event}\n`);
  res.write(`data: ${JSON.stringify(data)}\n\n`);
}

function readJson(req) {
  return new Promise((resolve, reject) => {
    let body = "";
    req.on("data", chunk => {
      body += chunk;
      if (body.length > 1024 * 1024) {
        reject(new Error("Request body is too large."));
        req.destroy();
      }
    });
    req.on("end", () => {
      try {
        resolve(body ? JSON.parse(body) : {});
      } catch {
        reject(new Error("Invalid JSON body."));
      }
    });
    req.on("error", reject);
  });
}

function normalizeMessages(messages) {
  if (!Array.isArray(messages)) return [];
  return messages
    .filter(message => message && typeof message.content === "string")
    .slice(-12)
    .map(message => ({
      role: message.role === "assistant" ? "model" : "user",
      parts: [{ text: message.content.slice(0, 8000) }]
    }));
}

function buildGeminiBody(roleKey, messages) {
  const role = roles[roleKey] || roles.guided_tutor;
  const normalized = normalizeMessages(messages);
  const contents = normalized.length
    ? normalized
    : [{ role: "user", parts: [{ text: "請介紹你可以如何協助我學習。" }] }];

  return {
    systemInstruction: {
      parts: [
        {
          text: `${role.instruction}\n\n你正在多角色教學輔助系統中回答學生。請避免編造資料；不確定時明確說明，並提出可驗證的學習方向。`
        }
      ]
    },
    contents,
    generationConfig: {
      temperature: roleKey === "strict_teacher" ? 0.45 : roleKey === "guided_tutor" ? 0.7 : 0.85,
      topP: 0.9,
      maxOutputTokens: 2048
    }
  };
}

function extractTextFromGemini(data) {
  const candidates = data && data.candidates;
  if (!Array.isArray(candidates)) return "";
  return candidates
    .flatMap(candidate => {
      const parts = candidate && candidate.content && candidate.content.parts;
      return Array.isArray(parts) ? parts.map(part => part.text || "") : [];
    })
    .join("");
}

async function handleChat(req, res) {
  res.writeHead(200, {
    "Content-Type": "text/event-stream; charset=utf-8",
    "Cache-Control": "no-cache, no-transform",
    Connection: "keep-alive",
    "X-Accel-Buffering": "no"
  });

  try {
    if (!GEMINI_API_KEY) {
      sendSse(res, "error", {
        message: "尚未設定 GEMINI_API_KEY。請建立 .env 或在雲端環境變數中設定。"
      });
      res.end();
      return;
    }

    const payload = await readJson(req);
    const roleKey = typeof payload.role === "string" ? payload.role : "guided_tutor";
    const geminiBody = buildGeminiBody(roleKey, payload.messages);
    const endpoint = `https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(
      GEMINI_MODEL
    )}:streamGenerateContent?alt=sse&key=${encodeURIComponent(GEMINI_API_KEY)}`;

    const geminiResponse = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(geminiBody)
    });

    if (!geminiResponse.ok || !geminiResponse.body) {
      const errorText = await geminiResponse.text().catch(() => "");
      const quotaHint =
        geminiResponse.status === 429
          ? "這是 Gemini 專案配額或帳務層級限制，不是前端 SSE 錯誤。請到 AI Studio 檢查該專案的 rate limit，或在 .env 換用有配額的模型/API key。"
          : "";
      sendSse(res, "error", {
        message: `Gemini API 回應失敗：HTTP ${geminiResponse.status}`,
        detail: `${quotaHint}\n${errorText.slice(0, 500)}`.trim()
      });
      res.end();
      return;
    }

    const decoder = new TextDecoder();
    let buffer = "";

    for await (const chunk of geminiResponse.body) {
      buffer += decoder.decode(chunk, { stream: true });
      const events = buffer.split("\n\n");
      buffer = events.pop() || "";

      for (const eventBlock of events) {
        const dataLines = eventBlock
          .split("\n")
          .filter(line => line.startsWith("data:"))
          .map(line => line.replace(/^data:\s?/, ""));

        for (const line of dataLines) {
          if (!line || line === "[DONE]") continue;
          try {
            const text = extractTextFromGemini(JSON.parse(line));
            if (text) sendSse(res, "token", { text });
          } catch {
            sendSse(res, "debug", { message: "略過無法解析的串流片段。" });
          }
        }
      }
    }

    sendSse(res, "done", { ok: true });
    res.end();
  } catch (error) {
    sendSse(res, "error", { message: error.message || "伺服器處理聊天時發生錯誤。" });
    res.end();
  }
}

function serveStatic(req, res) {
  const requestUrl = new URL(req.url, `http://${req.headers.host}`);
  const safePath = path
    .normalize(decodeURIComponent(requestUrl.pathname))
    .replace(/^(\.\.[/\\])+/, "");
  const filePath = path.join(PUBLIC_DIR, safePath === "/" ? "index.html" : safePath);

  if (!filePath.startsWith(PUBLIC_DIR)) {
    sendJson(res, 403, { error: "Forbidden" });
    return;
  }

  fs.stat(filePath, (statError, stat) => {
    const finalPath = !statError && stat.isDirectory() ? path.join(filePath, "index.html") : filePath;
    fs.readFile(finalPath, (readError, content) => {
      if (readError) {
        fs.readFile(path.join(PUBLIC_DIR, "index.html"), (fallbackError, fallbackContent) => {
          if (fallbackError) {
            sendJson(res, 404, { error: "Not found" });
            return;
          }
          res.writeHead(200, { "Content-Type": mimeTypes[".html"] });
          res.end(fallbackContent);
        });
        return;
      }

      const ext = path.extname(finalPath).toLowerCase();
      res.writeHead(200, {
        "Content-Type": mimeTypes[ext] || "application/octet-stream",
        "Cache-Control": ext === ".html" ? "no-store" : "public, max-age=3600"
      });
      res.end(content);
    });
  });
}

const server = http.createServer((req, res) => {
  if (req.method === "GET" && req.url === "/api/health") {
    sendJson(res, 200, {
      ok: true,
      app: "多角色教學輔助系統",
      model: GEMINI_MODEL,
      geminiKeyConfigured: Boolean(GEMINI_API_KEY)
    });
    return;
  }

  if (req.method === "POST" && req.url === "/api/chat") {
    handleChat(req, res);
    return;
  }

  if (req.method !== "GET" && req.method !== "HEAD") {
    sendJson(res, 405, { error: "Method not allowed" });
    return;
  }

  serveStatic(req, res);
});

server.listen(PORT, () => {
  console.log(`多角色教學輔助系統 running at http://localhost:${PORT}`);
  console.log(`Gemini model: ${GEMINI_MODEL}`);
  if (!GEMINI_API_KEY) console.log("提醒：尚未設定 GEMINI_API_KEY，聊天 API 會回傳設定提示。");
});
