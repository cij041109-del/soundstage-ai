"""
room_config.py 테스트 (강의실 설정 읽기·검사)

실행 방법:  pytest soundstage/test_room_config.py
"""

import copy
import json

import pytest

import check_room
from candidates import generate_candidates
from evaluate import make_listening_points
from recommend import default_baseline_position, recommend_placement
from room_config import DEFAULT_ROOMS_PATH, load_room, make_seat_grid


def _base_5420():
    """rooms.json에 적힌 5420 원본 설정(딕셔너리)을 복사해서 돌려준다."""
    with open(DEFAULT_ROOMS_PATH, encoding="utf-8") as f:
        return copy.deepcopy(json.load(f)["rooms"]["5420"])


def _write_rooms(tmp_path, rooms):
    """임시 폴더에 rooms.json을 만들고 경로를 돌려준다. (진짜 rooms.json은 건드리지 않는다)"""
    path = tmp_path / "rooms.json"
    path.write_text(json.dumps({"rooms": rooms}, ensure_ascii=False), encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------
# 기본 5420 설정
# ---------------------------------------------------------------------
def test_default_5420_loads():
    room = load_room()
    assert room["room_name"] == "5420"
    assert room["dimensions_m"] == [10.0, 8.0, 3.0]
    assert room["measured"] is False
    assert room["listening_source"] == "seating"


def test_default_seating_matches_demo_basic_12_points():
    """seating으로 만든 청취 지점이 demo_basic의 12개와 순서·값까지 똑같아야 한다."""
    room = load_room("5420")
    expected = [list(p) for p in make_listening_points()]
    assert len(room["listening_points"]) == 12
    assert room["listening_points"] == expected


def test_default_seating_matches_listening_points_in_json():
    """rooms.json에 남아 있는 listening_points와도 같아야 한다. (둘이 어긋나지 않았는지)"""
    raw = _base_5420()
    assert load_room("5420")["listening_points"] == raw["listening_points"]


def test_make_seat_grid_order():
    pts = make_seat_grid([1.0, 2.0], cols=2, rows=2, col_spacing=0.5, row_spacing=1.0, ear_height=1.1)
    # 앞줄 왼쪽 → 앞줄 오른쪽 → 둘째 줄 왼쪽 → 둘째 줄 오른쪽
    assert pts == [[1.0, 2.0, 1.1], [1.5, 2.0, 1.1], [1.0, 3.0, 1.1], [1.5, 3.0, 1.1]]


@pytest.mark.parametrize("kwargs, msg", [
    ({"cols": 0}, "열 개수"),
    ({"rows": 2.5}, "행 개수"),
    ({"col_spacing": 0.0}, "열 간격"),
    ({"row_spacing": -1.0}, "행 간격"),
])
def test_make_seat_grid_bad_values(kwargs, msg):
    args = dict(first_seat_xy=[1.0, 2.0], cols=2, rows=2, col_spacing=1.0, row_spacing=1.0,
                ear_height=1.2)
    args.update(kwargs)
    with pytest.raises(ValueError, match=msg):
        make_seat_grid(**args)


# ---------------------------------------------------------------------
# seating 없이 listening_points만 있는 경우
# ---------------------------------------------------------------------
def test_listening_points_only(tmp_path):
    raw = _base_5420()
    del raw["seating"]
    raw["listening_points"] = [[2.0, 3.0, 1.2], [8.0, 6.0, 1.2]]
    room = load_room("5420", _write_rooms(tmp_path, {"5420": raw}))
    assert room["listening_source"] == "listening_points"
    assert room["listening_points"] == [[2.0, 3.0, 1.2], [8.0, 6.0, 1.2]]
    assert "seating" not in room


# ---------------------------------------------------------------------
# 잘못된 설정 → 한국어 ValueError
# ---------------------------------------------------------------------
def test_unknown_room_name():
    with pytest.raises(ValueError, match="등록되어 있지 않습니다"):
        load_room("9999")


def test_seat_outside_room(tmp_path):
    raw = _base_5420()
    raw["seating"]["rows"] = 5          # 다섯째 줄 y = 2 + 4 x 1.667 = 8.67 m → 세로 8 m 방 밖
    with pytest.raises(ValueError, match="방 밖"):
        load_room("5420", _write_rooms(tmp_path, {"5420": raw}))


def test_listening_point_outside_room(tmp_path):
    raw = _base_5420()
    del raw["seating"]
    raw["listening_points"] = [[5.0, 4.0, 3.5]]   # 천장(3 m)보다 높다
    with pytest.raises(ValueError, match="방 밖"):
        load_room("5420", _write_rooms(tmp_path, {"5420": raw}))


def test_forbidden_zone_outside_room(tmp_path):
    raw = _base_5420()
    raw["forbidden_zones"] = [[8.0, 0.0, 12.0, 2.0]]   # 가로 10 m 방을 넘는다
    with pytest.raises(ValueError, match="금지 구역 0번.*방 밖"):
        load_room("5420", _write_rooms(tmp_path, {"5420": raw}))


def test_speaker_height_outside_room(tmp_path):
    raw = _base_5420()
    raw["speaker_height_m"] = 3.0      # 천장 높이와 같으면 방 "안"이 아니다
    with pytest.raises(ValueError, match="설치 높이"):
        load_room("5420", _write_rooms(tmp_path, {"5420": raw}))


@pytest.mark.parametrize("dims", [[0.0, 8.0, 3.0], [10.0, -8.0, 3.0]])
def test_non_positive_dimensions(tmp_path, dims):
    raw = _base_5420()
    raw["dimensions_m"] = dims
    with pytest.raises(ValueError, match="0보다 커야"):
        load_room("5420", _write_rooms(tmp_path, {"5420": raw}))


@pytest.mark.parametrize("key", ["dimensions_m", "wall_absorption", "forbidden_zones",
                                 "speaker_height_m", "min_wall_distance_m"])
def test_missing_required_key(tmp_path, key):
    raw = _base_5420()
    del raw[key]
    with pytest.raises(ValueError, match="항목이 없습니다"):
        load_room("5420", _write_rooms(tmp_path, {"5420": raw}))


def test_missing_both_seating_and_points(tmp_path):
    raw = _base_5420()
    del raw["seating"], raw["listening_points"]
    with pytest.raises(ValueError, match="seating 또는 listening_points"):
        load_room("5420", _write_rooms(tmp_path, {"5420": raw}))


def test_missing_seating_key(tmp_path):
    raw = _base_5420()
    del raw["seating"]["ear_height_m"]
    with pytest.raises(ValueError, match="ear_height_m"):
        load_room("5420", _write_rooms(tmp_path, {"5420": raw}))


def test_missing_file(tmp_path):
    with pytest.raises(ValueError, match="찾을 수 없습니다"):
        load_room("5420", str(tmp_path / "없는파일.json"))


# ---------------------------------------------------------------------
# 치수를 바꾼 방으로 끝까지 동작하는지 (실측값을 넣었을 때를 흉내 냄)
# ---------------------------------------------------------------------
@pytest.fixture
def small_room_path(tmp_path):
    raw = _base_5420()
    raw["dimensions_m"] = [7.0, 6.0, 2.8]
    raw["forbidden_zones"] = [[2.5, 0.0, 4.5, 1.5]]
    raw["speaker_height_m"] = 2.4
    raw["seating"] = {"first_seat_xy_m": [1.0, 2.0], "cols": 3, "rows": 3,
                      "col_spacing_m": 2.5, "row_spacing_m": 1.5, "ear_height_m": 1.1}
    del raw["listening_points"]
    return _write_rooms(tmp_path, {"5420": raw})


def test_changed_room_runs_to_recommendation(small_room_path):
    room = load_room("5420", small_room_path)
    assert room["dimensions_m"] == [7.0, 6.0, 2.8]
    assert len(room["listening_points"]) == 9
    assert room["listening_points"][-1] == [6.0, 5.0, 1.1]

    dims = room["dimensions_m"]
    cands = generate_candidates(dims, 1.0, room["min_wall_distance_m"], room["speaker_height_m"],
                                forbidden_zones=room["forbidden_zones"])
    default_room = load_room("5420")
    default_cands = generate_candidates(default_room["dimensions_m"], 1.0,
                                        default_room["min_wall_distance_m"],
                                        default_room["speaker_height_m"],
                                        forbidden_zones=default_room["forbidden_zones"])
    assert len(default_cands) == 76
    assert len(cands) != len(default_cands)      # 치수가 바뀌면 후보 수도 바뀐다
    assert all(c[2] == 2.4 for c in cands)

    rec = recommend_placement(dims, cands, room["listening_points"],
                              baseline_pos=default_baseline_position(dims, cands),
                              absorption=room["wall_absorption"], top_n=3)
    assert rec["num_candidates"] == len(cands)
    assert tuple(rec["best"]["position"]) in {tuple(c) for c in cands}
    assert rec["baseline"]["position"] == (3.5, 0.5, 2.4)


def test_check_room_script_runs(small_room_path, capsys):
    assert check_room.main(["5420", "--path", small_room_path]) == 0
    out = capsys.readouterr().out
    assert "아직 임시값입니다" in out
    assert "추천 위치" in out and "개선율" in out


def test_check_room_script_reports_error(tmp_path, capsys):
    raw = _base_5420()
    raw["dimensions_m"] = [0.0, 8.0, 3.0]
    assert check_room.main(["5420", "--path", _write_rooms(tmp_path, {"5420": raw})]) == 1
    assert "[설정 오류]" in capsys.readouterr().out
