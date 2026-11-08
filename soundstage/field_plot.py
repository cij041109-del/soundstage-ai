"""
soundstage 이슈 9: 촘촘한 격자 평가 결과를 "연속 열지도"로 그리기 (matplotlib)

좌석 12곳의 점 대신, 방 바닥 전체의 소리 크기(dB)를 등고선 색칠(contourf)로 보여 준다.
  (왼쪽) 기준 배치   (오른쪽) 추천 배치    ← 두 그림은 같은 색 범위를 쓴다 (색을 공정하게 비교하려고)
표시: 스피커 위치(★), 청취 구역(점선 사각형), 좌석 12곳(흰 점)

그림 좌표 약속은 visualize.py와 같다: 천장에서 내려다본 평면도, 앞벽(y=0)이 그림 위쪽.

실행 방법:  python soundstage/field_plot.py   → soundstage/output/field.png 저장
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import matplotlib                                    # noqa: E402
matplotlib.use("Agg")                                # 창을 띄우지 않고 파일로만 저장하는 방식
import numpy as np                                   # noqa: E402
from matplotlib.figure import Figure                 # noqa: E402
from matplotlib.lines import Line2D                  # noqa: E402
from matplotlib.patches import Rectangle             # noqa: E402

from field import zone_stats                         # noqa: E402
from visualize import setup_korean_font              # noqa: E402  (Malgun Gothic 설정 함수 재사용)

# 등고선 색 단계 수 (많을수록 매끄럽다) 와 색 지도 (visualize.py의 청취 지점 색과 같은 viridis)
LEVEL_STEPS = 40
CMAP = "viridis"


def _color_range(levels_list, xs, ys, zone):
    """
    여러 지도의 "청취 구역 안" 값만 모아 공통 색 범위 (vmin, vmax)를 정한다.

    방 전체를 쓰면 스피커 바로 근처의 아주 큰 값 때문에 색 범위가 넓어져서,
    정작 관심 있는 청취 구역 안의 차이가 잘 안 보인다. 그래서 구역 값으로 범위를 정하고,
    구역 밖에서 범위를 벗어나는 값은 맨 끝 색으로 칠한다(extend="both").
    """
    lows, highs = [], []
    for levels in levels_list:
        st = zone_stats(levels, xs, ys, zone)
        lows.append(st["min_db"])
        highs.append(st["max_db"])
    vmin, vmax = min(lows), max(highs)
    if vmax - vmin < 1e-9:
        vmin, vmax = vmin - 0.5, vmax + 0.5
    return vmin, vmax


def _draw_panel(ax, room_dims, xs, ys, levels, speaker_pos, zone, seat_points, title, norm_levels, color):
    """패널 하나(한 배치)를 그린다. 반환값: 색 막대(colorbar)에 쓸 contourf 결과"""
    W, L = room_dims[0], room_dims[1]
    # contourf: 격자점 값 사이를 이어서 "연속된 색 면"으로 칠한다
    cs = ax.contourf(xs, ys, levels, levels=norm_levels, cmap=CMAP, extend="both")

    # 방 테두리
    ax.add_patch(Rectangle((0, 0), W, L, fill=False, edgecolor="#333333", linewidth=1.2))
    # 청취 구역: 점선 사각형
    x0, y0, x1, y1 = zone
    ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, edgecolor="white",
                           linewidth=1.4, linestyle="--"))
    # 좌석 12곳: 흰 점 (검은 테두리로 밝은 색 위에서도 보이게)
    seats = np.asarray(seat_points, dtype=float)
    ax.scatter(seats[:, 0], seats[:, 1], s=26, facecolor="white", edgecolor="black",
               linewidth=0.8, zorder=5)
    # 스피커: 별 모양 (흰 테두리로 어떤 배경색에서도 보이게)
    ax.scatter([speaker_pos[0]], [speaker_pos[1]], marker="*", s=260, color=color,
               edgecolor="white", linewidth=1.2, zorder=6)

    ax.set_title(title, fontsize=11)
    ax.set_xlim(0, W)
    ax.set_ylim(L, 0)                     # y축을 뒤집어 앞벽(y=0)이 위에 오게
    ax.set_aspect("equal")
    ax.set_xlabel("x [m] (가로)")
    ax.set_ylabel("y [m]  (0 = 앞벽·칠판 → 뒤)")
    return cs


def plot_field_comparison(room_dims, xs, ys, base_levels, rec_levels, base_pos, rec_pos,
                          zone, seat_points, save_path):
    """
    기준/추천 배치의 연속 열지도 두 개를 나란히 그려 PNG(dpi 200)로 저장한다.

    room_dims   : (가로, 세로, 높이) [m]
    xs, ys      : 격자 좌표 배열
    base_levels, rec_levels : (len(ys), len(xs)) dB 지도 (field.evaluate_field 결과)
    base_pos, rec_pos       : 기준·추천 스피커 위치 (x, y, z)
    zone        : 청취 구역 (x_min, y_min, x_max, y_max)
    seat_points : 좌석 12곳 [(x, y, z), ...]
    save_path   : 저장할 PNG 경로
    반환값: 저장한 경로
    """
    setup_korean_font()
    vmin, vmax = _color_range([base_levels, rec_levels], xs, ys, zone)
    norm_levels = np.linspace(vmin, vmax, LEVEL_STEPS + 1)   # 두 패널이 똑같은 색 경계를 쓴다

    # Figure를 직접 만들면 pyplot 창 관리 없이 저장만 할 수 있다
    fig = Figure(figsize=(13, 5.6))
    axes = fig.subplots(1, 2)
    panels = (("기준 배치", base_levels, base_pos, "#d62728"),
              ("추천 배치", rec_levels, rec_pos, "#2ca02c"))
    cs = None
    for ax, (name, levels, pos, color) in zip(axes, panels):
        st = zone_stats(levels, xs, ys, zone)
        title = (f"{name}  스피커 ({pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.1f}) m\n"
                 f"청취 구역 std {st['std_db']:.2f} dB · 최소 {st['min_db']:.1f} · 최대 {st['max_db']:.1f} dB")
        cs = _draw_panel(ax, room_dims, xs, ys, levels, pos, zone, seat_points, title, norm_levels, color)

    # 색 막대는 오른쪽에 따로 자리(cax)를 만들어 그린다 (패널을 가리지 않게)
    fig.subplots_adjust(left=0.05, right=0.89, top=0.84, bottom=0.16, wspace=0.16)
    cax = fig.add_axes([0.915, 0.2, 0.014, 0.6])
    cbar = fig.colorbar(cs, cax=cax)
    cbar.set_label("소리 크기 [dB]  (밝을수록 크게 들림)")
    cbar.set_ticks(np.round(np.linspace(vmin, vmax, 6), 1))

    legend = [
        Line2D([], [], marker="*", linestyle="", markersize=13, color="#d62728", markeredgecolor="white",
               label="기준 스피커"),
        Line2D([], [], marker="*", linestyle="", markersize=13, color="#2ca02c", markeredgecolor="white",
               label="추천 스피커"),
        Line2D([], [], marker="o", linestyle="", markersize=6, markerfacecolor="white", markeredgecolor="black",
               label="좌석 12곳"),
        Line2D([], [], linestyle="--", color="#555555", label="청취 구역"),
    ]
    fig.legend(handles=legend, loc="lower center", ncol=4, frameon=False, fontsize=9)
    fig.suptitle("촘촘한 격자로 본 소리 크기 분포 (색 범위는 청취 구역 값 기준, 범위 밖은 끝 색)",
                 fontsize=13, fontweight="bold")

    folder = os.path.dirname(os.path.abspath(save_path))
    os.makedirs(folder, exist_ok=True)
    fig.savefig(save_path, dpi=200)
    return save_path


# 이 파일을 직접 실행했을 때만 아래가 실행된다
if __name__ == "__main__":
    import time

    from candidates import DEFAULT_STEP, generate_candidates
    from field import evaluate_field, listening_zone, make_dense_grid
    from recommend import recommend_placement
    from room_config import load_room

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    start = time.perf_counter()
    room = load_room("5420")
    dims = tuple(room["dimensions_m"])
    seats = [tuple(p) for p in room["listening_points"]]
    zone = listening_zone(seats)
    cands = generate_candidates(dims, DEFAULT_STEP, room["min_wall_distance_m"], room["speaker_height_m"],
                                forbidden_zones=[tuple(z) for z in room["forbidden_zones"]])

    # 추천 위치는 지금까지 써 온 방식(좌석 12곳)으로 정한다 → 그 추천이 "면"으로 보면 어떤지 확인
    rec = recommend_placement(dims, cands, seats, absorption=room["wall_absorption"])
    base_pos, rec_pos = rec["baseline"]["position"], rec["best"]["position"]

    # 방 전체(벽에서 0.25 m 안쪽)를 0.25 m 격자로
    xs, ys, _ = make_dense_grid(dims, step=0.25, height=seats[0][2])
    base_levels = evaluate_field(dims, base_pos, xs, ys, height=seats[0][2], absorption=room["wall_absorption"])
    rec_levels = evaluate_field(dims, rec_pos, xs, ys, height=seats[0][2], absorption=room["wall_absorption"])

    path = plot_field_comparison(dims, xs, ys, base_levels, rec_levels, base_pos, rec_pos, zone, seats,
                                 os.path.join(HERE, "output", "field.png"))
    for name, lv in (("기준", base_levels), ("추천", rec_levels)):
        st = zone_stats(lv, xs, ys, zone)
        print(f"{name} 배치: 청취 구역 {st['num_points']}점  std {st['std_db']:.3f} dB  "
              f"평균 {st['mean_db']:.2f}  최소 {st['min_db']:.2f}  최대 {st['max_db']:.2f} dB")
    print(f"격자 {len(xs)} x {len(ys)} = {len(xs) * len(ys)}점, 그림 저장: {path}")
    print(f"계산 시간: {time.perf_counter() - start:.1f}초")
