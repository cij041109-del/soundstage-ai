"""
soundstage 이슈 8 (1단계): 계산 결과를 Blender용 JSON으로 내보내기

Blender는 자기만의 파이썬을 따로 가지고 있어서, 우리 .venv에 설치한 pyroomacoustics를 쓸 수 없다.
그래서 일을 두 단계로 나눈다.
  1) (이 파일, .venv 파이썬) 시뮬레이션으로 추천 배치를 계산하고 결과를 scene.json으로 저장한다.
  2) (blender_scene.py, Blender 파이썬) scene.json을 읽어 3D 장면을 만들고 그림을 렌더링한다.

실행 방법:  python soundstage/export_scene.py
  → soundstage/output/scene.json 저장
  → Blender를 찾으면 baseline.png, recommended.png, scene.blend 까지 만든다.

Blender 위치를 직접 알려 주고 싶으면 환경변수 BLENDER_PATH에 blender.exe 경로를 넣는다.
  PowerShell 예:  $env:BLENDER_PATH = "C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe"
"""

import glob
import json
import os
import re
import shutil
import subprocess
import sys

# 어느 폴더에서 실행하든 같은 폴더의 recommend.py 등을 import할 수 있게 한다
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# 결과 파일을 모아 둘 폴더와 Blender 안에서 실행할 스크립트 경로
OUTPUT_DIR = os.path.join(HERE, "output")
BLENDER_SCRIPT = os.path.join(HERE, "blender_scene.py")

# Windows에서 Blender를 기본 설치하면 생기는 위치 (버전마다 폴더 이름이 다르므로 * 사용)
WINDOWS_BLENDER_GLOB = r"C:\Program Files\Blender Foundation\Blender *\blender.exe"

# scene.json에 반드시 들어가는 항목 (테스트에서도 이 목록으로 확인한다)
SCENE_KEYS = ("room_name", "description", "measured", "dimensions_m", "forbidden_zones",
              "listening_points", "baseline", "recommended", "improvement_percent")
PLACEMENT_KEYS = ("position", "levels_db", "std_db", "min_db")


# ---------------------------------------------------------------------
# 1) 장면 딕셔너리 만들기
# ---------------------------------------------------------------------
def _floats(values):
    """숫자 목록을 순수 파이썬 float 리스트로 바꾼다. (numpy 값은 json으로 저장이 안 될 수 있어서)"""
    return [float(v) for v in values]


def _placement(result):
    """평가 딕셔너리 하나에서 Blender가 쓸 값(위치, 지점별 dB, 표준편차, 최솟값)만 골라낸다."""
    return {
        "position": _floats(result["position"]),
        "levels_db": _floats(result["levels_db"]),
        "std_db": float(result["std_db"]),
        "min_db": float(result["min_db"]),
    }


def build_scene_dict(room, rec_result):
    """
    방 설정과 추천 결과를 Blender가 읽을 딕셔너리 하나로 묶는다.

    매개변수
    --------
    room : room_config.load_room()이 돌려준 방 설정 딕셔너리
    rec_result : recommend.recommend_placement()가 돌려준 결과 딕셔너리
                 (rec_result["baseline"] = 기준 배치, rec_result["best"] = 추천 배치)

    반환값: json.dumps로 바로 저장할 수 있는 순수 파이썬 값(dict, list, float, str, bool)만 든 딕셔너리
    """
    points = [_floats(p) for p in room["listening_points"]]
    baseline = _placement(rec_result["baseline"])
    recommended = _placement(rec_result["best"])

    # 지점별 dB 개수가 청취 지점 개수와 다르면 색을 칠할 수 없으므로 미리 막는다
    for name, placement in (("기준 배치", baseline), ("추천 배치", recommended)):
        if len(placement["levels_db"]) != len(points):
            raise ValueError(
                f"{name}의 지점별 dB 개수({len(placement['levels_db'])})가 "
                f"청취 지점 개수({len(points)})와 다릅니다."
            )

    return {
        "room_name": str(room["room_name"]),
        "description": str(room.get("description", "")),
        "measured": bool(room.get("measured", False)),     # False면 실측 전 임시값이라는 뜻
        "dimensions_m": _floats(room["dimensions_m"]),     # [가로 x, 세로 y, 높이 z]
        "forbidden_zones": [_floats(z) for z in room["forbidden_zones"]],  # [[x0, y0, x1, y1], ...]
        "listening_points": points,                        # [[x, y, z], ...]
        "baseline": baseline,
        "recommended": recommended,
        "improvement_percent": float(rec_result["improvement_percent"]),
    }


def save_scene_json(scene, path):
    """장면 딕셔너리를 UTF-8 JSON 파일로 저장하고 저장한 경로를 돌려준다. (폴더가 없으면 만든다)"""
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        # ensure_ascii=False: 한글을 \uXXXX가 아닌 글자 그대로 저장한다
        json.dump(scene, f, ensure_ascii=False, indent=2)
    return path


# ---------------------------------------------------------------------
# 2) Blender 프로그램 찾기
# ---------------------------------------------------------------------
def _version_key(path):
    """'Blender 5.2' 같은 폴더 이름에서 숫자를 뽑아 정렬용 값으로 쓴다. (높은 버전을 먼저 고르려고)"""
    folder = os.path.basename(os.path.dirname(path))
    return [int(n) for n in re.findall(r"\d+", folder)]


def find_blender():
    """
    Blender 실행 파일 경로를 찾아 돌려준다. 못 찾으면 None.

    찾는 순서
      1) 환경변수 BLENDER_PATH (blender.exe 파일 경로 또는 그 파일이 든 폴더)
      2) PATH에 등록된 blender 명령
      3) C:\\Program Files\\Blender Foundation\\Blender *\\blender.exe (여러 개면 가장 높은 버전)
    BLENDER_PATH가 잘못된 경로면 경고만 출력하고 다음 방법으로 계속 찾는다.
    """
    # 1) 환경변수
    env_path = os.environ.get("BLENDER_PATH", "").strip().strip('"')
    if env_path:
        if os.path.isfile(env_path):
            return env_path
        for name in ("blender.exe", "blender"):
            inside = os.path.join(env_path, name)
            if os.path.isdir(env_path) and os.path.isfile(inside):
                return inside
        print(f"[경고] 환경변수 BLENDER_PATH의 경로에 Blender가 없습니다: {env_path}", file=sys.stderr)

    # 2) PATH
    on_path = shutil.which("blender")
    if on_path:
        return on_path

    # 3) Windows 기본 설치 위치
    found = sorted(glob.glob(WINDOWS_BLENDER_GLOB), key=_version_key, reverse=True)
    return found[0] if found else None


def run_blender(blender, scene_path, out_dir):
    """
    Blender를 화면 없이(--background) 실행해서 blender_scene.py로 그림을 만든다.

    --python-exit-code 1 : 스크립트에서 오류가 나면 Blender가 실패 코드(1)로 끝나게 한다
    "--" 뒤의 인자는 Blender가 무시하고 blender_scene.py가 sys.argv에서 읽는다
    반환값: Blender의 종료 코드 (0이면 성공)
    """
    cmd = [blender, "--background", "--python-exit-code", "1",
           "--python", BLENDER_SCRIPT, "--", scene_path, out_dir]
    print("Blender 실행:", subprocess.list2cmdline(cmd))
    # Blender가 출력하는 글자(한글 포함)를 UTF-8로 받아서 그대로 보여 준다
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.stdout:
        print(proc.stdout)
    if proc.returncode != 0:
        print("[오류] Blender 실행이 실패했습니다. (종료 코드 %d)" % proc.returncode)
        if proc.stderr:
            print(proc.stderr)
    return proc.returncode


# 이 파일을 직접 실행했을 때만 아래가 실행된다
if __name__ == "__main__":
    import time

    from candidates import DEFAULT_STEP, generate_candidates
    from recommend import recommend_placement
    from room_config import load_room

    # 한글 출력이 깨지거나 오류가 나지 않도록 (Windows 콘솔/파이프 대비)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    # 1) 기본 방(5420) 설정으로 추천 배치 계산
    room = load_room("5420")
    dims = tuple(room["dimensions_m"])
    zones = [tuple(z) for z in room["forbidden_zones"]]
    cands = generate_candidates(dims, DEFAULT_STEP, room["min_wall_distance_m"],
                                room["speaker_height_m"], forbidden_zones=zones)
    listeners = [tuple(p) for p in room["listening_points"]]

    print(f"{room['room_name']} 강의실: 후보 {len(cands)}개 평가 중...")
    start = time.perf_counter()
    rec = recommend_placement(dims, cands, listeners, absorption=room["wall_absorption"])
    print(f"계산 완료 ({time.perf_counter() - start:.1f}초)")

    # 2) scene.json 저장
    scene = build_scene_dict(room, rec)
    scene_path = save_scene_json(scene, os.path.join(OUTPUT_DIR, "scene.json"))
    print(f"장면 데이터 저장: {scene_path}")
    print(f"  기준 배치 {scene['baseline']['position']}  std {scene['baseline']['std_db']:.2f} dB")
    print(f"  추천 배치 {scene['recommended']['position']}  std {scene['recommended']['std_db']:.2f} dB")
    print(f"  개선율 {scene['improvement_percent']:.1f} %")

    # 3) Blender로 렌더링
    blender = find_blender()
    if blender is None:
        print()
        print("Blender를 찾지 못해서 3D 그림은 만들지 않았습니다. (scene.json은 저장됨)")
        print("  1) https://www.blender.org/download/ 에서 Blender를 설치하거나")
        print("  2) 이미 설치했다면 환경변수 BLENDER_PATH에 blender.exe 경로를 넣은 뒤 다시 실행하세요.")
        print('     PowerShell 예: $env:BLENDER_PATH = "C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe"')
        sys.exit(0)

    sys.exit(run_blender(blender, scene_path, OUTPUT_DIR))
