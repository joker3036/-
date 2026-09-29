"""Altair 차트: 돌파 산점도, 성장 타임라인, 구독자 추이, 평균 막대."""
from __future__ import annotations

import altair as alt
import pandas as pd

from ui.common import colors, type_label

SMALL = "구독 1만 미만"
BIG = "구독 1만 이상"


def breakout_scatter(df: pd.DataFrame, threshold: int = 10_000) -> alt.Chart:
    """x = 채널 구독자, y = 영상 조회수 (둘 다 로그). 대각선 = 조회수가 구독자의 1배·10배."""
    c = colors()
    data = df.dropna(subset=["subscribers", "views"]).copy()
    data = data[(data["subscribers"] > 0) & (data["views"] > 0)]
    data["규모"] = data["subscribers"].apply(lambda s: SMALL if s < threshold else BIG)
    data["돌파 지수"] = data["breakout"].round(1)
    data["떡상 점수"] = data["outlier"].round(1)
    data["유형"] = data["content_type"].apply(type_label)
    data = data[["video_id", "title", "channel_title", "subscribers", "views", "규모", "돌파 지수", "떡상 점수", "유형"]]

    x_dom = [max(data["subscribers"].min() * 0.8, 1), data["subscribers"].max() * 1.25] if not data.empty else [100, 1e6]
    y_dom = [max(data["views"].min() * 0.8, 1), data["views"].max() * 1.25] if not data.empty else [100, 1e6]
    # 기준선: 조회수 = 구독자 × k. 축 범위 안에 들어오는 구간만 그린다.
    rows = []
    for k in (1, 10):
        x0, x1 = max(x_dom[0], y_dom[0] / k), min(x_dom[1], y_dom[1] / k)
        if x0 < x1:
            rows += [{"x": x0, "y": x0 * k, "선": f"조회수 = 구독자 × {k}"}, {"x": x1, "y": x1 * k, "선": f"조회수 = 구독자 × {k}"}]
    refs = pd.DataFrame(rows, columns=["x", "y", "선"])
    x_scale = alt.Scale(type="log", domain=x_dom)
    y_scale = alt.Scale(type="log", domain=y_dom)
    x = alt.X("subscribers:Q", title="채널 구독자 (로그 눈금)", scale=x_scale)
    y = alt.Y("views:Q", title="영상 조회수 (로그 눈금)", scale=y_scale)

    ref_lines = alt.Chart(refs).mark_line(strokeDash=[4, 4], strokeWidth=1, color=c["muted"]).encode(
        x=alt.X("x:Q", scale=x_scale), y=alt.Y("y:Q", scale=y_scale), detail="선:N",
    )
    ref_labels = alt.Chart(refs.groupby("선").last().reset_index()).mark_text(
        align="right", dx=-6, dy=-8, fontSize=11, color=c["text2"]
    ).encode(x=alt.X("x:Q", scale=x_scale), y=alt.Y("y:Q", scale=y_scale), text="선:N")

    pick = alt.selection_point(name="pick", fields=["video_id"], on="click")
    points = alt.Chart(data).mark_circle(size=70, stroke=c["surface"], strokeWidth=1).encode(
        x=x, y=y,
        color=alt.Color("규모:N", scale=alt.Scale(domain=[SMALL, BIG], range=[c["series1"], c["series2"]]),
                        legend=alt.Legend(title=None, orient="top")),
        opacity=alt.condition(pick, alt.value(0.9), alt.value(0.35)),
        tooltip=[
            alt.Tooltip("title:N", title="제목"),
            alt.Tooltip("channel_title:N", title="채널"),
            alt.Tooltip("subscribers:Q", title="구독자", format=","),
            alt.Tooltip("views:Q", title="조회수", format=","),
            alt.Tooltip("돌파 지수:Q", title="조회수÷구독자"),
            alt.Tooltip("떡상 점수:Q", title="채널 평소 대비"),
            alt.Tooltip("유형:N"),
        ],
    ).add_params(pick)
    return (ref_lines + ref_labels + points).properties(height=460)


def timeline_chart(videos: pd.DataFrame, turning_video_id: str | None = None) -> alt.Chart:
    """업로드 날짜별 롱폼 조회수. 터닝포인트 영상은 크게 표시하고 이름표를 붙인다."""
    c = colors()
    data = videos.dropna(subset=["published", "views"]).copy()
    data = data[data["views"] > 0]
    data["유형"] = data["content_type"].apply(type_label)
    data = data[["video_id", "title", "published", "views", "유형"]]
    base = alt.Chart(data).encode(
        x=alt.X("published:T", title="업로드 날짜", axis=alt.Axis(format="%Y-%m")),
        y=alt.Y("views:Q", title="조회수 (로그 눈금)", scale=alt.Scale(type="log")),
        tooltip=[alt.Tooltip("published:T", title="업로드", format="%Y-%m-%d"), alt.Tooltip("title:N", title="제목"),
                 alt.Tooltip("views:Q", title="조회수", format=","), alt.Tooltip("유형:N")],
    )
    line = base.mark_line(strokeWidth=2, color=c["series1"])
    dots = base.mark_circle(size=64, color=c["series1"], stroke=c["surface"], strokeWidth=1)
    layers = [line, dots]
    if turning_video_id is not None:
        tp = data[data["video_id"] == turning_video_id]
        if not tp.empty:
            tp_base = alt.Chart(tp).encode(x="published:T", y=alt.Y("views:Q", scale=alt.Scale(type="log")))
            layers.append(tp_base.mark_circle(size=220, color=c["series2"], stroke=c["surface"], strokeWidth=2))
            layers.append(tp_base.mark_text(dy=-16, fontSize=12, fontWeight="bold", color=c["text2"]).encode(
                text=alt.value("터닝포인트")))
    return alt.layer(*layers).properties(height=320)


def subscriber_trend(history: pd.DataFrame, threshold: int = 10_000) -> alt.Chart:
    c = colors()
    data = history.dropna(subset=["subscribers"]).copy()
    data["captured"] = pd.to_datetime(data["captured_at"], utc=True)
    line = alt.Chart(data).mark_line(strokeWidth=2, color=c["series1"], point=alt.OverlayMarkDef(size=64, color=c["series1"])).encode(
        x=alt.X("captured:T", title="수집 날짜", axis=alt.Axis(format="%m/%d")),
        y=alt.Y("subscribers:Q", title="구독자", scale=alt.Scale(zero=False)),
        tooltip=[alt.Tooltip("captured:T", title="날짜", format="%Y-%m-%d"), alt.Tooltip("subscribers:Q", title="구독자", format=",")],
    )
    rule = alt.Chart(pd.DataFrame({"y": [threshold]})).mark_rule(strokeDash=[4, 4], color=c["muted"]).encode(y="y:Q")
    label = alt.Chart(pd.DataFrame({"y": [threshold], "t": ["구독 1만"]})).mark_text(
        align="left", dx=4, dy=-6, color=c["text2"], fontSize=11).encode(y="y:Q", text="t:N", x=alt.value(0))
    layers = [line]
    # 1만 기준선은 구독자가 그 근처일 때만 그린다 (대형 채널에 그리면 축이 0까지 늘어나 추이가 납작해짐)
    if data["subscribers"].max() >= threshold * 0.7 and data["subscribers"].min() <= threshold * 1.3:
        layers += [rule, label]
    return alt.layer(*layers).properties(height=220)


def mean_bars(df: pd.DataFrame, category: str, value: str, count: str, value_title: str, fmt: str = ".1f") -> alt.Chart:
    """항목별 평균값 가로 막대 (값 순으로 정렬, 막대 끝에 값 표시)."""
    c = colors()
    base = alt.Chart(df).encode(
        y=alt.Y(f"{category}:N", sort="-x", title=None, axis=alt.Axis(labelLimit=220, labelOverlap=False)),
        x=alt.X(f"{value}:Q", title=value_title),
        tooltip=[alt.Tooltip(f"{category}:N", title="항목"), alt.Tooltip(f"{value}:Q", title=value_title, format=fmt),
                 alt.Tooltip(f"{count}:Q", title="영상 수")],
    )
    bars = base.mark_bar(color=c["series1"], cornerRadiusEnd=4, height={"band": 0.7})
    labels = base.mark_text(align="left", dx=4, color=c["text2"], fontSize=11).encode(text=alt.Text(f"{value}:Q", format=fmt))
    return (bars + labels).properties(height=alt.Step(30))
