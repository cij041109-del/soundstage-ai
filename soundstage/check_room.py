"""
soundstage 이슈 7: rooms.json의 강의실 설정을 점검하는 스크립트

실측값을 rooms.json에 적은 뒤 이 스크립트를 돌리면,
  1) 설정을 읽어 값이 올바른지 검사하고 (잘못되면 무엇이 문제인지 한국어로 알려 준다)
  2) 방 치수, 실측 여부, 청취 지점, 금지 구역, 후보 개수를 요약해서 보여 주고
  3) 추천 계산(recommend_placement)을 끝까지 한 번 돌려 추천 위치와 개선율을 보여 준다.

실행 방법:
    python soundstage/check_room.py          (기본: 5420 강의실)
    python soundstage/check_room.py 5420
"""

import argparse
import contextlib
import os
import sys

# 어느 폴더에서 실행하든 같은 폴더의 모듈을 import할 수 있게 한다
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from candidates import generate_candidates  # noqa: E402
from recommend import default_baseline_position, recommend_placement  # noqa: E402
from room_config import load_room  # noqa: E402

# MCP 서버와 같은 1 m 격자로 후보를 만든다
CANDIDATE_STEP = 1.0


def _fmt(values):
    """[1.0, 2.0, 1.2] → '(1.00, 2.00, 1.20)' 모양 글자로 바꾼다."""
    return "(" + ", ".join(f"{float(v):.2f}" for v in values) + ")"


def print_summary(room, candidates):
    """방 설정 요약을 한국어로 출력한다."""
    w, l, h = room["dimensions_m"]
    pts = room["listening_points"]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    zs = [p[2] for p in pts]

    print(f"=== 강의실 {room['room_name']} 설정 점검 ===")
    if room["description"]:
        print(f"설명        : {room['description']}")
    print(f"방 치수     : 가로 {w:g} m x 세로 {l:g} m x 높이 {h:g} m")
    print(f"실측 여부   : {'실측값' if room['measured'] else '임시값 (measured: false)'}")
    if room["note"]:
        print(f"메모        : {room['note']}")
    print(f"벽 흡음률   : {room['wall_absorption']:g}")
    print(f"설치 높이   : {room['speaker_height_m']:g} m, 벽과 최소 거리 {room['min_wall_distance_m']:g} m")

    # 청취 지점 수와 범위
    if room["listening_source"] == "seating":
        s = room["seating"]
        how = (f"seating에서 자동 생성 ({s['cols']}열 x {s['rows']}행, "
               f"첫 좌석 {_fmt(s['first_seat_xy_m'])})")
    else:
        how = "listening_points 그대로 사용"
    print(f"청취 지점   : {len(pts)}개 - {how}")
    print(f"  범위      : x {min(xs):.2f}~{max(xs):.2f}, y {min(ys):.2f}~{max(ys):.2f}, "
          f"z {min(zs):.2f}~{max(zs):.2f} m")

    # 금지 구역
    zones = room["forbidden_zones"]
    if zones:
        print(f"금지 구역   : {len(zones)}개")
        for i, (x0, y0, x1, y1) in enumerate(zones):
            print(f"  {i}번      : x {x0:g}~{x1:g}, y {y0:g}~{y1:g} m")
    else:
        print("금지 구역   : 없음")

    print(f"후보 위치   : {len(candidates)}개 ({CANDIDATE_STEP:g} m 격자)")


def print_measured_warning(room):
    """measured가 false이면 눈에 띄게 경고한다."""
    if room["measured"]:
        return
    bar = "!" * 64
    print()
    print(bar)
    print("!!  [주의] 아직 임시값입니다.")
    print("!!  실측 후 rooms.json을 수정하고 measured를 true로 바꾸세요.")
    print("!!  (측정 방법: soundstage/MEASURE_5420.md)")
    print(bar)


def main(argv=None):
    parser = argparse.ArgumentParser(description="rooms.json 강의실 설정 점검")
    parser.add_argument("room_name", nargs="?", default="5420", help="강의실 이름 (기본: 5420)")
    parser.add_argument("--path", default=None, help="rooms.json 경로 (기본: soundstage/rooms.json)")
    args = parser.parse_args(argv)

    # 1) 설정 읽기 + 검사 (잘못되면 이유를 출력하고 실패 코드 1로 끝낸다)
    try:
        room = load_room(args.room_name, args.path)
        candidates = generate_candidates(room["dimensions_m"], CANDIDATE_STEP,
                                         room["min_wall_distance_m"], room["speaker_height_m"],
                                         forbidden_zones=room["forbidden_zones"])
    except ValueError as exc:
        print(f"[설정 오류] {exc}")
        return 1

    # 2) 요약 출력
    print_summary(room, candidates)
    print_measured_warning(room)
    print("\n설정 검증 통과.")

    # 3) 추천 계산을 끝까지 한 번 돌려 본다 (수 초 걸림)
    print(f"\n추천 계산 중... (후보 {len(candidates)}개 시뮬레이션)")
    try:
        dims = room["dimensions_m"]
        rec = recommend_placement(dims, candidates, room["listening_points"],
                                  baseline_pos=default_baseline_position(dims, candidates),
                                  absorption=room["wall_absorption"])
    except ValueError as exc:
        print(f"[계산 오류] {exc}")
        return 1

    base, best = rec["baseline"], rec["best"]
    print(f"기준 배치 (전면 중앙 상단): {_fmt(base['position'])} m, 균일도(std) {base['std_db']:.2f} dB")
    print(f"추천 위치                 : {_fmt(best['position'])} m, 균일도(std) {best['std_db']:.2f} dB")
    print(f"균일도 개선율             : {rec['improvement_percent']:.1f} %")
    print(f"조건 통과 후보            : {rec['num_passed']} / {rec['num_candidates']}개")
    if not room["measured"]:
        print("\n(위 결과는 임시값 기준입니다.)")
    return 0


if __name__ == "__main__":
    # Windows 콘솔(cp949)에서도 한글이 깨지지 않도록 출력 인코딩을 UTF-8로 맞춘다
    if hasattr(sys.stdout, "reconfigure"):
        with contextlib.suppress(Exception):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
