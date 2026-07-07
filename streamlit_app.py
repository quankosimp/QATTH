import json
import os
from typing import Any

import httpx
import streamlit as st
from websocket import create_connection


st.set_page_config(page_title="QATTH Career Demo", page_icon="Q", layout="wide")


def init_state() -> None:
    defaults = {
        "cv_id": None,
        "cv_status": None,
        "cv_draft_profile": None,
        "cv_draft_json": "",
        "cv_profile": None,
        "interview_id": None,
        "messages": [],
        "interview_result": None,
        "match_items": [],
        "access_token": None,
        "current_user": None,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def api_base() -> str:
    default = os.getenv("API_BASE_URL", "http://localhost:8000")
    return st.session_state.get("api_base_url", default).rstrip("/")


def ws_base(http_base: str) -> str:
    if http_base.startswith("https://"):
        return "wss://" + http_base.removeprefix("https://")
    return "ws://" + http_base.removeprefix("http://")


def unwrap_response(response: httpx.Response) -> Any:
    response.raise_for_status()
    body = response.json()
    if body.get("error"):
        raise RuntimeError(body["error"]["message"])
    return body["data"]


def auth_headers() -> dict[str, str]:
    token = st.session_state.get("access_token")
    return {"Authorization": f"Bearer {token}"} if token else {}


def post_json(path: str, payload: dict[str, Any]) -> Any:
    with httpx.Client(timeout=60.0) as client:
        return unwrap_response(client.post(f"{api_base()}{path}", json=payload, headers=auth_headers()))


def put_json(path: str, payload: dict[str, Any]) -> Any:
    with httpx.Client(timeout=60.0) as client:
        return unwrap_response(client.put(f"{api_base()}{path}", json=payload, headers=auth_headers()))


def get_json(path: str) -> Any:
    with httpx.Client(timeout=60.0) as client:
        return unwrap_response(client.get(f"{api_base()}{path}", headers=auth_headers()))


def send_interview_message(interview_id: str, text: str) -> list[dict[str, Any]]:
    url = f"{ws_base(api_base())}/v1/interviews/{interview_id}/stream?token={st.session_state.access_token}"
    ws = create_connection(url, timeout=15)
    events: list[dict[str, Any]] = []
    try:
        events.append(json.loads(ws.recv()))
        ws.send(json.dumps({"type": "text.message", "payload": {"text": text}}))
        while True:
            event = json.loads(ws.recv())
            events.append(event)
            if event.get("type") in {"transcript.model", "error"}:
                break
    finally:
        ws.close()
    return events


def render_profile(profile: dict[str, Any]) -> None:
    left, right = st.columns([1, 1])
    with left:
        st.subheader("Candidate")
        st.write(profile.get("name") or "Unknown")
        st.write(profile.get("email") or "No email")
        st.write(profile.get("summary") or "No summary")
    with right:
        st.subheader("Skills")
        skills = [item.get("name", "") for item in profile.get("skills", [])]
        st.write(", ".join(skill for skill in skills if skill) or "No skills detected")
    with st.expander("Raw CV profile JSON"):
        st.json(profile)


def main() -> None:
    init_state()
    st.title("QATTH Career Platform Demo")
    st.caption("Local Streamlit client for the FastAPI backend contract.")

    default_api_base = os.getenv("API_BASE_URL", "http://localhost:8000")
    st.sidebar.text_input("Backend URL", value=default_api_base, key="api_base_url")
    base = api_base()
    st.sidebar.write("API docs:", f"{base}/docs")

    st.sidebar.divider()
    st.sidebar.subheader("Account")
    if st.session_state.current_user:
        st.sidebar.write(st.session_state.current_user["email"])
        st.sidebar.caption(f"Role: {st.session_state.current_user['role']}")
        if st.sidebar.button("Log out"):
            st.session_state.access_token = None
            st.session_state.current_user = None
            st.rerun()
    else:
        auth_mode = st.sidebar.radio("Mode", ["Login", "Register"], horizontal=True)
        email = st.sidebar.text_input("Email")
        password = st.sidebar.text_input("Password", type="password")
        full_name = None
        if auth_mode == "Register":
            full_name = st.sidebar.text_input("Full name")
        if st.sidebar.button(auth_mode):
            path = "/v1/auth/login" if auth_mode == "Login" else "/v1/auth/register"
            payload = {"email": email, "password": password}
            if full_name:
                payload["full_name"] = full_name
            try:
                with httpx.Client(timeout=30.0) as client:
                    result = unwrap_response(client.post(f"{base}{path}", json=payload))
                st.session_state.access_token = result["access_token"]
                st.session_state.current_user = result["user"]
                st.rerun()
            except Exception as exc:
                st.sidebar.error(str(exc))

    if not st.session_state.current_user:
        st.info("Login or register to use the career platform.")
        return

    tab_cv, tab_interview, tab_jobs = st.tabs(["1. CV Scan", "2. Interview", "3. Job Matches"])

    with tab_cv:
        st.header("Scan CV")
        target_role = st.text_input("Target role", value="Backend Developer Intern")
        language = st.selectbox("Language", ["vi", "en"], index=0)
        uploaded = st.file_uploader("Upload CV", type=["pdf", "docx"])

        if st.button("Scan CV", disabled=uploaded is None):
            if uploaded is not None:
                files = {
                    "file": (
                        uploaded.name,
                        uploaded.getvalue(),
                        uploaded.type or "application/pdf",
                    )
                }
                data = {"target_role": target_role, "language": language}
                with httpx.Client(timeout=120.0) as client:
                    result = unwrap_response(
                        client.post(
                            f"{base}/v1/cvs/scan",
                            files=files,
                            data=data,
                            headers=auth_headers(),
                        )
                    )
                st.session_state.cv_id = result["cv_id"]
                st.session_state.cv_status = result["status"]
                st.session_state.cv_draft_profile = result["draft_profile"]
                st.session_state.cv_draft_json = json.dumps(
                    result["draft_profile"],
                    ensure_ascii=False,
                    indent=2,
                )
                st.session_state.cv_profile = None
                st.session_state.interview_id = None
                st.session_state.interview_result = None
                st.session_state.match_items = []
                st.success(f"CV scanned as draft: {result['cv_id']}")

        if st.session_state.cv_draft_profile and st.session_state.cv_status != "completed":
            st.subheader("Review and edit scanned JSON")
            edited_json = st.text_area(
                "Edit CV JSON before saving to database",
                key="cv_draft_json",
                height=520,
            )
            col_save, col_preview = st.columns([1, 1])
            with col_save:
                if st.button("Save edited CV to database"):
                    try:
                        edited_profile = json.loads(edited_json)
                        result = put_json(
                            f"/v1/cvs/{st.session_state.cv_id}/profile",
                            edited_profile,
                        )
                    except json.JSONDecodeError as exc:
                        st.error(f"Invalid JSON: {exc}")
                    except Exception as exc:
                        st.error(str(exc))
                    else:
                        st.session_state.cv_status = result["status"]
                        st.session_state.cv_profile = result["profile"]
                        st.success("Edited CV profile saved.")
            with col_preview:
                if st.button("Preview edited JSON"):
                    try:
                        st.json(json.loads(edited_json))
                    except json.JSONDecodeError as exc:
                        st.error(f"Invalid JSON: {exc}")

        if st.session_state.cv_profile:
            st.subheader("Saved CV profile")
            render_profile(st.session_state.cv_profile)

    with tab_interview:
        st.header("Virtual interview")
        if not st.session_state.cv_profile:
            st.info("Scan a CV and save the reviewed JSON profile first.")
        else:
            if st.button("Create interview room"):
                result = post_json(
                    "/v1/interviews",
                    {
                        "cv_id": st.session_state.cv_id,
                        "target_role": target_role,
                        "language": language,
                    },
                )
                st.session_state.interview_id = result["interview_id"]
                st.session_state.messages = [
                    {"role": "assistant", "text": result["opening_message"]}
                ]
                st.success(f"Interview created: {result['interview_id']}")

        if st.session_state.interview_id:
            st.caption(f"Interview ID: {st.session_state.interview_id}")
            for message in st.session_state.messages:
                with st.chat_message(message["role"]):
                    st.write(message["text"])

            prompt = st.chat_input("Reply to the interviewer")
            if prompt:
                st.session_state.messages.append({"role": "user", "text": prompt})
                events = send_interview_message(st.session_state.interview_id, prompt)
                for event in events:
                    if event.get("type") == "transcript.model":
                        text = event["payload"]["text"]
                        st.session_state.messages.append({"role": "assistant", "text": text})
                    if event.get("type") == "error":
                        st.error(event["payload"]["message"])
                st.rerun()

            if st.button("End interview and evaluate"):
                result = post_json(f"/v1/interviews/{st.session_state.interview_id}/end", {})
                st.session_state.interview_result = result["result"]
                st.success("Interview evaluated.")

        if st.session_state.interview_result:
            st.subheader("Evaluation")
            st.metric("Overall score", st.session_state.interview_result["overall_score"])
            st.write(st.session_state.interview_result["transcript_summary"])
            with st.expander("Full evaluation JSON"):
                st.json(st.session_state.interview_result)

    with tab_jobs:
        st.header("Job matching")
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("Seed local IT jobs"):
                result = post_json("/v1/jobs/crawl-runs", {"source": "seed", "query": "it", "max_pages": 1})
                st.success(f"Seeded {result['jobs_found']} jobs.")
        with col_b:
            if st.button("Generate matches", disabled=not st.session_state.cv_profile):
                result = post_json(
                    "/v1/matches",
                    {
                        "cv_id": st.session_state.cv_id,
                        "interview_id": st.session_state.interview_id,
                        "limit": 10,
                    },
                )
                st.session_state.match_items = result["items"]
                st.success(f"Match run: {result['match_id']}")

        for item in st.session_state.match_items:
            job = item["job"]
            with st.expander(f"{item['score']:.2f} - {job['title']} at {job['company']}"):
                st.write(f"Location: {job.get('location') or 'Unknown'}")
                st.write(f"Level: {job.get('level') or 'Unknown'}")
                st.write(f"Skills: {', '.join(job.get('skills') or [])}")
                st.write("Fit reasons")
                st.write(item["fit_reasons"])
                st.write("Gaps")
                st.write(item["gap_reasons"])
                st.write("JD")
                st.write(job["jd_text"])
                st.link_button("Apply / source", item["apply_url"])


if __name__ == "__main__":
    main()
