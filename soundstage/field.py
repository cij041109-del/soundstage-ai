"""
soundstage 이슈 9: 촘촘한 격자로 음향 분포를 "면"으로 평가하기

지금까지는 좌석 12곳(청취 지점)에서만 소리 크기를 재서 균일도(std_db)를 계산했다.
그런데 12곳은 듬성듬성하기 때문에, 좌석 "사이"에 소리가 유난히 큰 곳(핫스팟)이 있어도 놓친다.
예) 스피커를 청취 구역 한가운데 천장에 달면, 스피커 바로 아래는 소리가 크게 솟는다.
    좌석 12곳이 마침 그 봉우리를 피해 있으면 12곳 기준으로는 "균일하다"고 잘못 판단할 수 있다.

이 파일은 청취 구역을 0.5 m(또는 더 촘촘한) 간격 격자로 덮어서 평가한다.
  make_dense_grid  : 촘촘한 격자점 만들기
  evaluate_field   : 격자점마다 소리 크기(dB)를 구해 2차원 배열(지도)로 돌려주기
  zone_stats       : 지도 중 청취 구역 안의 평균/표준편차/최솟값
  compare_sampling : "12곳 평가"와 "촘촘한 격자 평가"로 추천 결과가 어떻게 달라지는지 비교

실행 방법:  python soundstage/field.py   (후보 76개 x 격자 187점, 1분 정도 걸린다)
"""

import math
import os
import sys
import time

import numpy as np

# 어느 폴더에서 실행하든 같은 폴더의 evaluate.py 등을 import할 수 있게 한다
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from candidates import DEFAULT_STEP, generate_candidates           # noqa: E402
from demo_basic import FS, MAX_ORDER, WALL_ABSORPTION              # noqa: E402
from evaluate import evaluate_position                             # noqa: E402
from recommend import recommend_placement                          # noqa: E402
from room_config import load_room                                  # noqa: E402

# 좌표가 0.1 + 0.2 = 0.30000000000000004 처럼 아주 조금 어긋나도 "같은 값"으로 보기 위한 허용 오차 [m]
TOL = 1e-6


# ---------------------------------------------------------------------
# 1) 격자 만들기
# ---------------------------------------------------------------------
def _axis(start, stop, step):
    """
    start부터 stop까지(양 끝 포함) step 간격 좌표 배열을 만든다.

    np.arange(start, stop, step)은 실수 오차 때문에 끝점(stop)이 빠지거나 넘칠 수 있어서,
    "몇 칸인지"를 먼저 정수로 계산한 뒤 start + 번호 x step 으로 만든다.
    """
    n = int(math.floor((stop - start) / step + 1e-9)) + 1
    return np.round(start + step * np.arange(n), 9)


def listening_zone(listening_points):
    """
    청취 지점(좌석)들을 모두 감싸는 가장 작은 사각형 (x_min, y_min, x_max, y_max)를 돌려준다.
    5420 강의실 기본값이면 (1.0, 2.0, 9.0, 7.0) = "청취 구역"이다.
    """
    pts = np.asarray(listening_points, dtype=float)
    return (float(pts[:, 0].min()), float(pts[:, 1].min()),
            float(pts[:, 0].max()), float(pts[:, 1].max()))


def make_dense_grid(room_dims, step=0.5, height=1.2, zone=None, margin=0.25):
    """
    방 바닥(또는 청취 구역)을 step 간격 격자로 덮는 점들을 만든다.

    매개변수
    --------
    room_dims : (가로, 세로, 높이) 방 치수 [m]
    step      : 격자 간격 [m]. 작을수록 촘촘하다(점이 많아져 계산은 느려진다).
    height    : 격자점 높이 [m] (앉은 사람 귀 높이 1.2 m)
    zone      : None이면 방 전체(각 벽에서 margin만큼 안쪽),
                (x_min, y_min, x_max, y_max)를 주면 그 사각형 안만 (경계 포함)
    margin    : zone이 None일 때 벽에서 떨어뜨릴 거리 [m]
                (벽 "위"의 점은 시뮬레이션할 수 없어서 조금 안쪽부터 시작한다)

    반환값
    ------
    xs     : x 좌표 배열 (왼쪽 → 오른쪽)
    ys     : y 좌표 배열 (앞 → 뒤)
    points : [(x, y, height), ...]  ← "앞줄부터, 각 줄은 왼쪽부터" 순서
             그래서 계산 결과를 (len(ys), len(xs)) 모양으로 바로 접을(reshape) 수 있다.
    """
    W, L, H = (float(v) for v in room_dims)
    if step <= 0:
        raise ValueError(f"격자 간격 step은 0보다 커야 합니다. (받은 값: {step})")
    if not 0 < height < H:
        raise ValueError(f"격자 높이 {height} m가 방 밖입니다. (0 < 높이 < {H})")

    if zone is None:
        if margin <= 0 or 2 * margin >= min(W, L):
            raise ValueError(f"margin {margin} m가 올바르지 않습니다. (0보다 크고 방 크기의 절반보다 작아야 함)")
        x0, y0, x1, y1 = margin, margin, W - margin, L - margin
    else:
        x0, y0, x1, y1 = (float(v) for v in zone)
        if x0 > x1 or y0 > y1:
            raise ValueError(f"구역 {zone}은 x_min <= x_max, y_min <= y_max 이어야 합니다.")
        if x0 <= 0 or y0 <= 0 or x1 >= W or y1 >= L:
            raise ValueError(f"구역 {zone}이 방 안쪽(벽 제외)에 있지 않습니다. (방: {W} x {L} m)")

    xs = _axis(x0, x1, step)
    ys = _axis(y0, y1, step)
    points = [(float(x), float(y), float(height)) for y in ys for x in xs]
    return xs, ys, points


# ---------------------------------------------------------------------
# 2) 격자 전체를 한 번에 평가하기
# ---------------------------------------------------------------------
def evaluate_field(room_dims, speaker_pos, xs, ys, height=1.2,
                   absorption=WALL_ABSORPTION, max_order=MAX_ORDER, fs=FS):
    """
    스피커를 speaker_pos에 두었을 때, 격자 (xs x ys)의 모든 점에서 소리 크기[dB]를 구한다.

    evaluate.evaluate_position()에 "모든 격자점"을 청취 지점 목록으로 한꺼번에 넘긴다.
    → 방(ShoeBox)을 딱 한 번만 만들고, 마이크를 격자점 수만큼 달아서 RIR을 한 번에 계산한다.
      (점마다 방을 새로 만들면 수백 배 느려진다)

    반환값: (len(ys), len(xs)) 모양의 2차원 numpy 배열
            levels[j, i] = 좌표 (xs[i], ys[j])의 소리 크기 [dB]
            (행 = y 방향 줄, 열 = x 방향 칸. 그림의 contourf(xs, ys, levels)에 바로 쓸 수 있다)
    """
    xs = np.asarray(xs, dtype=float)
    ys = np.asarray(ys, dtype=float)
    points = [(float(x), float(y), float(height)) for y in ys for x in xs]
    result = evaluate_position(room_dims, speaker_pos, points,
                               absorption=absorption, max_order=max_order, fs=fs)
    return np.array(result["levels_db"]).reshape(len(ys), len(xs))


def zone_stats(levels_grid, xs, ys, zone):
    """
    2차원 dB 지도 중에서 구역 zone = (x_min, y_min, x_max, y_max) 안(경계 포함)의 점만 골라
    평균·표준편차·최솟값·최댓값을 돌려준다.

    표준편차는 evaluate.py와 같은 np.std(모집단 표준편차, ddof=0)를 쓴다.
    """
    levels = np.asarray(levels_grid, dtype=float)
    xs = np.asarray(xs, dtype=float)
    ys = np.asarray(ys, dtype=float)
    x0, y0, x1, y1 = zone
    in_x = (xs >= x0 - TOL) & (xs <= x1 + TOL)     # 구역 안에 드는 열(x)
    in_y = (ys >= y0 - TOL) & (ys <= y1 + TOL)     # 구역 안에 드는 행(y)
    inside = levels[np.ix_(in_y, in_x)]            # 두 조건을 모두 만족하는 칸만 잘라낸다
    if inside.size == 0:
        raise ValueError(f"구역 {zone} 안에 격자점이 하나도 없습니다.")
    return {
        "mean_db": float(np.mean(inside)),
        "std_db": float(np.std(inside)),
        "min_db": float(np.min(inside)),
        "max_db": float(np.max(inside)),
        "num_points": int(inside.size),
    }


# ---------------------------------------------------------------------
# 3) 12곳 평가 vs 촘촘한 격자 평가 비교
# ---------------------------------------------------------------------
def _spearman(a, b):
    """두 점수 목록의 순위 상관계수(Spearman). 1이면 순위가 똑같고, 0 근처면 거의 무관하다."""
    from scipy.stats import spearmanr
    return float(spearmanr(a, b).correlation)


def _summary(rec):
    """recommend_placement 결과에서 비교에 필요한 숫자만 뽑는다."""
    return {
        "baseline_position": tuple(rec["baseline"]["position"]),
        "baseline_std_db": float(rec["baseline"]["std_db"]),
        "best_position": tuple(rec["best"]["position"]),
        "best_std_db": float(rec["best"]["std_db"]),
        "best_min_db": float(rec["best"]["min_db"]),
        "improvement_percent": float(rec["improvement_percent"]),
        "num_passed": int(rec["num_passed"]),
        "num_candidates": int(rec["num_candidates"]),
        # 최소 음향 조건과 상관없이, 기준 배치보다 std_db가 작은(더 균일한) 후보가 몇 개인지
        "num_better_than_baseline": sum(1 for r in rec["results"]
                                        if r["std_db"] < rec["baseline"]["std_db"]),
    }


def compare_sampling(room="5420", top_n=5, step=0.5, candidates=None, margin_db=0.0):
    """
    같은 후보·같은 규칙(recommend_placement)으로, 청취 지점만 바꿔서 두 번 추천해 본다.
      (a) seats : 기존 좌석 12곳
      (b) grid  : 청취 구역을 step 간격 격자로 덮은 점들 (기본 0.5 m → 187곳)

    매개변수
    --------
    room       : 방 이름("5420") 또는 room_config.load_room()이 돌려준 딕셔너리
    top_n      : 상위 몇 개 후보를 비교 표에 넣을지
    step       : 격자 간격 [m]
    candidates : 후보 위치 목록. None이면 방 설정으로 generate_candidates() (테스트에서 줄여 쓰려고 둔 인자)
    margin_db  : recommend_placement에 그대로 넘기는 최소 음향 조건 여유 [dB] (기본 0 = recommend.py와 같음)

    반환값 (딕셔너리)
    ------
    room_name, zone, step, num_seats, num_grid_points
    seats, grid : 각 방식의 요약 (기준 std, 추천 위치·std, 개선율 ...)
    cross       : 12곳 방식의 추천 위치를 "촘촘한 격자"로 다시 잰 결과
                  (std_db, 기준 대비 개선율, 촘촘한 방식에서의 순위)
    spearman    : 전체 후보의 std_db 순위가 두 방식에서 얼마나 비슷한지 (-1 ~ 1)
    table       : 두 방식 상위 top_n 후보를 합친 비교 표 (행마다 두 방식의 순위·std)
    seats_result, grid_result : recommend_placement 원래 결과 (그림 등에서 다시 쓰라고)
    """
    if isinstance(room, str):
        room = load_room(room)
    dims = tuple(room["dimensions_m"])
    absorption = room["wall_absorption"]
    seats = [tuple(p) for p in room["listening_points"]]
    ear_height = float(seats[0][2])

    if candidates is None:
        zones = [tuple(z) for z in room["forbidden_zones"]]
        candidates = generate_candidates(dims, DEFAULT_STEP, room["min_wall_distance_m"],
                                         room["speaker_height_m"], forbidden_zones=zones)
    candidates = [tuple(c) for c in candidates]

    # 청취 구역 = 좌석 12곳을 감싸는 사각형, 그 안을 step 간격으로 덮는다
    zone = listening_zone(seats)
    _, _, grid_points = make_dense_grid(dims, step=step, height=ear_height, zone=zone)

    # recommend.py는 고치지 않고 listening_points만 바꿔서 두 번 호출한다
    rec_seats = recommend_placement(dims, candidates, seats, absorption=absorption,
                                    margin_db=margin_db, top_n=top_n)
    rec_grid = recommend_placement(dims, candidates, grid_points, absorption=absorption,
                                   margin_db=margin_db, top_n=top_n)

    # 두 결과의 results는 후보 입력 순서 그대로이므로, 같은 번호끼리 같은 후보다
    std_seats = [r["std_db"] for r in rec_seats["results"]]
    std_grid = [r["std_db"] for r in rec_grid["results"]]

    def ranks(rec):
        """조건(최소 음향 수준)을 통과한 후보의 순위 {위치: 1, 2, ...}. 탈락 후보는 없음."""
        passed = sorted((r for r in rec["results"] if r["min_db"] >= rec["threshold_db"]),
                        key=lambda r: r["std_db"])
        return {tuple(r["position"]): i + 1 for i, r in enumerate(passed)}

    rank_seats, rank_grid = ranks(rec_seats), ranks(rec_grid)
    by_pos_seats = {tuple(r["position"]): r for r in rec_seats["results"]}
    by_pos_grid = {tuple(r["position"]): r for r in rec_grid["results"]}

    # 비교 표: 12곳 상위 → 격자 상위 순서로, 중복 없이
    order = []
    for r in rec_seats["top"] + rec_grid["top"]:
        pos = tuple(r["position"])
        if pos not in order:
            order.append(pos)
    table = [{
        "position": pos,
        "seats_rank": rank_seats.get(pos),          # None = 최소 음향 조건 탈락
        "seats_std_db": float(by_pos_seats[pos]["std_db"]),
        "grid_rank": rank_grid.get(pos),
        "grid_std_db": float(by_pos_grid[pos]["std_db"]),
    } for pos in order]

    # 12곳 방식이 추천한 자리를 촘촘한 격자로 다시 재면?
    seat_best = tuple(rec_seats["best"]["position"])
    grid_base_std = float(rec_grid["baseline"]["std_db"])
    cross_std = float(by_pos_grid[seat_best]["std_db"])
    cross = {
        "position": seat_best,
        "std_db": cross_std,
        "improvement_percent": (grid_base_std - cross_std) / grid_base_std * 100 if grid_base_std > 0 else 0.0,
        "grid_rank": rank_grid.get(seat_best),
    }

    return {
        "room_name": room["room_name"],
        "zone": zone,
        "step": float(step),
        "num_seats": len(seats),
        "num_grid_points": len(grid_points),
        "seats": _summary(rec_seats),
        "grid": _summary(rec_grid),
        "cross": cross,
        "spearman": _spearman(std_seats, std_grid),
        "table": table,
        "seats_result": rec_seats,
        "grid_result": rec_grid,
    }


# ---------------------------------------------------------------------
# 4) 보기 좋게 출력하기
# ---------------------------------------------------------------------
def _fmt(pos):
    return "(" + ", ".join(f"{v:.1f}" for v in pos) + ")"


def print_comparison(cmp):
    """compare_sampling() 결과를 한국어로 출력한다. (한글은 글자 폭이 달라 표 칸 대신 '항목: 값 | 값' 모양으로)"""
    line = "=" * 72
    s, g, c = cmp["seats"], cmp["grid"], cmp["cross"]
    print(line)
    print(f" {cmp['room_name']} 강의실: 좌석 12곳 평가 vs 촘촘한 격자 평가")
    print(line)
    z = cmp["zone"]
    print(f"청취 구역 x {z[0]:g}~{z[2]:g} m, y {z[1]:g}~{z[3]:g} m")
    print(f"  (a) 좌석 {cmp['num_seats']}곳      (b) {cmp['step']:g} m 격자 {cmp['num_grid_points']}곳")
    print()
    print("                  (a) 좌석 12곳          (b) 촘촘한 격자")
    print(f"  기준 배치 std : {s['baseline_std_db']:8.3f} dB          {g['baseline_std_db']:8.3f} dB")
    print(f"  추천 위치     : {_fmt(s['best_position']):17}      {_fmt(g['best_position'])}")
    print(f"  추천 배치 std : {s['best_std_db']:8.3f} dB          {g['best_std_db']:8.3f} dB")
    print(f"  개선율        : {s['improvement_percent']:+8.1f} %           {g['improvement_percent']:+8.1f} %")
    print(f"  조건 통과     : {s['num_passed']:3d} / {s['num_candidates']}              "
          f"{g['num_passed']:3d} / {g['num_candidates']}")
    print(f"  기준보다 균일 : {s['num_better_than_baseline']:3d}개                  "
          f"{g['num_better_than_baseline']:3d}개   (조건과 무관하게 std만 비교)")
    print()
    rank = f"{c['grid_rank']}위" if c["grid_rank"] else "조건 탈락"
    verdict = "좋아짐" if c["improvement_percent"] > 0 else "오히려 나빠짐 → 순위 역전"
    print(f"[교차 확인] (a)의 추천 {_fmt(c['position'])}를 (b) 촘촘한 격자로 다시 재면")
    print(f"  std {c['std_db']:.3f} dB, 기준 배치({g['baseline_std_db']:.3f} dB) 대비 "
          f"{c['improvement_percent']:+.1f} %, (b) 방식 순위 {rank}")
    print(f"  → 기준 배치보다 {verdict}")
    print()
    print(f"[후보 순위 상관] Spearman = {cmp['spearman']:.3f}")
    print(f"  (전체 {s['num_candidates']}개 후보의 std_db 순위를 비교. 1이면 두 방식 순위가 똑같다)")
    print()
    print("[상위 후보 비교]  순위 = 최소 음향 조건을 통과한 후보끼리의 순위, '-' = 조건 탈락")
    print("   위치 (x, y, z)  |  (a) 순위   (a) std  |  (b) 순위   (b) std")
    print("-" * 72)
    for row in cmp["table"]:
        rs = row["seats_rank"] if row["seats_rank"] else "-"
        rg = row["grid_rank"] if row["grid_rank"] else "-"
        print(f"  {_fmt(row['position']):16} |  {rs!s:>6}   {row['seats_std_db']:7.3f}  |  "
              f"{rg!s:>6}   {row['grid_std_db']:7.3f}")
    print("-" * 72)


# 이 파일을 직접 실행했을 때만 아래가 실행된다
if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):     # Windows 콘솔에서 한글 출력 오류 방지
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    start = time.perf_counter()
    result = compare_sampling("5420", top_n=5, step=0.5)
    print_comparison(result)
    print(f"계산 시간: {time.perf_counter() - start:.1f}초")
