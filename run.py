import json
import mimetypes
import os
import posixpath
import urllib.error
import urllib.parse
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PUBLIC_DIR = ROOT / "public"


def load_env_file() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().lstrip("\ufeff")
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


load_env_file()

PORT = int(os.environ.get("PORT", "3000"))
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")

ROLES = {
    "strict_teacher": {
        "label": "老師（嚴格）",
        "temperature": 0.45,
        "instruction": (
            "你是嚴格但公正的老師。請用繁體中文回答。要求學生精準、條理清楚，"
            "會指出錯誤與盲點，語氣專業直接。回答時先給結論，再給重點步驟，"
            "必要時出一題練習檢查理解。"
        ),
    },
    "guided_tutor": {
        "label": "家教老師（引導）",
        "temperature": 0.7,
        "instruction": (
            "你是擅長引導的家教老師。請用繁體中文回答。不要急著只給答案，"
            "要用提示、問題與分段推理帶學生理解。語氣耐心，鼓勵學生自己走到答案。"
        ),
    },
    "relaxed_counselor": {
        "label": "課後輔導員（輕鬆）",
        "temperature": 0.85,
        "instruction": (
            "你是輕鬆親切的課後輔導員。請用繁體中文回答。用生活化比喻降低壓力，"
            "保持正確性，回答清楚但不要太嚴肅。可以給簡短整理與下一步建議。"
        ),
    },
}


def normalize_messages(messages):
    if not isinstance(messages, list):
        return []
    normalized = []
    for message in messages[-12:]:
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            continue
        normalized.append(
            {
                "role": "model" if message.get("role") == "assistant" else "user",
                "parts": [{"text": message["content"][:8000]}],
            }
        )
    return normalized


def build_gemini_body(role_key, messages):
    role = ROLES.get(role_key, ROLES["guided_tutor"])
    contents = normalize_messages(messages) or [
        {"role": "user", "parts": [{"text": "請介紹你可以如何協助我學習。"}]}
    ]
    return {
        "systemInstruction": {
            "parts": [
                {
                    "text": (
                        role["instruction"]
                        + "\n\n你正在多角色教學輔助系統中回答學生。請避免編造資料；"
                        + "不確定時明確說明，並提出可驗證的學習方向。"
                    )
                }
            ]
        },
        "contents": contents,
        "generationConfig": {
            "temperature": role["temperature"],
            "topP": 0.9,
            "maxOutputTokens": 2048,
        },
    }


def extract_text_from_gemini(payload):
    chunks = []
    for candidate in payload.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            text = part.get("text")
            if text:
                chunks.append(text)
    return "".join(chunks)


class TeachingHandler(SimpleHTTPRequestHandler):
    server_version = "TeachingAssistant/1.0"

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except Exception as error:
            try:
                with (ROOT / "server.error.log").open("a", encoding="utf-8") as log_file:
                    log_file.write(f"{type(error).__name__}: {error}\n")
            except Exception:
                pass
            raise

    def log_message(self, format, *args):
        try:
            with (ROOT / "server.access.log").open("a", encoding="utf-8") as log_file:
                log_file.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), format % args))
        except Exception:
            pass

    def translate_path(self, path):
        path = urllib.parse.urlparse(path).path
        path = posixpath.normpath(urllib.parse.unquote(path))
        parts = [part for part in path.split("/") if part and part not in (os.curdir, os.pardir)]
        target = PUBLIC_DIR
        for part in parts:
            target = target / part
        if target.is_dir():
            target = target / "index.html"
        return str(target)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_sse(self, event, payload):
        message = f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
        self.wfile.write(message.encode("utf-8"))
        self.wfile.flush()

    def serve_public_file(self):
        parsed_path = urllib.parse.urlparse(self.path).path
        normalized_path = posixpath.normpath(urllib.parse.unquote(parsed_path))
        parts = [
            part
            for part in normalized_path.split("/")
            if part and part not in (os.curdir, os.pardir)
        ]

        target = PUBLIC_DIR
        for part in parts:
            target = target / part

        if target.is_dir():
            target = target / "index.html"
        if not target.exists() or not target.is_file():
            target = PUBLIC_DIR / "index.html"

        try:
            content = target.read_bytes()
        except OSError:
            self.send_json(404, {"error": "File not found", "publicDir": str(PUBLIC_DIR)})
            return

        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if target.suffix in (".html", ".css", ".js", ".json"):
            content_type += "; charset=utf-8"

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(content)

    def do_GET(self):
        if self.path == "/api/health":
            self.send_json(
                200,
                {
                    "ok": True,
                    "app": "多角色教學輔助系統",
                    "model": GEMINI_MODEL,
                    "geminiKeyConfigured": bool(GEMINI_API_KEY),
                },
            )
            return
        if self.path.startswith("/api/"):
            self.send_json(404, {"error": "API not found"})
            return
        self.serve_public_file()

    def do_POST(self):
        if self.path != "/api/chat":
            self.send_json(404, {"error": "Not found"})
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        try:
            if not GEMINI_API_KEY:
                self.send_sse(
                    "error",
                    {"message": "尚未設定 GEMINI_API_KEY。請建立 .env 或在雲端環境變數中設定。"},
                )
                return

            length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(length).decode("utf-8") if length else "{}"
            payload = json.loads(raw_body)
            role_key = payload.get("role") if isinstance(payload.get("role"), str) else "guided_tutor"
            gemini_body = build_gemini_body(role_key, payload.get("messages"))
            endpoint = (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                + urllib.parse.quote(GEMINI_MODEL, safe="")
                + ":streamGenerateContent?alt=sse&key="
                + urllib.parse.quote(GEMINI_API_KEY, safe="")
            )
            request = urllib.request.Request(
                endpoint,
                data=json.dumps(gemini_body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(request, timeout=120) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    text = extract_text_from_gemini(json.loads(data))
                    if text:
                        self.send_sse("token", {"text": text})

            self.send_sse("done", {"ok": True})
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:500]
            quota_hint = (
                "這是 Gemini 專案配額或帳務層級限制，不是前端 SSE 錯誤。"
                "請到 AI Studio 檢查該專案的 rate limit，或在 .env 換用有配額的模型/API key。"
                if error.code == 429
                else ""
            )
            self.send_sse(
                "error",
                {
                    "message": f"Gemini API 回應失敗：HTTP {error.code}",
                    "detail": f"{quota_hint}\n{detail}".strip(),
                },
            )
        except Exception as error:
            self.send_sse("error", {"message": str(error) or "伺服器處理聊天時發生錯誤。"})


def is_running_in_streamlit():
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        return get_script_run_ctx() is not None
    except Exception:
        return False


def run_http_server():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), TeachingHandler)
    print(f"多角色教學輔助系統 running at http://localhost:{PORT}")
    print(f"Gemini model: {GEMINI_MODEL}")
    if not GEMINI_API_KEY:
        print("提醒：尚未設定 GEMINI_API_KEY，聊天 API 會回傳設定提示。")
    server.serve_forever()


if __name__ == "__main__":
    if is_running_in_streamlit():
        from streamlit_app import main as streamlit_main

        streamlit_main()
    else:
        run_http_server()
