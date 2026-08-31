# -*- coding: utf-8 -*-
"""dg5f 스크립트 공용 경로 규칙 — 로그·보정 파일이 서로 어긋나거나 덮어써지지 않게 한곳에 모음.

왜 이 파일이 있나 (2026-07-16):
  ① **덮어쓰기 사고**: 로그 파일명이 분 단위(%H%M)라 같은 분에 두 번 실행하면 뒤가 앞을
     소리 없이 지웠다. 7/6에 이미 한 번 로그를 통째로 잃고 "실행마다 새 파일"로 고쳤는데
     분 단위까지만 고친 탓에 함정이 남아 있었다. → 초 단위 + 그래도 겹치면 접미사.
  ② **저장/로드 경로 불일치**: calibrate는 CWD 상대(`open("dg5f_calibration.json","w")`)로
     저장하는데 dg5f_angles는 스크립트 기준 절대경로로 읽었다. dg5f 폴더 안에서 실행하면
     우연히 맞지만 밖에서 실행하면 보정이 딴 데 저장되고 로드는 못 찾는다.
     → 저장·로드가 이 모듈의 **같은 상수**를 쓴다.

⚠️ 새 로그를 추가할 땐 반드시 unique_log_path()를 쓸 것. 직접 strftime + open(...,"w") 금지.
"""
import os
import sys
import time

# PyInstaller로 얼린 실행파일에서는 이 모듈이 압축 아카이브(PYZ) 안에서 임포트되므로
# __file__ 기준 경로가 실제 디스크 위치가 아니게 된다 — exe 파일 위치를 기준으로 삼는다.
# (config/rtauto_config.py의 REPO_ROOT와 같은 이유, 같은 처리.)
if getattr(sys, "frozen", False):
    _HERE = os.path.dirname(os.path.abspath(sys.executable))
else:
    _HERE = os.path.dirname(os.path.abspath(__file__))

# 로그는 스크립트 위치 기준 — 실행 CWD와 무관 (어디서 실행하든 같은 곳에 쌓인다)
LOG_DIR = os.path.join(_HERE, "logs")

# 보정 파일: calibrate_dg5f.py(저장)와 dg5f_angles.py(로드)가 **이 상수 하나**를 공유
CALIB_PATH = os.path.join(_HERE, "dg5f_calibration.json")


def unique_log_path(prefix, ext=".csv", log_dir=None):
    """logs/<prefix>_<YYYYMMDD_HHMMSS><ext> — 이미 있으면 _2, _3… 을 붙여 **절대 덮지 않는다**.

    초 단위라 실질적으로 겹치지 않지만, 겹쳤을 때 조용히 지우는 것보다 파일이 하나 더
    생기는 편이 낫다(로그는 지워지면 복구 불가, 늘어나는 건 나중에 지우면 그만).
    """
    d = log_dir or LOG_DIR
    os.makedirs(d, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    n = 1
    while True:
        name = f"{prefix}_{stamp}{ext}" if n == 1 else f"{prefix}_{stamp}_{n}{ext}"
        path = os.path.join(d, name)
        try:
            # 반환 즉시 자리 선점 — 경로만 계산해 돌려주면 호출자가 open하기 전에 다른
            # 프로세스가 같은 이름을 채갈 수 있다. 'x'(배타 생성)로 원자적으로 예약한다.
            open(path, "x", encoding="utf-8").close()
            return path
        except FileExistsError:
            n += 1
