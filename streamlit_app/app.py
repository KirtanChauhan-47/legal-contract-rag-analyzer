"""Minimal Streamlit frontend for the Legal Contract RAG Analyzer backend.

A thin client only: every action here is a plain HTTP call to an existing
FastAPI endpoint (see README.md / CLAUDE.md for the full API). No business
logic, no new AI calls, no database access lives here -- this file's only
job is to render responses and give clear feedback when a call fails
(backend down, wrong workflow order, Groq rate limit, etc.).
"""
import requests
import streamlit as st

DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"

st.set_page_config(page_title="Legal Contract RAG Analyzer", page_icon="📄", layout="wide")

if "backend_url" not in st.session_state:
    st.session_state.backend_url = DEFAULT_BACKEND_URL
if "selected_document_id" not in st.session_state:
    st.session_state.selected_document_id = None
if "last_action" not in st.session_state:
    st.session_state.last_action = None
if "ask_result" not in st.session_state:
    st.session_state.ask_result = None


# --- Thin API client -------------------------------------------------------


def _api_url(path: str) -> str:
    return st.session_state.backend_url.rstrip("/") + path


def _parse_error(response: requests.Response) -> tuple[str, str]:
    try:
        body = response.json()
        error = body.get("error", {})
        code = error.get("code", str(response.status_code))
        message = error.get("message", response.text or "Unknown error.")
    except ValueError:
        code = str(response.status_code)
        message = response.text or "Unknown error."
    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            message = f"{message} (retry after {retry_after}s)"
    return code, message


def _request(method: str, path: str, *, timeout: int = 60, **kwargs):
    """Returns (data, error_code, error_message). data is None on failure;
    error_code/error_message are None on success."""
    try:
        response = requests.request(method, _api_url(path), timeout=timeout, **kwargs)
    except requests.exceptions.ConnectionError:
        return None, "backend_unavailable", (
            f"Could not reach the backend at {st.session_state.backend_url}. "
            "Is `uvicorn app.main:app --reload` running?"
        )
    except requests.exceptions.Timeout:
        return None, "timeout", "The backend took too long to respond."

    if response.status_code < 400:
        return (response.json() if response.content else None), None, None
    code, message = _parse_error(response)
    return None, code, message


def api_get(path: str, **kwargs):
    return _request("GET", path, **kwargs)


def api_post(path: str, *, timeout: int = 60, **kwargs):
    return _request("POST", path, timeout=timeout, **kwargs)


def show_error(code: str | None, message: str | None, container=st) -> None:
    if code is None:
        return
    if code == "backend_unavailable":
        container.error(f"🔌 {message}")
    elif code == "conflict":
        container.warning(f"⚠️ Workflow order issue: {message}")
    elif code == "rate_limited":
        container.warning(f"⏳ Groq rate limit reached: {message}")
    elif code == "not_found":
        container.info(message)
    else:
        container.error(message)


# --- Sidebar: connection, upload, document selection, pipeline actions -----

st.sidebar.header("⚙️ Setup")
st.session_state.backend_url = st.sidebar.text_input("Backend URL", value=st.session_state.backend_url)

st.sidebar.divider()
st.sidebar.subheader("📤 Upload a contract")
uploaded_file = st.sidebar.file_uploader("PDF / DOCX / TXT", type=["pdf", "docx", "txt"])
if st.sidebar.button("Upload", disabled=uploaded_file is None, use_container_width=True):
    files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
    data, code, msg = api_post("/documents/upload", files=files, timeout=60)
    if data:
        st.session_state.selected_document_id = data["id"]
        st.sidebar.success(f"Uploaded as document #{data['id']} (status: {data['status']})")
    else:
        show_error(code, msg, container=st.sidebar)

st.sidebar.divider()
st.sidebar.subheader("📁 Existing documents")
docs_data, docs_code, docs_msg = api_get("/documents", params={"limit": 100})
if docs_data:
    labels = [f"#{d['id']} — {d['original_filename']} ({d['status']})" for d in docs_data]
    ids = [d["id"] for d in docs_data]
    default_index = ids.index(st.session_state.selected_document_id) if st.session_state.selected_document_id in ids else 0
    chosen_label = st.sidebar.selectbox("Select a document", labels, index=default_index)
    st.session_state.selected_document_id = ids[labels.index(chosen_label)]
elif docs_code:
    show_error(docs_code, docs_msg, container=st.sidebar)
else:
    st.sidebar.caption("No documents uploaded yet.")

document_id = st.session_state.selected_document_id

st.sidebar.divider()
st.sidebar.subheader("▶️ Pipeline actions")
if document_id is None:
    st.sidebar.caption("Upload or select a document to enable these.")

action_col1, action_col2 = st.sidebar.columns(2)
if action_col1.button("Process", disabled=document_id is None, use_container_width=True):
    data, code, msg = api_post(f"/documents/{document_id}/process", timeout=60)
    st.session_state.last_action = ("Process", data, code, msg)
if action_col2.button("Embed", disabled=document_id is None, use_container_width=True):
    data, code, msg = api_post(f"/documents/{document_id}/embed", timeout=180)
    st.session_state.last_action = ("Embed", data, code, msg)

action_col3, action_col4 = st.sidebar.columns(2)
if action_col3.button("Analyze Clauses", disabled=document_id is None, use_container_width=True):
    data, code, msg = api_post(f"/documents/{document_id}/analyze-clauses", timeout=300)
    st.session_state.last_action = ("Analyze Clauses", data, code, msg)
if action_col4.button("Summarize", disabled=document_id is None, use_container_width=True):
    data, code, msg = api_post(f"/documents/{document_id}/summarize", timeout=180)
    st.session_state.last_action = ("Summarize", data, code, msg)


# --- Main area: tabs --------------------------------------------------------

st.title("📄 Legal Contract RAG Analyzer")
st.caption("AI-assisted contract understanding — not legal advice.")

tab_overview, tab_ask, tab_clauses, tab_summary = st.tabs(
    ["Overview", "Ask Questions", "Clause Analysis", "Contract Summary"]
)

with tab_overview:
    st.subheader("Document Overview")
    if document_id is None:
        st.info("Upload or select a document from the sidebar to get started.")
    else:
        data, code, msg = api_get(f"/documents/{document_id}")
        if data:
            col1, col2, col3 = st.columns(3)
            col1.metric("Filename", data["original_filename"])
            col2.metric("Status", data["status"])
            col3.metric("Created", data["created_at"][:10])
            if data.get("contract_type"):
                st.write(f"**Contract type (gate-detected):** {data['contract_type']}")
            if data.get("rejection_reason"):
                st.warning(f"Rejected by the contract gate: {data['rejection_reason']}")
            if data.get("error_message"):
                st.error(f"Processing error: {data['error_message']}")
        else:
            show_error(code, msg)

        if st.session_state.last_action is not None:
            action_name, action_data, action_code, action_msg = st.session_state.last_action
            st.divider()
            st.caption(f"Last sidebar action: **{action_name}**")
            if action_data is not None:
                st.success(f"{action_name} succeeded.")
            else:
                show_error(action_code, action_msg)

with tab_ask:
    st.subheader("Ask a grounded question")
    if document_id is None:
        st.info("Select a document first.")
    else:
        question = st.text_input("Your question", key="question_input")
        if st.button("Ask", disabled=not question.strip()):
            data, code, msg = api_post(f"/documents/{document_id}/ask", json={"question": question}, timeout=60)
            st.session_state.ask_result = (data, code, msg)

        if st.session_state.ask_result is not None:
            data, code, msg = st.session_state.ask_result
            if data:
                st.markdown(f"**Answer:** {data['answer']}")
                if data["citations"]:
                    st.markdown("**Verified citations:**")
                    for citation in data["citations"]:
                        st.markdown(f"> chunk `{citation['chunk_id']}`: *\"{citation['quote']}\"*")
                else:
                    st.caption("No verified citations were returned for this answer.")
            else:
                show_error(code, msg)

with tab_clauses:
    st.subheader("Clause Analysis")
    if document_id is None:
        st.info("Select a document first.")
    else:
        data, code, msg = api_get(f"/documents/{document_id}/clauses")
        if data is not None:
            if not data:
                st.info("No clause analysis yet — click 'Analyze Clauses' in the sidebar.")
            for clause in data:
                present_label = "✅ Present" if clause["present"] else "▫️ Absent"
                title = f"{clause['clause_type'].replace('_', ' ').title()} — {present_label} (risk: {clause['risk_level']})"
                with st.expander(title):
                    if clause["summary"]:
                        st.write(clause["summary"])
                    if clause["risk_explanation"]:
                        st.caption(clause["risk_explanation"])
                    if clause["citations"]:
                        st.markdown("**Citations:**")
                        for citation in clause["citations"]:
                            st.markdown(f"> chunk `{citation['chunk_id']}`: *\"{citation['quote']}\"*")
        else:
            show_error(code, msg)

with tab_summary:
    st.subheader("Contract Summary")
    if document_id is None:
        st.info("Select a document first.")
    else:
        data, code, msg = api_get(f"/documents/{document_id}/summary")
        if data:
            st.write(f"**Contract type:** {data['contract_type']}")

            st.write("**Parties:**")
            if data["parties"]:
                for party in data["parties"]:
                    role = f" ({party['role']})" if party.get("role") else ""
                    st.write(f"- {party['name']}{role}")
            else:
                st.caption("No parties extracted.")

            date_col1, date_col2 = st.columns(2)
            date_col1.write(f"**Effective date:** {data['effective_date'] or 'Not found'}")
            date_col2.write(f"**Expiration date:** {data['expiration_date'] or 'Not found'}")

            if data["key_obligations"]:
                st.write("**Key obligations:**")
                for obligation in data["key_obligations"]:
                    st.write(f"- {obligation['party']}: {obligation['obligation']}")

            st.write("**Risk counts:**")
            counts = data["risk_counts"]
            risk_cols = st.columns(len(counts))
            for col, (level, count) in zip(risk_cols, counts.items()):
                col.metric(level.title(), count)

            if data["risk_summary_narrative"]:
                st.write(f"**Risk narrative:** {data['risk_summary_narrative']}")

            if data["citations"]:
                st.markdown("**Verified summary citations:**")
                for citation in data["citations"]:
                    st.markdown(f"> chunk `{citation['chunk_id']}`: *\"{citation['quote']}\"*")
        else:
            show_error(code, msg)
