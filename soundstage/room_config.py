"""
soundstage 이슈 7: 강의실 설정을 rooms.json 한 곳에서 읽어 오는 모듈

강의실을 실측하면 rooms.json의 값만 고치면 된다.
이 모듈이 rooms.json을 읽고, 값이 말이 되는지 검사한 뒤, 다른 코드가 쓰기 좋은 딕셔너리로 돌려준다.
(MCP 서버 mcp_server.py와 점검 스크립트 check_room.py가 모두 이 모듈을 쓴다)

좌표 기준 (단위 m)
  원점(0, 0, 0) = 앞벽(교탁/칠판 쪽)·왼쪽 벽·바닥이 만나는 모서리
  x = 오른쪽으로, y = 뒤쪽(교실 뒤편)으로, z = 위쪽(천장)으로 커진다

청취 지점(관객 귀 위치)을 적는 방법은 두 가지다.
  1) "seating"(좌석 배치)을 적으면 → 좌석 격자에서 청취 지점을 자동으로 만든다. (권장)
       "seating": {"first_seat_xy_m": [x, y], "cols": 3, "rows": 4,
                   "col_spacing_m": 4.0, "row_spacing_m": 1.667, "ear_height_m": 1.2}
  2) "seating"이 없으면 → "listening_points": [[x, y, z], ...] 를 그대로 쓴다.
  둘 다 있으면 seating을 쓴다. (listening_points는 무시된다)

사용 예:
    from room_config import load_room
    room = load_room("5420")
    room["dimensions_m"]       # [10.0, 8.0, 3.0]
    room["listening_points"]   # [[1.0, 2.0, 1.2], ...]
"""

import json
import math
import os

# 이 파일과 같은 폴더의 rooms.json을 기본으로 읽는다
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROOMS_PATH = os.path.join(HERE, "rooms.json")

# 방 설정에 반드시 있어야 하는 항목 (청취 지점은 seating 또는 listening_points 중 하나)
REQUIRED_KEYS = ("dimensions_m", "wall_absorption", "forbidden_zones",
                 "speaker_height_m", "min_wall_distance_m")

# seating 안에 반드시 있어야 하는 항목
SEATING_KEYS = ("first_seat_xy_m", "cols", "rows",
                "col_spacing_m", "row_spacing_m", "ear_height_m")


# ---------------------------------------------------------------------
# 작은 도우미 함수들 (숫자 검사)
# ---------------------------------------------------------------------
def _number(value, name):
    """value가 유한한 숫자인지 확인하고 float로 바꿔 돌려준다. (True/False는 숫자로 치지 않는다)"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 값은 숫자여야 합니다. (받은 값: {value!r})")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} 값이 올바른 숫자가 아닙니다. (받은 값: {value!r})")
    return value


def _numbers(values, count, name):
    """숫자 count개짜리 리스트인지 확인하고 float 리스트로 돌려준다."""
    if not isinstance(values, (list, tuple)) or len(values) != count:
        raise ValueError(f"{name} 은(는) 숫자 {count}개짜리 목록이어야 합니다. (받은 값: {values!r})")
    return [_number(v, name) for v in values]


def _positive_int(value, name):
    """1 이상의 정수인지 확인한다. (3.0처럼 소수점 없는 실수도 허용)"""
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or value != int(value) or value < 1:
        raise ValueError(f"{name} 은(는) 1 이상의 정수여야 합니다. (받은 값: {value!r})")
    return int(value)


# ---------------------------------------------------------------------
# 좌석 격자 → 청취 지점 좌표
# ---------------------------------------------------------------------
def make_seat_grid(first_seat_xy, cols, rows, col_spacing, row_spacing, ear_height):
    """
    좌석 배치로 청취 지점 좌표 [[x, y, z], ...] 를 만든다.

    first_seat_xy : 첫 좌석(앞줄 왼쪽)의 (x, y) [m]
    cols          : 열 개수 (한 줄에 몇 자리인지, x 방향으로 늘어남)
    rows          : 행 개수 (몇 줄인지, y 방향 = 뒤쪽으로 늘어남)
    col_spacing   : 옆자리와의 간격 [m] (x 방향)
    row_spacing   : 앞뒤 줄 간격 [m] (y 방향)
    ear_height    : 앉은 사람 귀 높이 [m] (z)

    순서는 앞줄부터 뒷줄, 각 줄에서는 왼쪽부터 오른쪽이다. (demo_basic.py와 같은 순서)
    좌표는 "첫 좌석 + 번호 x 간격"으로 계산한다. (numpy.linspace와 같은 계산이라 값이 똑같이 나온다)
    """
    x0, y0 = _numbers(first_seat_xy, 2, "첫 좌석 위치(first_seat_xy_m)")
    cols = _positive_int(cols, "열 개수(cols)")
    rows = _positive_int(rows, "행 개수(rows)")
    col_spacing = _number(col_spacing, "열 간격(col_spacing_m)")
    row_spacing = _number(row_spacing, "행 간격(row_spacing_m)")
    ear_height = _number(ear_height, "귀 높이(ear_height_m)")

    # 자리가 2개 이상이면 간격이 0보다 커야 좌석이 겹치지 않는다
    if cols > 1 and col_spacing <= 0:
        raise ValueError(f"열 간격(col_spacing_m)은 0보다 커야 합니다. (받은 값: {col_spacing})")
    if rows > 1 and row_spacing <= 0:
        raise ValueError(f"행 간격(row_spacing_m)은 0보다 커야 합니다. (받은 값: {row_spacing})")

    points = []
    for r in range(rows):          # 앞줄 → 뒷줄
        for c in range(cols):      # 왼쪽 → 오른쪽
            points.append([x0 + c * col_spacing, y0 + r * row_spacing, ear_height])
    return points


# ---------------------------------------------------------------------
# rooms.json 읽기
# ---------------------------------------------------------------------
def load_rooms(path=None):
    """rooms.json을 읽어 {방 이름: 설정 딕셔너리}를 돌려준다. (값 검사는 하지 않는다)"""
    path = path or DEFAULT_ROOMS_PATH
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise ValueError(f"강의실 설정 파일을 찾을 수 없습니다: {path}") from None
    except json.JSONDecodeError as exc:
        raise ValueError(f"강의실 설정 파일 {path} 의 JSON 형식이 잘못되었습니다: {exc}") from None
    rooms = data.get("rooms") if isinstance(data, dict) else None
    if not isinstance(rooms, dict) or not rooms:
        raise ValueError(f"강의실 설정 파일 {path} 에 \"rooms\" 항목이 없거나 비어 있습니다.")
    return rooms


def load_room(room_name="5420", path=None):
    """
    rooms.json에서 방 하나의 설정을 읽고 검사해서 딕셔너리로 돌려준다.

    반환 키 (mcp_server.py가 쓰는 키와 같다)
      room_name, description, measured, note,
      dimensions_m [가로, 세로, 높이], wall_absorption, forbidden_zones [[x0, y0, x1, y1], ...],
      speaker_height_m, min_wall_distance_m, listening_points [[x, y, z], ...],
      listening_source ("seating" 또는 "listening_points": 청취 지점을 어디서 만들었는지),
      seating (seating이 있을 때만, 원래 적힌 값)

    값이 이상하면 무엇이 잘못됐는지 한국어로 알려 주는 ValueError를 낸다.
    """
    path = path or DEFAULT_ROOMS_PATH
    rooms = load_rooms(path)

    # 1) 방 이름 찾기 ("5420"과 5420 모두 받도록 글자로 바꿔서 찾는다)
    key = str(room_name).strip()
    if key not in rooms:
        names = ", ".join(sorted(rooms))
        raise ValueError(f"'{room_name}' 강의실은 등록되어 있지 않습니다. 등록된 강의실: {names}")
    raw = rooms[key]
    if not isinstance(raw, dict):
        raise ValueError(f"rooms.json의 '{key}' 강의실 설정은 {{...}} 모양이어야 합니다.")
    where = f"rooms.json의 '{key}' 강의실"   # 오류 메시지 앞에 붙일 위치 설명

    # 2) 필수 항목이 다 있는지
    missing = [k for k in REQUIRED_KEYS if k not in raw]
    if "seating" not in raw and "listening_points" not in raw:
        missing.append("seating 또는 listening_points")
    if missing:
        raise ValueError(f"{where} 설정에 다음 항목이 없습니다: {missing}")

    # 3) 방 치수: 세 값 모두 0보다 커야 한다
    dims = _numbers(raw["dimensions_m"], 3, f"{where} 방 치수(dimensions_m)")
    if any(d <= 0 for d in dims):
        raise ValueError(f"{where} 방 치수(dimensions_m)는 모두 0보다 커야 합니다. (받은 값: {dims})")
    width, length, height = dims

    # 4) 벽 흡음률: 0(전부 반사) ~ 1(전부 흡수)
    absorption = _number(raw["wall_absorption"], f"{where} 벽 흡음률(wall_absorption)")
    if not 0 <= absorption <= 1:
        raise ValueError(f"{where} 벽 흡음률(wall_absorption)은 0~1 사이여야 합니다. (받은 값: {absorption})")

    # 5) 스피커 설치 높이: 바닥보다 위, 천장보다 아래
    speaker_h = _number(raw["speaker_height_m"], f"{where} 설치 높이(speaker_height_m)")
    if not 0 < speaker_h < height:
        raise ValueError(
            f"{where} 설치 높이(speaker_height_m) {speaker_h} m가 방 밖입니다. "
            f"(0보다 크고 천장 높이 {height} m보다 작아야 합니다)"
        )

    # 6) 벽과의 최소 거리: 0 이상
    min_wall = _number(raw["min_wall_distance_m"], f"{where} 벽과의 최소 거리(min_wall_distance_m)")
    if min_wall < 0:
        raise ValueError(f"{where} 벽과의 최소 거리(min_wall_distance_m)는 0 이상이어야 합니다. (받은 값: {min_wall})")

    # 7) 설치 금지 구역: [x_min, y_min, x_max, y_max], 방 바닥 안에 있어야 한다 (벽에 붙는 것은 허용)
    zones_raw = raw["forbidden_zones"]
    if not isinstance(zones_raw, list):
        raise ValueError(f"{where} 금지 구역(forbidden_zones)은 [[x_min, y_min, x_max, y_max], ...] 목록이어야 합니다.")
    zones = []
    for i, zone in enumerate(zones_raw):
        x0, y0, x1, y1 = _numbers(zone, 4, f"{where} 금지 구역 {i}번")
        if x0 > x1 or y0 > y1:
            raise ValueError(f"{where} 금지 구역 {i}번 {zone} 은 x_min <= x_max, y_min <= y_max 이어야 합니다.")
        if x0 < 0 or y0 < 0 or x1 > width or y1 > length:
            raise ValueError(
                f"{where} 금지 구역 {i}번 {zone} 이 방 밖으로 나가 있습니다. "
                f"(x는 0~{width}, y는 0~{length} 안이어야 합니다)"
            )
        zones.append([x0, y0, x1, y1])

    # 8) 청취 지점: seating이 있으면 자동 생성, 없으면 listening_points 그대로
    if "seating" in raw:
        seating = raw["seating"]
        if not isinstance(seating, dict):
            raise ValueError(f"{where} seating은 {{...}} 모양이어야 합니다.")
        missing = [k for k in SEATING_KEYS if k not in seating]
        if missing:
            raise ValueError(f"{where} seating 설정에 다음 항목이 없습니다: {missing}")
        try:
            points = make_seat_grid(seating["first_seat_xy_m"], seating["cols"], seating["rows"],
                                    seating["col_spacing_m"], seating["row_spacing_m"],
                                    seating["ear_height_m"])
        except ValueError as exc:
            raise ValueError(f"{where} seating 설정 오류: {exc}") from None
        source = "seating"
        hint = " seating 설정(첫 좌석 위치, 열·행 수, 간격, 귀 높이)을 확인하세요."
    else:
        pts_raw = raw["listening_points"]
        if not isinstance(pts_raw, list):
            raise ValueError(f"{where} listening_points는 [[x, y, z], ...] 목록이어야 합니다.")
        points = [_numbers(p, 3, f"{where} 청취 지점 {i}번") for i, p in enumerate(pts_raw)]
        source = "listening_points"
        hint = ""
    if not points:
        raise ValueError(f"{where} 청취 지점이 하나도 없습니다.")

    # 청취 지점은 방 "안"(벽 위 제외)에 있어야 시뮬레이션할 수 있다
    for i, (x, y, z) in enumerate(points):
        if not (0 < x < width and 0 < y < length and 0 < z < height):
            raise ValueError(
                f"{where} 청취 지점 {i}번 ({x:g}, {y:g}, {z:g}) 이 방 밖에 있습니다. "
                f"(방 크기: {width:g} x {length:g} x {height:g} m, 각 좌표는 0보다 크고 방 크기보다 작아야 합니다)"
                + hint
            )

    # 9) 다른 코드가 쓰기 좋은 모양으로 정리해서 돌려준다
    room = {
        "room_name": key,
        "description": str(raw.get("description", "")),
        "measured": bool(raw.get("measured", False)),
        "note": str(raw.get("note", "")),
        "dimensions_m": dims,
        "wall_absorption": absorption,
        "forbidden_zones": zones,
        "speaker_height_m": speaker_h,
        "min_wall_distance_m": min_wall,
        "listening_points": points,
        "listening_source": source,
    }
    if "seating" in raw:
        room["seating"] = raw["seating"]
    return room
