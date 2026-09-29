"""AI 분석 결과를 읽기 좋게 보여주기."""
from __future__ import annotations

import streamlit as st


def _bullets(items, empty: str = "_없음_") -> None:
    items = [i for i in (items or []) if i]
    st.markdown("\n".join(f"- {i}" for i in items) if items else empty)


def _chips(items) -> str:
    return " ".join(f"`{i}`" for i in (items or [])) or "-"


def video_analysis(r: dict) -> None:
    st.markdown(f"**상황 설정** — {r.get('situation', '-')}")
    c1, c2, c3 = st.columns(3)
    c1.markdown(f"**유형**  \n{r.get('content_type', '-')}")
    c2.markdown(f"**기획 장치**  \n{_chips(r.get('planning_devices'))}")
    c3.markdown(f"**신뢰도**  \n{r.get('confidence', '-')}")

    st.markdown("#### 💡 잘 된 이유 (가설)")
    _bullets(r.get("success_hypotheses"))
    st.markdown("#### ✅ 내 채널에 적용할 점")
    _bullets(r.get("apply_to_my_channel"))

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### 🔁 시그니처 요소")
        _bullets(r.get("signature_elements"))
        info = r.get("info_density") or {}
        st.markdown(f"#### 📘 정보 밀도: {info.get('level', '-')}")
        _bullets(info.get("examples"))
    with c2:
        st.markdown(f"#### 🏷️ 제목 장치\n{_chips(r.get('title_devices'))}")
        st.caption(r.get("title_comment", ""))
        th = r.get("thumbnail") or {}
        st.markdown("#### 🖼️ 썸네일")
        if th.get("available"):
            st.markdown(f"얼굴 {'있음' if th.get('has_face') else '없음'} · 문구 \"{th.get('text', '')}\" ({th.get('text_length', 0)}자)  \n"
                        f"{th.get('reaction', '')}  \n{th.get('composition', '')}  \n{th.get('comment', '')}")
        else:
            st.caption(th.get("comment") or "썸네일 분석 없음")

    hook = r.get("hook") or {}
    st.markdown(f"#### 🎣 훅: {hook.get('type', '-')}")
    st.markdown(hook.get("summary", "-"))
    if hook.get("quote"):
        st.markdown(f"> {hook['quote']}")
    if r.get("chapters"):
        st.markdown("#### 🧭 구성")
        st.markdown("\n".join(f"- `{c.get('time', '')}` {c.get('title', '')}" for c in r["chapters"]))

    aud = r.get("audience") or {}
    st.markdown("#### 💬 시청자 반응")
    cols = st.columns(4)
    for col, (key, label) in zip(cols, [("questions", "반복 질문"), ("requests", "다음 요청"), ("praise", "칭찬"), ("complaints", "불만")]):
        with col:
            st.markdown(f"**{label}**")
            _bullets(aud.get(key))
    if r.get("data_notes"):
        st.caption(f"참고: {r['data_notes']}")


def channel_analysis(kind: str, r: dict) -> None:
    st.markdown(f"**요약** — {r.get('summary', '-')}  \n신뢰도: {r.get('confidence', '-')}")
    if kind == "hidden_gem":
        st.markdown("**구독자에 비해 조회수가 나오는 이유**")
        _bullets(r.get("why_views"))
        st.markdown(f"**유입 추정**: {r.get('traffic_guess', '-')} — {r.get('traffic_reason', '')}")
        st.markdown(f"**포지셔닝**: {r.get('positioning', '-')}")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**시그니처 요소**")
            _bullets(r.get("signature_elements"))
            st.markdown("**주제 패턴**")
            _bullets(r.get("topic_patterns"))
        with c2:
            st.markdown("**제목·썸네일 패턴**")
            _bullets(r.get("title_thumbnail_patterns"))
            st.markdown(f"**업로드 운영**: {r.get('consistency', '-')}")
        st.markdown("**✅ 구독 1만을 위해 따라 할 점**")
        _bullets(r.get("lessons_for_10k"))
    elif kind == "contrast":
        for d in r.get("differences") or []:
            st.markdown(f"- **{d.get('aspect')}** — 떡상: {d.get('hit_videos')} / 평범: {d.get('normal_videos')}")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**따라 할 점**")
            _bullets(r.get("what_to_copy"))
        with c2:
            st.markdown("**피할 점**")
            _bullets(r.get("what_to_avoid"))
        st.markdown("**패턴**")
        _bullets(r.get("patterns"))
    elif kind == "growth":
        if r.get("turning_point_video"):
            st.markdown(f"**터닝포인트 영상**: {r['turning_point_video']}")
        for d in r.get("what_changed") or []:
            st.markdown(f"- **{d.get('aspect')}**: {d.get('before')} → {d.get('after')}")
        st.markdown("**통한 이유**")
        _bullets(r.get("why_it_worked"))
        if r.get("graduation_notes"):
            st.markdown(f"**🎓 1만 돌파 직전 변화**: {r['graduation_notes']}")
        st.markdown("**✅ 구독 1만을 위한 교훈**")
        _bullets(r.get("lessons_for_10k"))
    elif kind == "travel_check":
        st.markdown(f"여행 채널: {'예' if r.get('is_travel') else '아니오'} · {r.get('primary_type', '-')}  \n{r.get('reason', '')}")
