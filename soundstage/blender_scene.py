"""
soundstage 이슈 8 (2단계): Blender 안에서 3D 장면을 만들고 그림으로 렌더링한다

이 파일은 우리 .venv 파이썬이 아니라 "Blender의 파이썬"에서 실행된다.
보통은 export_scene.py가 아래 명령으로 대신 실행해 준다.

  blender --background --python soundstage/blender_scene.py -- <scene.json 경로> <출력 폴더>

  --background : 창을 띄우지 않고 실행
  "--" 뒤      : Blender는 무시하고, 이 스크립트가 sys.argv에서 직접 읽는 인자

만드는 파일 (출력 폴더 안)
  baseline.png    : 기준 배치(지금 스피커 자리) 장면
  recommended.png : 추천 배치 장면
  scene.blend     : 두 장면을 함께 담은 Blender 파일
                    오른쪽 위 Outliner에서 "Baseline"/"Recommended" 컬렉션의 눈 아이콘으로 켜고 끈다

좌표는 scene.json 값을 그대로 쓴다. (단위 m)
  x = 가로(왼쪽 벽 → 오른쪽), y = 앞벽(칠판, y=0) → 뒤쪽, z = 높이

bpy(Blender 파이썬 모듈)는 Blender 안에서만 있으므로 함수 안에서 import 한다.
그래서 pytest가 이 파일을 import 해도(parse_args 등을 시험할 때) 오류가 나지 않는다.
"""

import json
import math
import os
import sys

# ---------------------------------------------------------------------
# 설정값 (모양·색을 바꾸고 싶으면 여기만 고치면 된다)
# ---------------------------------------------------------------------
RESOLUTION = (1600, 900)          # 렌더 해상도 (가로, 세로) [픽셀]
SPHERE_RADIUS = 0.25              # 청취 지점 구의 반지름 [m]
LABEL_SIZE = 0.32                 # 청취 지점 위 dB 글자 크기 [m]
FORBIDDEN_HEIGHT = 0.9            # 금지 구역 상자 높이 [m] (교탁 정도 높이)
EDGE_RADIUS = 0.025               # 방 모서리 선(얇은 원기둥) 반지름 [m]
SPEAKER_SIZE = (0.4, 0.3, 0.45)   # 스피커 상자 크기 (가로, 깊이, 높이) [m]
# 앞벽 위 간판 글자 줄들의 높이 (천장 높이 + 이 값) [m]: 앞(칠판), 제목, 설명, 색 범례, 방 이름
SIGN_LINES = (2.55, 2.0, 1.55, 1.05, 0.6)

# 한글 글꼴 (Windows 기본 "맑은 고딕"). 없으면 글자를 영어로 바꿔 쓴다.
KOREAN_FONTS = (r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\malgunbd.ttf")

# 색 (sRGB, 0~1). Blender 안에서는 선형 색으로 바꿔서 넣는다.
COLOR_FLOOR = (0.93, 0.93, 0.93)
COLOR_FRONT_WALL = (0.72, 0.84, 0.95)    # 앞벽(칠판 쪽)은 연한 하늘색
COLOR_EDGE = (0.35, 0.35, 0.40)
COLOR_FORBIDDEN = (0.45, 0.45, 0.45)
COLOR_TEXT = (0.08, 0.08, 0.10)
COLOR_SPEAKER = {"baseline": (0.90, 0.12, 0.12),       # 기준 = 빨강
                 "recommended": (0.10, 0.80, 0.20)}    # 추천 = 초록
COLOR_BACKGROUND = (0.97, 0.97, 0.98)

# viridis 색표를 흉내 내는 기준 색 5개 (0=보라: 작게 들림 → 1=노랑: 크게 들림)
# matplotlib 없이 이 점들 사이를 직선으로 섞어서(선형 보간) 색을 만든다.
VIRIDIS_STOPS = (
    (0.00, (0.267, 0.005, 0.329)),
    (0.25, (0.229, 0.322, 0.546)),
    (0.50, (0.128, 0.567, 0.551)),
    (0.75, (0.369, 0.789, 0.383)),
    (1.00, (0.993, 0.906, 0.144)),
)

# 화면에 쓸 글자 (한글 글꼴이 있으면 "ko", 없으면 "en")
TEXTS = {
    "ko": {
        "front": "앞(칠판)",
        "forbidden": "설치 금지",
        "baseline": "기준 배치",
        "recommended": "추천 배치",
        "title": "{label}  위치 ({x:.1f}, {y:.1f}, {z:.1f}) m   균일도 std {std:.2f} dB   최소 {mn:.1f} dB",
        "improve": "추천 배치는 기준보다 균일도 {p:.1f}% 개선",
        "current": "지금 스피커 자리 (전면 중앙 상단)",
        "legend": "구 색: {vmin:.1f} dB(보라, 작게 들림) ~ {vmax:.1f} dB(노랑, 크게 들림)",
        "room": "{name} 강의실",
        "temp": "  (실측 전 임시 치수)",
    },
    "en": {
        "front": "FRONT (board)",
        "forbidden": "No install",
        "baseline": "Baseline",
        "recommended": "Recommended",
        "title": "{label}  pos ({x:.1f}, {y:.1f}, {z:.1f}) m   std {std:.2f} dB   min {mn:.1f} dB",
        "improve": "Recommended is {p:.1f}% more uniform than baseline",
        "current": "Current speaker position (front center, high)",
        "legend": "Sphere color: {vmin:.1f} dB (purple, quiet) ~ {vmax:.1f} dB (yellow, loud)",
        "room": "Room {name}",
        "temp": "  (temporary dimensions)",
    },
}


# ---------------------------------------------------------------------
# bpy 없이도 쓸 수 있는 순수 함수들 (pytest로 시험 가능)
# ---------------------------------------------------------------------
def parse_args(argv):
    """
    sys.argv에서 "--" 뒤의 인자 2개(scene.json 경로, 출력 폴더)를 꺼낸다.
    예: ["blender", "--background", ..., "--", "scene.json", "out"] → ("scene.json", "out")
    """
    if "--" not in argv:
        raise SystemExit('사용법: blender --background --python blender_scene.py -- <scene.json> <출력 폴더>')
    rest = argv[argv.index("--") + 1:]
    if len(rest) < 2:
        raise SystemExit(f'"--" 뒤에 scene.json 경로와 출력 폴더 2개가 필요합니다. (받은 값: {rest})')
    return rest[0], rest[1]


def srgb_to_linear(c):
    """화면용 sRGB 색 값(0~1)을 Blender 내부용 선형 값으로 바꾼다. (안 바꾸면 색이 하얗게 떠 보인다)"""
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def viridis(t):
    """0~1 사이 값 t를 viridis 비슷한 sRGB 색 (r, g, b)로 바꾼다."""
    t = min(max(float(t), 0.0), 1.0)
    for (t0, c0), (t1, c1) in zip(VIRIDIS_STOPS, VIRIDIS_STOPS[1:]):
        if t <= t1:
            w = (t - t0) / (t1 - t0)          # 두 기준점 사이에서 어디쯤인지 (0~1)
            return tuple(a + (b - a) * w for a, b in zip(c0, c1))
    return VIRIDIS_STOPS[-1][1]


def color_range(scene):
    """기준·추천 배치의 dB 값을 모두 모아 같은 색 범위(vmin, vmax)를 정한다. (두 그림 색을 공정하게 비교하려고)"""
    values = scene["baseline"]["levels_db"] + scene["recommended"]["levels_db"]
    vmin, vmax = min(values), max(values)
    if vmax - vmin < 1e-9:      # 모든 값이 같으면 0으로 나누지 않도록 범위를 살짝 넓힌다
        vmin, vmax = vmin - 0.5, vmax + 0.5
    return vmin, vmax


# ---------------------------------------------------------------------
# 여기부터는 Blender 안에서만 동작하는 함수들
# ---------------------------------------------------------------------
def _material(name, rgb, alpha=1.0):
    """
    단색 재질을 만든다.
    - diffuse_color : Workbench 렌더러와 뷰포트가 쓰는 색
    - Principled BSDF : Eevee/Cycles 렌더러가 쓰는 색 (scene.blend를 열어 렌더할 때 대비)
    """
    import bpy
    lin = tuple(srgb_to_linear(c) for c in rgb)
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*lin, alpha)
    try:
        mat.use_nodes = True        # Blender 5부터는 항상 노드를 쓰므로 이 줄이 필요 없거나 경고만 난다
    except Exception:
        pass
    bsdf = mat.node_tree.nodes.get("Principled BSDF") if mat.node_tree else None
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (*lin, 1.0)
        bsdf.inputs["Alpha"].default_value = alpha
    if alpha < 1.0:
        # 반투명으로 그리기 (Blender 버전에 따라 속성 이름이 다르다)
        for attr, value in (("surface_render_method", "BLENDED"), ("blend_method", "BLEND")):
            if hasattr(mat, attr):
                try:
                    setattr(mat, attr, value)
                except Exception:
                    pass
    return mat


def _put(obj, collection, mat=None):
    """오브젝트를 원하는 컬렉션으로 옮기고 재질을 붙인다."""
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    collection.objects.link(obj)
    if mat is not None:
        obj.data.materials.clear()
        obj.data.materials.append(mat)
    return obj


def _box(name, x0, y0, z0, x1, y1, z1, collection, mat):
    """두 모서리 (x0, y0, z0) ~ (x1, y1, z1) 사이를 채우는 상자를 만든다."""
    import bpy
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2))
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = (max(x1 - x0, 1e-3), max(y1 - y0, 1e-3), max(z1 - z0, 1e-3))
    return _put(obj, collection, mat)


def _rod(name, p0, p1, radius, collection, mat):
    """점 p0에서 p1까지 이어지는 얇은 원기둥(막대)을 만든다. (방 모서리 선, 스피커를 매다는 줄)"""
    import bpy
    from mathutils import Vector
    a, b = Vector(p0), Vector(p1)
    d = b - a
    bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=radius, depth=d.length,
                                        location=(a + b) / 2)
    obj = bpy.context.active_object
    obj.name = name
    # 원기둥은 처음에 z축 방향으로 서 있으므로, d 방향으로 돌린다
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(d.normalized())
    return _put(obj, collection, mat)


def _text(name, body, location, size, collection, mat, font, face_camera=None, rotation=None):
    """
    글자 오브젝트를 만든다.
    face_camera에 카메라를 주면 글자가 항상 카메라를 바라보게(Track To 제약) 한다.
    """
    import bpy
    curve = bpy.data.curves.new(name, "FONT")
    curve.body = body
    curve.size = size
    curve.align_x = "CENTER"
    curve.align_y = "CENTER"
    curve.extrude = 0.005
    if font is not None:
        curve.font = font
    obj = bpy.data.objects.new(name, curve)
    obj.location = location
    if rotation is not None:
        obj.rotation_euler = rotation
    collection.objects.link(obj)
    curve.materials.append(mat)
    if face_camera is not None:
        con = obj.constraints.new("TRACK_TO")
        con.target = face_camera
        con.track_axis = "TRACK_Z"    # 글자 앞면(+Z)이 카메라를 향하게
        con.up_axis = "UP_Y"          # 글자 위쪽(+Y)은 위로
    return obj


def _new_collection(name):
    import bpy
    col = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(col)
    return col


def build_room(scene, room_col, font, words):
    """방(바닥, 앞벽, 모서리 선, 금지 구역)을 만든다. 기준/추천이 함께 쓰는 부분이다."""
    import bpy
    W, L, H = scene["dimensions_m"]

    # 바닥: 연한 회색 평면
    bpy.ops.mesh.primitive_plane_add(size=1.0, location=(W / 2, L / 2, 0))
    floor = bpy.context.active_object
    floor.name = "Floor"
    floor.scale = (W, L, 1)
    _put(floor, room_col, _material("M_Floor", COLOR_FLOOR))

    # 앞벽(y=0): 알아보기 쉽게 하늘색 판. 카메라가 뒤에서 앞을 보므로 가려지는 것이 없다.
    _box("FrontWall", 0, -0.05, 0, W, 0, H, room_col, _material("M_FrontWall", COLOR_FRONT_WALL))

    # 벽/천장: 상자의 모서리 12개를 얇은 막대로 그려 "선이 보이는 상자"로 만든다
    edge_mat = _material("M_Edge", COLOR_EDGE)
    corners = [(x, y, z) for z in (0, H) for y in (0, L) for x in (0, W)]
    n = 0
    for i, p in enumerate(corners):
        for q in corners[i + 1:]:
            # 좌표 하나만 다른 두 꼭짓점 = 상자의 모서리
            if sum(1 for a, b in zip(p, q) if a != b) == 1:
                _rod(f"Edge_{n:02d}", p, q, EDGE_RADIUS, room_col, edge_mat)
                n += 1

    # 금지 구역: 바닥 위 반투명 회색 상자 + "설치 금지" 글자
    zone_mat = _material("M_Forbidden", COLOR_FORBIDDEN, alpha=0.45)
    text_mat = _material("M_Text", COLOR_TEXT)
    for i, (x0, y0, x1, y1) in enumerate(scene["forbidden_zones"]):
        _box(f"Forbidden_{i}", x0, y0, 0, x1, y1, FORBIDDEN_HEIGHT, room_col, zone_mat)
        # 글자는 상자 윗면의 앞벽 쪽에 둔다 (뒤쪽 가장자리는 청취 지점 구에 가려지기 쉬워서)
        _text(f"ForbiddenLabel_{i}", words["forbidden"], ((x0 + x1) / 2, y0 + (y1 - y0) * 0.3, FORBIDDEN_HEIGHT + 0.01),
              0.25, room_col, text_mat, font, rotation=(0, 0, math.pi))   # 카메라 쪽에서 바로 읽히게 180° 돌림

    # 앞벽 글자: 벽면에 붙여서 방 안쪽(+y)을 보게 세운다 (x축 90° 세우고 z축 180° 돌림)
    wall_rot = (math.pi / 2, 0, math.pi)
    # 글자는 앞벽 "위"에 간판처럼 띄운다. (벽면에 쓰면 앞쪽 스피커·구에 가려지기 쉬워서)
    _text("FrontLabel", words["front"], (W / 2, 0.0, H + SIGN_LINES[0]), 0.42, room_col, text_mat, font,
          rotation=wall_rot)
    return text_mat, wall_rot


def build_placement(scene, key, col, cam, font, words, text_mat, wall_rot, vmin, vmax):
    """한 배치(기준 또는 추천)의 스피커, 색칠한 청취 지점, dB 글자, 제목 글자를 col 컬렉션에 만든다."""
    import bpy
    W, L, H = scene["dimensions_m"]
    place = scene[key]
    x, y, z = place["position"]

    # 스피커: 눈에 띄는 색 상자 + 천장까지 매단 얇은 막대 + 바닥에 같은 색 원판(바닥 위치를 알기 쉽게)
    sp_mat = _material(f"M_Speaker_{key}", COLOR_SPEAKER[key])
    sw, sd, sh = SPEAKER_SIZE
    _box(f"Speaker_{key}", x - sw / 2, y - sd / 2, z - sh / 2, x + sw / 2, y + sd / 2, z + sh / 2, col, sp_mat)
    _rod(f"SpeakerRod_{key}", (x, y, z + sh / 2), (x, y, H), 0.02, col, sp_mat)
    bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=0.35, depth=0.02, location=(x, y, 0.011))
    _put(bpy.context.active_object, col, sp_mat).name = f"SpeakerFloorMark_{key}"

    # 청취 지점: 구 + 위에 dB 숫자. 색은 같은 범위(vmin~vmax)로 viridis 매핑
    for i, (pt, db) in enumerate(zip(scene["listening_points"], place["levels_db"])):
        rgb = viridis((db - vmin) / (vmax - vmin))
        bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=SPHERE_RADIUS, location=pt)
        sphere = bpy.context.active_object
        sphere.name = f"Point_{key}_{i:02d}"
        bpy.ops.object.shade_smooth()
        _put(sphere, col, _material(f"M_Point_{key}_{i:02d}", rgb))
        _text(f"Label_{key}_{i:02d}", f"{db:.1f}", (pt[0], pt[1], pt[2] + SPHERE_RADIUS + 0.3),
              LABEL_SIZE, col, text_mat, font, face_camera=cam)

    # 앞벽 제목: 어떤 배치인지, 균일도 수치
    title = words["title"].format(label=words[key], x=x, y=y, z=z, std=place["std_db"], mn=place["min_db"])
    _text(f"Title_{key}", title, (W / 2, 0.0, H + SIGN_LINES[1]), 0.28, col, text_mat, font, rotation=wall_rot)
    if key == "recommended":
        line = words["improve"].format(p=scene["improvement_percent"])
    else:
        line = words["current"]
    _text(f"Note_{key}", line, (W / 2, 0.0, H + SIGN_LINES[2]), 0.24, col, text_mat, font, rotation=wall_rot)


def setup_camera_and_lights(scene):
    """카메라(방 뒤쪽 위에서 앞벽을 내려다보는 대각선)와 조명(태양 1 + 약한 보조광)을 만든다."""
    import bpy
    W, L, H = scene["dimensions_m"]
    sc = bpy.context.scene

    # 카메라가 바라볼 점(빈 오브젝트). 방 가운데에서 조금 앞쪽, 바닥보다 약간 위
    target = bpy.data.objects.new("CameraTarget", None)
    target.location = (W / 2, L * 0.45, 1.4)
    sc.collection.objects.link(target)

    cam_data = bpy.data.cameras.new("Camera")
    cam_data.lens = 28                     # 작은 값일수록 넓게 보인다 [mm]
    cam = bpy.data.objects.new("Camera", cam_data)
    cam.location = (W * 0.72, L + 8.0, H + 6.5)   # 오른쪽 뒤, 천장보다 위
    sc.collection.objects.link(cam)
    con = cam.constraints.new("TRACK_TO")
    con.target = target
    con.track_axis = "TRACK_NEGATIVE_Z"    # 카메라는 -Z 방향을 바라본다
    con.up_axis = "UP_Y"
    sc.camera = cam

    # 태양광: 위에서 비스듬히 / 보조광: 반대쪽에서 약하게 (Eevee/Cycles에서 쓰임. Workbench는 자체 조명 사용)
    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    sun.data.energy = 3.0
    sun.rotation_euler = (math.radians(40), math.radians(15), math.radians(150))
    sc.collection.objects.link(sun)
    fill = bpy.data.objects.new("Fill", bpy.data.lights.new("Fill", "SUN"))
    fill.data.energy = 0.8
    fill.rotation_euler = (math.radians(60), 0, math.radians(-40))
    sc.collection.objects.link(fill)

    # 배경색 (World)
    world = bpy.data.worlds.new("World")
    world.color = tuple(srgb_to_linear(c) for c in COLOR_BACKGROUND)
    sc.world = world
    return cam


def setup_render(engine):
    """렌더 설정. engine = "BLENDER_WORKBENCH"(빠름, 기본) 또는 "CYCLES"(CPU로만 계산, 예비용)."""
    import bpy
    sc = bpy.context.scene
    sc.render.engine = engine
    sc.render.resolution_x, sc.render.resolution_y = RESOLUTION
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = "PNG"
    sc.render.film_transparent = False
    # 'Standard'로 해야 지정한 색이 그대로 나온다 (기본값 AgX는 색을 부드럽게 바꾼다)
    sc.view_settings.view_transform = "Standard"
    if engine == "BLENDER_WORKBENCH":
        sc.view_settings.exposure = 0.8     # 스튜디오 조명만으로는 어두워서 조금 밝게

    if engine == "BLENDER_WORKBENCH":
        shading = sc.display.shading
        shading.light = "STUDIO"            # 기본 스튜디오 조명 (구가 입체로 보이게)
        shading.color_type = "MATERIAL"     # 재질의 diffuse_color로 칠한다
        shading.show_shadows = False        # 그림자를 켜면 간판 글자 그림자가 바닥에 비쳐 지저분하다
        shading.show_cavity = False
        shading.show_object_outline = True  # 오브젝트 테두리를 그려 모양이 잘 보이게
        sc.display.render_aa = "8"
    else:
        sc.cycles.device = "CPU"
        sc.cycles.samples = 32
        sc.world.use_nodes = True
        bg = sc.world.node_tree.nodes.get("Background")
        if bg is not None:
            bg.inputs["Color"].default_value = (*sc.world.color, 1.0)


def show_only(collections, visible_key):
    """visible_key 컬렉션만 보이게 한다. (렌더와 뷰포트 둘 다)"""
    import bpy
    layer = bpy.context.view_layer.layer_collection
    for key, col in collections.items():
        hidden = key != visible_key
        col.hide_render = hidden
        layer.children[col.name].hide_viewport = hidden   # Outliner의 눈 아이콘


def render_to(path):
    """현재 카메라로 그림 한 장을 렌더링해서 path에 PNG로 저장한다."""
    import bpy
    bpy.context.scene.render.filepath = os.path.abspath(path)   # 상대 경로는 Blender가 다르게 해석할 수 있어 절대 경로로
    bpy.ops.render.render(write_still=True)
    if not os.path.isfile(path):
        raise RuntimeError(f"렌더 결과 파일이 만들어지지 않았습니다: {path}")


def load_font():
    """한글 글꼴을 불러온다. 성공하면 (글꼴, "ko"), 없으면 (None, "en") — 기본 글꼴은 한글이 안 나온다."""
    import bpy
    for path in KOREAN_FONTS:
        if os.path.isfile(path):
            try:
                return bpy.data.fonts.load(path), "ko"
            except Exception as exc:
                print(f"[경고] 글꼴을 불러오지 못했습니다: {path} ({exc})")
    print("[안내] 한글 글꼴이 없어 글자를 영어로 표시합니다.")
    return None, "en"


def main(argv):
    import bpy

    scene_path, out_dir = parse_args(argv)
    with open(scene_path, encoding="utf-8") as f:
        scene = json.load(f)
    os.makedirs(out_dir, exist_ok=True)
    print(f"[blender_scene] Blender {bpy.app.version_string}, 장면 데이터: {scene_path}")

    # 1) 기본 장면(큐브, 카메라, 조명)을 모두 지우고 빈 장면에서 시작
    bpy.ops.wm.read_factory_settings(use_empty=True)

    font, lang = load_font()
    words = TEXTS[lang]
    vmin, vmax = color_range(scene)

    # 2) 컬렉션: Room(공통) / Baseline / Recommended
    room_col = _new_collection("Room")
    cols = {"baseline": _new_collection("Baseline"), "recommended": _new_collection("Recommended")}

    # 3) 장면 만들기
    cam = setup_camera_and_lights(scene)
    text_mat, wall_rot = build_room(scene, room_col, font, words)
    W, L, H = scene["dimensions_m"]
    legend = words["legend"].format(vmin=vmin, vmax=vmax)
    room_line = words["room"].format(name=scene["room_name"]) + ("" if scene["measured"] else words["temp"])
    _text("Legend", legend, (W / 2, 0.0, H + SIGN_LINES[3]), 0.22, room_col, text_mat, font, rotation=wall_rot)
    _text("RoomName", room_line, (W / 2, 0.0, H + SIGN_LINES[4]), 0.22, room_col, text_mat, font, rotation=wall_rot)
    for key, col in cols.items():
        build_placement(scene, key, col, cam, font, words, text_mat, wall_rot, vmin, vmax)

    # 4) 렌더링: Workbench가 실패하면 Cycles(CPU)로 다시 시도
    outputs = {"baseline": os.path.join(out_dir, "baseline.png"),
               "recommended": os.path.join(out_dir, "recommended.png")}
    for engine in ("BLENDER_WORKBENCH", "CYCLES"):
        try:
            setup_render(engine)
            for key, path in outputs.items():
                show_only(cols, key)
                render_to(path)
            print(f"[blender_scene] 렌더 엔진: {engine}")
            break
        except Exception as exc:
            print(f"[경고] {engine} 렌더 실패: {exc}")
            if engine == "CYCLES":
                raise

    # 5) .blend 저장: 추천 배치가 보이는 상태로 저장 (Outliner에서 Baseline 눈 아이콘을 켜서 비교)
    show_only(cols, "recommended")
    blend_path = os.path.abspath(os.path.join(out_dir, "scene.blend"))
    bpy.context.preferences.filepaths.save_version = 0   # 백업 파일(scene.blend1)을 만들지 않는다
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)

    print("[blender_scene] 만든 파일:")
    for path in (*outputs.values(), blend_path):
        print("  " + os.path.abspath(path))


# Blender가 --python으로 실행할 때만 동작한다 (pytest가 import 할 때는 실행되지 않음)
if __name__ == "__main__":
    main(sys.argv)
