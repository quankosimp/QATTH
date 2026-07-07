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
        "cv_profile": None,
        "interview_id": None,
        "messages": [],
        "interview_result": None,
        "match_items": [],
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


def post_json(path: str, payload: dict[str, Any]) -> Any:
    with httpx.Client(timeout=60.0) as client:
        return unwrap_response(client.post(f"{api_base()}{path}", json=payload))


def get_json(path: str) -> Any:
    with httpx.Client(timeout=60.0) as client:
        return unwrap_response(client.get(f"{api_base()}{path}"))


def send_interview_message(interview_id: str, text: str) -> list[dict[str, Any]]:
    url = f"{ws_base(api_base())}/v1/interviews/{interview_id}/stream"
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
                    result = unwrap_response(client.post(f"{base}/v1/cvs/scan", files=files, data=data))
                st.session_state.cv_id = result["cv_id"]
                st.session_state.cv_profile = result["profile"]
                st.success(f"CV scanned: {result['cv_id']}")

        if st.session_state.cv_profile:
            render_profile(st.session_state.cv_profile)

    with tab_interview:
        st.header("Virtual interview")
        if not st.session_state.cv_id:
            st.info("Scan a CV first.")
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
            if st.button("Generate matches", disabled=not st.session_state.cv_id):
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
