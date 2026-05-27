import json
import os
import urllib.error
import urllib.parse
import urllib.request

import streamlit as st


DEFAULT_MODEL = "gemini-2.5-flash-lite"

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


def get_setting(name, default=""):
    try:
        value = st.secrets.get(name)
        if value:
            return str(value)
    except Exception:
        pass
    return os.environ.get(name, default)


def normalize_messages(messages):
    normalized = []
    for message in messages[-12:]:
        normalized.append(
            {
                "role": "model" if message["role"] == "assistant" else "user",
                "parts": [{"text": message["content"][:8000]}],
            }
        )
    return normalized


def build_gemini_body(role_key, messages):
    role = ROLES.get(role_key, ROLES["guided_tutor"])
    contents = normalize_messages(messages)
    if not contents:
        contents = [{"role": "user", "parts": [{"text": "請開始教學。"}]}]

    return {
        "systemInstruction": {
            "parts": [
                {
                    "text": (
                        role["instruction"]
                        + "\n\n你現在的教學角色是上方設定。請保持角色風格，回答要具體、可操作，並以繁體中文輸出。"
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


def stream_gemini(role_key, messages):
    api_key = get_setting("GEMINI_API_KEY")
    model = get_setting("GEMINI_MODEL", DEFAULT_MODEL)
    if not api_key:
        yield "尚未設定 GEMINI_API_KEY。請到 Streamlit Cloud 的 App settings -> Secrets 加入 GEMINI_API_KEY。"
        return

    endpoint = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        + urllib.parse.quote(model, safe="")
        + ":streamGenerateContent?alt=sse&key="
        + urllib.parse.quote(api_key, safe="")
    )
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(build_gemini_body(role_key, messages)).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
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
                    yield text
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:500]
        yield f"Gemini API 回應失敗：HTTP {error.code}\n\n{detail}"
    except Exception as error:
        yield f"伺服器處理聊天時發生錯誤：{error}"


def main():
    st.set_page_config(page_title="多角色教學輔助系統", page_icon="教", layout="wide")

    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "role" not in st.session_state:
        st.session_state.role = "strict_teacher"

    with st.sidebar:
        st.title("多角色教學輔助系統")
        st.caption("Gemini 即時教學助理")
        role_keys = list(ROLES.keys())
        st.session_state.role = st.radio(
            "教學角色",
            role_keys,
            format_func=lambda key: ROLES[key]["label"],
            index=role_keys.index(st.session_state.role),
        )
        if st.button("清除對話", use_container_width=True):
            st.session_state.messages = []
            st.rerun()

        api_ready = bool(get_setting("GEMINI_API_KEY"))
        st.status("Gemini API 已設定" if api_ready else "尚未設定 GEMINI_API_KEY", state="complete" if api_ready else "error")

    st.header(ROLES[st.session_state.role]["label"])

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    prompt = st.chat_input("輸入你的問題...")
    if not prompt:
        return

    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        placeholder = st.empty()
        answer = ""
        for chunk in stream_gemini(st.session_state.role, st.session_state.messages):
            answer += chunk
            placeholder.markdown(answer)

    st.session_state.messages.append({"role": "assistant", "content": answer})


if __name__ == "__main__":
    main()
