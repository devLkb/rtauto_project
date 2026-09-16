# joint_ranges.py
# ─────────────────────────────────────────────────────────────────────────────
# 사람 손가락 관절 ↔ DG5F 로봇 관절의 [최소~최대 가동범위] 대조표.
#
# 채택된 매핑(2026-07-21 구현): **전 채널 1:1 + 로봇 기구한계 clamp**.
#   robot_deg = human_deg,  단 [r_use_min, r_use_max]로 clamp.
#   즉 "사람 관절각을 그대로 로봇 관절각으로" 보내고, 사람이 로봇 한계보다 크게 움직이면 한계각에서 포화.
#   → [0,1] 정규화(norm=(v-h_min)/(h_max-h_min))는 채택 안 함: 벌림 중립이 어긋나고(index_abd 중립→+10°),
#     middle_abd 0나누기, 좁은 보정폭 과증폭 문제 때문. 1:1은 이 셋을 모두 회피(+엄지 1:1과 일관).
#   구현 위치: dg5f_angles.map_to_dg5f (전 분기 1:1). 이 표는 사람/로봇 범위 대조·검증용.
#
# 데이터 출처:
#   • 사람 범위(h_min/h_max): dg5f_calibration.json human_ranges (rad). 실행 시 자동 로드.
#       - percentile(2/98) 측정치. ★1:1에서는 매핑에 직접 안 쓰임(참고·검증용). robot=human_deg 그대로.
#       - 단 보정 세션에서 관절을 끝까지 안 움직였으면 라이브 _bend도 그만큼만 나와 로봇이 덜 움직일 수 있음.
#   • 로봇 범위: urdf/dg5f/dg5f_left.urdf <limit> (이번 세션 왼손 미러 기준). 상수로 하드코딩.
#       - pip/dip(관절 _3,_4)의 URDF 리밋은 ±90°로 넉넉히 열려 있음(기구 여유).
#         실제 굽힘 사용범위는 'robot_use'(현재 map_to_dg5f 타겟)를 참고.
#
# 사용:  python joint_ranges.py            # 표 출력
#        from joint_ranges import HUMAN, ROBOT, print_table
# ─────────────────────────────────────────────────────────────────────────────
import json
import math
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_CALIB = os.path.join(_HERE, "dg5f_calibration.json")

# 채널 순서 = dg5f_angles.CHANNEL_NAMES = 패킷/관절 인덱스 순서.
#   (channel, 로봇관절 f_j, 프록시 의미,
#    사람 min~max[rad] (lo,hi),          ← ★사람 관절 가동범위(여기 직접 명시)
#    로봇 URDF 리밋[deg] (lo,hi), 로봇 현재 사용범위[deg] (lo,hi), 현재 매핑방식)
#
# ★ 사람 범위(human_rad)는 dg5f_calibration.json(created 2026-07-20 15:32)의 스냅샷.
#   실행 시 calibration.json에 값이 있으면 그걸로 자동 덮어씀(_apply_live_calib).
#   재보정했는데 여기 숫자와 다르면 → calibration.json이 최신, 아래 스냅샷만 낡은 것.
# 로봇 사용범위 = dg5f_angles.DG5F_CHANNELS 의 (dg_min,dg_max) — 실제 명령이 도달하는 범위.
SPEC = [
    # 채널          관절    프록시 의미                        사람min~max(rad)     URDF리밋      사용범위     매핑
    ("thumb_cmc",  "1_1", "엄지 평면 벌림/접힘(cmc→mcp)",    (-0.524, -0.025), (-77,  22), ( -65,  22), "|abd|→[fold,spread]선형"),
    ("thumb_opp",  "1_2", "엄지 깊이 들림(손바닥평면 대비)", ( 0.013,  0.428), (  0, 155), (  0, -75), "1:1"),
    ("thumb_mcp",  "1_3", "엄지 MCP 굽힘",                   ( 0.054,  0.549), (-90,  90), (  0,  80), "1:1"),
    ("thumb_ip",   "1_4", "엄지 IP 굽힘",                    ( 0.031,  1.369), (-90,  90), (  0,  80), "1:1"),
    ("index_abd",  "2_1", "검지 좌우 벌림(중지 기준)",       (-0.345,  0.096), (-20,  31), (-25,  20), "1:1"),
    ("index_mcp",  "2_2", "검지 MCP 굽힘",                   ( 0.094,  0.497), (  0, 115), (  0, 110), "1:1"),
    ("index_pip",  "2_3", "검지 PIP 굽힘",                   ( 0.056,  1.900), (-90,  90), (  0,  85), "1:1"),
    ("index_dip",  "2_4", "검지 DIP 굽힘",                   ( 0.009,  1.095), (-90,  90), (  0,  80), "1:1"),
    ("middle_abd", "3_1", "중지 좌우 벌림(기준=항상 0)",     ( 0.000,  0.000), (-25,  25), (-20,  20), "1:1"),
    ("middle_mcp", "3_2", "중지 MCP 굽힘",                   ( 0.054,  0.580), (  0, 115), (  0, 110), "1:1"),
    ("middle_pip", "3_3", "중지 PIP 굽힘",                   ( 0.040,  1.900), (-90,  90), (  0,  85), "1:1"),
    ("middle_dip", "3_4", "중지 DIP 굽힘",                   ( 0.021,  1.420), (-90,  90), (  0,  80), "1:1"),
    ("ring_abd",   "4_1", "약지 좌우 벌림(중지 기준)",       (-0.131,  0.206), (-32,  15), (-12,  28), "1:1"),
    ("ring_mcp",   "4_2", "약지 MCP 굽힘",                   ( 0.015,  0.902), (  0, 110), (  0, 105), "1:1"),
    ("ring_pip",   "4_3", "약지 PIP 굽힘",                   ( 0.025,  1.900), (-90,  90), (  0,  85), "1:1"),
    ("ring_dip",   "4_4", "약지 DIP 굽힘",                   ( 0.028,  1.433), (-90,  90), (  0,  80), "1:1"),
    ("pinky_cmc",  "5_1", "새끼 손바닥 접기(cupping)",       ( 0.109,  0.210), (-60,   0), (  0,   0), "게이트(0)"),
    ("pinky_lat",  "5_2", "새끼 좌우 벌림",                  ( 0.096,  0.852), (-90,  15), (-15,  50), "1:1"),
    ("pinky_mcp",  "5_3", "새끼 MCP 굽힘",                   ( 0.034,  1.261), (-90,  90), (  0,  85), "1:1"),
    ("pinky_pip",  "5_4", "새끼 PIP 굽힘",                   ( 0.036,  1.490), (-90,  90), (  0,  80), "1:1"),
]

# 해부학적 참고 ROM(deg) — 보정 percentile이 실제 가동범위를 얼마나 담았는지 점검용(대략치).
ANATOMICAL_REF = {
    "mcp_flex": (0, 90), "pip_flex": (0, 110), "dip_flex": (0, 80),
    "finger_abd": (-20, 20), "thumb_cmc_abd": (0, 45), "thumb_opp": (0, 50),
}


def _load_human_ranges():
    """dg5f_calibration.json human_ranges(rad) 로드. 없으면 빈 dict."""
    try:
        with open(_CALIB, encoding="utf-8") as f:
            j = json.load(f)
        return j.get("human_ranges", {}), j.get("created", "?")
    except Exception as e:  # noqa: BLE001
        print(f"[joint_ranges] 보정 파일 못 읽음({e}) — 사람 범위 공란")
        return {}, "?"


_HR, _CALIB_DATE = _load_human_ranges()
_LIVE = bool(_HR)   # calibration.json에서 실제로 값을 읽었나(=사람 범위가 라이브)

# 외부에서 import 해서 쓰는 구조화 데이터
#   HUMAN[ch]  = {"min_rad","max_rad","min_deg","max_deg","src"}  src=live|snapshot
#   ROBOT[ch]  = {"joint","urdf":(lo,hi),"use":(lo,hi),"mapping":..,"desc":..}
HUMAN, ROBOT = {}, {}
for ch, joint, desc, human_rad, urdf, use, mapping in SPEC:
    # 기본값 = 파일에 박아둔 스냅샷. calibration.json에 값 있으면 그걸로 덮어씀.
    lo, hi = human_rad
    src = "snapshot"
    if ch in _HR and _HR[ch].get("min") is not None:
        lo, hi = _HR[ch]["min"], _HR[ch]["max"]
        src = "live"
    HUMAN[ch] = {
        "min_rad": lo, "max_rad": hi,
        "min_deg": math.degrees(lo), "max_deg": math.degrees(hi),
        "src": src,
    }
    ROBOT[ch] = {"joint": joint, "urdf": urdf, "use": use,
                 "mapping": mapping, "desc": desc}


def print_table():
    src = "라이브(calibration.json)" if _LIVE else "파일 내 스냅샷"
    print(f"사람 범위 출처: {src}  (calibration created {_CALIB_DATE})")
    print("사람=측정 가동범위(rad/deg) · 로봇=URDF 리밋 및 현재 사용범위(deg)\n")
    hdr = (f"{'채널':11s} {'관절':4s} {'프록시 의미':22s} "
           f"{'사람min~max(rad)':>17s} {'사람min~max(deg)':>17s} "
           f"{'로봇URDF(deg)':>13s} {'로봇사용(deg)':>13s} {'매핑':>8s}")
    print(hdr)
    print("-" * len(hdr))
    for ch, joint, desc, _human_rad, urdf, use, mapping in SPEC:
        h = HUMAN[ch]  # 사람 범위는 HUMAN(스냅샷 또는 라이브)에서 읽음
        hr = f"{h['min_rad']:+.3f}~{h['max_rad']:+.3f}"
        hd = f"{h['min_deg']:+6.1f}~{h['max_deg']:+6.1f}"
        ud = f"{urdf[0]:+4d}~{urdf[1]:+4d}"
        us = f"{use[0]:+4d}~{use[1]:+4d}"
        print(f"{ch:11s} {joint:4s} {desc:20s} "
              f"{hr:>17s} {hd:>17s} {ud:>13s} {us:>13s} {mapping:>9s}")
    print("\n주(매핑=전 채널 1:1, 2026-07-21 구현):")
    print(" • robot_deg = human_deg,  단 '로봇사용'[dmin,dmax]로 clamp. 사람이 로봇 한계보다 크게 움직이면 포화.")
    print(" • 기구한계<사람인 곳(pip 109>90, pinky_lat 36>15)은 로봇 한계각에서 포화 — 정상(사용범위 내내 1:1).")
    print(" • middle_abd는 기준(중지)이라 v≈0 → 0. 1:1이라 0나누기 없음.  pinky_cmc(5_1)는 게이트(항상 0).")
    print(" • 사람 범위(rad/deg)는 이제 매핑에 직접 안 쓰임(참고·검증용). 보정 폭이 좁아도 과증폭은 없으나,")
    print("   보정 때 관절을 끝까지 안 움직였으면 라이브에서도 그만큼만 나와 로봇이 덜 움직일 수 있음.")


if __name__ == "__main__":
    print_table()
