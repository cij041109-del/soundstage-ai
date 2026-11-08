"""
field.py 테스트 (이슈 9). 격자 간격을 크게 줘서 빨리 끝나게 했다.

실행 방법:  pytest soundstage/test_field.py
"""

import json

import numpy as np
import pytest

import blender_scene
from evaluate import evaluate_position
from export_scene import build_field_dict, build_scene_dict
from field import compare_sampling, evaluate_field, listening_zone, make_dense_grid, zone_stats
from room_config import load_room

DIMS = (10.0, 8.0, 3.0)
ZONE = (1.0, 2.0, 9.0, 7.0)


# ---------------------------------------------------------------------
# make_dense_grid
# ---------------------------------------------------------------------
def test_grid_points_inside_room():
    xs, ys, pts = make_dense_grid(DIMS, step=1.0, margin=0.25)
    assert len(pts) == len(xs) * len(ys)
    for x, y, z in pts:
        assert 0 < x < DIMS[0] and 0 < y < DIMS[1] and z == 1.2


def test_grid_points_inside_zone_and_include_corners():
    xs, ys, pts = make_dense_grid(DIMS, step=1.0, zone=ZONE)
    for x, y, _ in pts:
        assert ZONE[0] <= x <= ZONE[2] and ZONE[1] <= y <= ZONE[3]
    # 실수 오차로 끝점이 빠지지 않아야 한다
    assert xs[0] == 1.0 and xs[-1] == 9.0 and ys[0] == 2.0 and ys[-1] == 7.0


def test_smaller_step_gives_more_points():
    counts = [len(make_dense_grid(DIMS, step=s, zone=ZONE)[2]) for s in (2.0, 1.0, 0.5)]
    assert counts[0] < counts[1] < counts[2]


def test_grid_rejects_bad_input():
    with pytest.raises(ValueError):
        make_dense_grid(DIMS, step=0)
    with pytest.raises(ValueError):
        make_dense_grid(DIMS, step=1.0, zone=(0.0, 2.0, 9.0, 7.0))   # 벽 위(x=0)는 안 됨


# ---------------------------------------------------------------------
# evaluate_field
# ---------------------------------------------------------------------
def test_evaluate_field_shape():
    xs, ys, _ = make_dense_grid(DIMS, step=2.0, zone=ZONE)
    levels = evaluate_field(DIMS, (5.0, 0.5, 2.5), xs, ys)
    assert levels.shape == (len(ys), len(xs))
    assert np.all(np.isfinite(levels))


def test_evaluate_field_matches_12_seats():
    # 좌석 12곳 좌표 자체를 격자로 주면, evaluate_position(12곳)과 같은 값이 나와야 한다
    room = load_room("5420")
    seats = room["listening_points"]
    xs = sorted({p[0] for p in seats})
    ys = sorted({p[1] for p in seats})
    speaker = (3.5, 4.5, 2.5)
    grid = evaluate_field(DIMS, speaker, xs, ys, absorption=room["wall_absorption"])
    direct = evaluate_position(DIMS, speaker, seats, absorption=room["wall_absorption"])["levels_db"]
    for (x, y, _), db in zip(seats, direct):
        assert grid[ys.index(y), xs.index(x)] == pytest.approx(db, abs=1e-9)


# ---------------------------------------------------------------------
# zone_stats
# ---------------------------------------------------------------------
def test_zone_stats_matches_manual():
    xs = np.array([0.5, 1.0, 2.0, 3.0, 4.0])
    ys = np.array([1.0, 2.0, 3.0])
    rng = np.random.default_rng(0)
    levels = rng.normal(-5, 2, size=(len(ys), len(xs)))
    st = zone_stats(levels, xs, ys, (1.0, 2.0, 3.0, 3.0))   # x 1~3, y 2~3 → 열 1..3, 행 1..2
    inside = levels[1:3, 1:4]
    assert st["num_points"] == 6
    assert st["std_db"] == pytest.approx(np.std(inside))
    assert st["mean_db"] == pytest.approx(np.mean(inside))
    assert st["min_db"] == pytest.approx(np.min(inside))


def test_listening_zone_of_default_room():
    assert listening_zone(load_room("5420")["listening_points"]) == pytest.approx(ZONE)


# ---------------------------------------------------------------------
# compare_sampling (작은 격자 + 후보 4개만)
# ---------------------------------------------------------------------
def test_compare_sampling_returns_needed_items():
    cands = [(3.5, 4.5, 2.5), (4.5, 4.5, 2.5), (1.5, 6.5, 2.5), (8.5, 1.5, 2.5)]
    cmp = compare_sampling("5420", top_n=3, step=2.0, candidates=cands,
                           margin_db=100.0)   # 조건을 넉넉히 줘서 반드시 통과 후보가 있게
    for key in ("seats", "grid", "cross", "spearman", "table", "zone", "num_grid_points"):
        assert key in cmp
    for which in ("seats", "grid"):
        for key in ("baseline_std_db", "best_position", "best_std_db", "improvement_percent"):
            assert key in cmp[which]
    assert cmp["num_seats"] == 12
    assert cmp["num_grid_points"] == len(make_dense_grid(DIMS, step=2.0, zone=ZONE)[2])
    assert -1.0 <= cmp["spearman"] <= 1.0
    assert 1 <= len(cmp["table"]) <= 6
    # 12곳 방식의 추천 위치를 격자로 다시 잰 값은 격자 결과 안의 같은 후보 값과 같아야 한다
    grid_by_pos = {tuple(r["position"]): r["std_db"] for r in cmp["grid_result"]["results"]}
    assert cmp["cross"]["std_db"] == pytest.approx(grid_by_pos[cmp["cross"]["position"]])


# ---------------------------------------------------------------------
# scene.json의 field 항목과 Blender 쪽 순수 함수
# ---------------------------------------------------------------------
def _fake_rec():
    return {"baseline": {"position": (5.0, 0.5, 2.5), "levels_db": [-5.0] * 12, "std_db": 1.0, "min_db": -5.0},
            "best": {"position": (3.5, 4.5, 2.5), "levels_db": [-4.0] * 12, "std_db": 0.5, "min_db": -4.0},
            "improvement_percent": 50.0}


def test_scene_field_is_json_and_has_shape():
    room = load_room("5420")
    rec = _fake_rec()
    field = build_field_dict(room, rec, step=2.0)
    scene = build_scene_dict(room, rec, field=field)
    f = json.loads(json.dumps(scene))["field"]
    for key in ("xs", "ys", "height", "baseline_levels", "recommended_levels", "vmin", "vmax"):
        assert key in f
    assert len(f["baseline_levels"]) == len(f["ys"])
    assert all(len(row) == len(f["xs"]) for row in f["recommended_levels"])
    assert f["vmin"] < f["vmax"]
    assert "field" not in build_scene_dict(room, rec)        # 안 주면 예전과 같다


def test_blender_field_helpers_without_bpy():
    assert blender_scene.turbo(0.0) == pytest.approx(blender_scene.TURBO_STOPS[0][1])
    assert blender_scene.turbo(1.0) == pytest.approx(blender_scene.TURBO_STOPS[-1][1])
    assert blender_scene.surface_z(-10, -10, 0) == pytest.approx(1.0)
    assert blender_scene.surface_z(0, -10, 0) == pytest.approx(2.2)
    verts, faces, colors = blender_scene.field_mesh_data([0, 1, 2], [0, 1], [[-10, -5, 0], [-10, -5, 0]], -10, 0)
    assert len(verts) == 6 and len(colors) == 6 and len(faces) == 2
    assert blender_scene.parse_options(["b", "--", "a.json", "out", "--no-spheres"]) == {"show_spheres": False}
    assert blender_scene.parse_options(["b", "--", "a.json", "out"]) == {"show_spheres": True}
