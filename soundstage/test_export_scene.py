"""
export_scene.py 테스트 (Blender 없이 돌아간다)

실행 방법:  pytest soundstage/test_export_scene.py
"""

import json
import os

import blender_scene
import export_scene
from export_scene import PLACEMENT_KEYS, SCENE_KEYS, build_scene_dict, find_blender, save_scene_json
from recommend import recommend_placement
from room_config import load_room


def _fake_rec(n_points):
    """시뮬레이션 없이 recommend_placement() 결과와 같은 모양의 가짜 결과를 만든다. (빠른 테스트용)"""
    base = {"position": (5.0, 0.5, 2.5), "levels_db": [-10.0 - i for i in range(n_points)],
            "std_db": 3.0, "min_db": -10.0 - (n_points - 1), "mean_db": -15.0}
    best = {"position": (2.0, 4.0, 2.5), "levels_db": [-12.0 - 0.1 * i for i in range(n_points)],
            "std_db": 1.0, "min_db": -12.0 - 0.1 * (n_points - 1), "mean_db": -12.5}
    return {"baseline": base, "best": best, "improvement_percent": 66.7}


def test_build_scene_dict_has_all_keys_and_is_json():
    room = load_room("5420")
    scene = build_scene_dict(room, _fake_rec(len(room["listening_points"])))
    for key in SCENE_KEYS:
        assert key in scene
    for which in ("baseline", "recommended"):
        for key in PLACEMENT_KEYS:
            assert key in scene[which]
    assert scene["room_name"] == "5420"
    assert scene["measured"] is False
    json.dumps(scene, ensure_ascii=False)   # 오류 없이 JSON 글자로 바뀌어야 한다


def test_levels_length_matches_points_with_real_recommendation():
    # 실제 시뮬레이션으로 확인 (후보 3개만 써서 빠르게)
    room = load_room("5420")
    dims = tuple(room["dimensions_m"])
    listeners = [tuple(p) for p in room["listening_points"]]
    cands = [(1.0, 1.0, 2.5), (2.0, 4.0, 2.5), (8.0, 6.0, 2.5)]
    rec = recommend_placement(dims, cands, listeners, absorption=room["wall_absorption"],
                              margin_db=100.0)   # 조건을 넉넉히 줘서 반드시 하나는 통과
    scene = build_scene_dict(room, rec)
    n = len(scene["listening_points"])
    assert n == 12
    assert len(scene["baseline"]["levels_db"]) == n
    assert len(scene["recommended"]["levels_db"]) == n
    json.dumps(scene)


def test_build_scene_dict_rejects_length_mismatch():
    room = load_room("5420")
    rec = _fake_rec(len(room["listening_points"]) - 1)
    try:
        build_scene_dict(room, rec)
    except ValueError:
        pass
    else:
        raise AssertionError("dB 개수가 다르면 ValueError가 나야 합니다")


def test_save_scene_json_creates_file(tmp_path):
    room = load_room("5420")
    scene = build_scene_dict(room, _fake_rec(len(room["listening_points"])))
    path = tmp_path / "sub" / "scene.json"      # 없는 폴더도 만들어야 한다
    save_scene_json(scene, str(path))
    assert path.is_file()
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded == scene


def test_find_blender_returns_none_or_existing_path():
    result = find_blender()
    assert result is None or os.path.isfile(result)


def test_find_blender_with_fake_env_path(monkeypatch, tmp_path):
    monkeypatch.setenv("BLENDER_PATH", str(tmp_path / "no_such_blender.exe"))
    result = find_blender()           # 오류 없이 다음 방법으로 넘어가야 한다
    assert result is None or os.path.isfile(result)


def test_find_blender_without_any_blender(monkeypatch, tmp_path):
    # Blender가 전혀 없는 컴퓨터를 흉내 낸다 → None
    monkeypatch.setenv("BLENDER_PATH", str(tmp_path / "missing.exe"))
    monkeypatch.setattr(export_scene.shutil, "which", lambda name: None)
    monkeypatch.setattr(export_scene, "WINDOWS_BLENDER_GLOB", str(tmp_path / "none" / "blender.exe"))
    assert find_blender() is None


def test_find_blender_uses_env_path(monkeypatch, tmp_path):
    fake = tmp_path / "blender.exe"
    fake.write_text("")
    monkeypatch.setenv("BLENDER_PATH", str(fake))
    assert find_blender() == str(fake)
    monkeypatch.setenv("BLENDER_PATH", str(tmp_path))     # 폴더를 줘도 찾는다
    assert find_blender() == str(fake)


def test_blender_scene_helpers_without_bpy():
    # blender_scene.py는 bpy 없이 import 되고, 순수 함수는 바로 쓸 수 있어야 한다
    assert blender_scene.parse_args(["blender", "--", "a.json", "out"]) == ("a.json", "out")
    assert blender_scene.viridis(0.0) == blender_scene.VIRIDIS_STOPS[0][1]
    assert blender_scene.viridis(1.0) == blender_scene.VIRIDIS_STOPS[-1][1]
    scene = {"baseline": {"levels_db": [-20.0, -10.0]}, "recommended": {"levels_db": [-15.0, -5.0]}}
    assert blender_scene.color_range(scene) == (-20.0, -5.0)
