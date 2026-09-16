# -*- coding: utf-8 -*-
"""웹캠에서 **쓸 수 있는 가장 좋은 화면**을 찾아 적용하는 공용 부품.

왜 이 파일이 있나 (2026-09-16):
  ① 예전에는 카메라를 열 때 가로 1280 · 세로 720을 **고정으로 요청**했다. 그런데 실제로
     열린 건 640x480이었다 — 요청이 통하지 않았는데 아무도 몰랐다. 손가락 끝처럼 작은
     부분은 화면에 찍히는 점이 적을수록 위치가 흔들리므로 그냥 손해였다.
  ② "이 웹캠이 얼마까지 되나"를 알려주는 표준 방법이 OpenCV에 없다. 그래서 **직접 열어서
     요청해 보고, 실제로 나온 영상으로 확인하는** 방법밖에 없다.
  ③ **큰 화면이 항상 좋은 것도 아니다.** 실측(2026-09-16, 이 PC의 웹캠 + Windows msmf):
         2592x1944 → 초당 1장    (손 동작 추적 불가)
         1920x1080 → 초당 30장   ← 가장 좋음
         1280x720  → 초당 7.5장  (크기는 더 작은데 더 느리다)
          640x480  → 초당 30장
     크기와 속도는 비례하지 않는다. 웹캠이 내부적으로 지원하는 모드가 정해져 있고, 그
     밖의 크기를 요청하면 드라이버가 억지로 만들어 주느라 느려지기 때문이다. 그래서 이
     파일은 **크기만 보지 않고 속도까지 실제로 재서** 고른다.
  ④ 한 번 알아내면 파일에 적어 둔다(dg5f_paths.CAMERA_CAPS_PATH). 알아내는 데 수십 초가
     걸려서 매번 하면 실행이 느려진다.

⚠️ 실패한 요청은 카메라를 망가뜨린다 (2026-09-16 실측). 지원하지 않는 크기를 요청하면
   Windows msmf가 `Failed to select stream 0`을 내뱉고, 그 뒤로는 **원래 되던 크기도
   안 되는 상태**로 남는다 — 그래서 첫 구현은 1920x1080이 멀쩡히 되는 카메라를 두고
   "최대 640x480"이라는 틀린 답을 냈다. 지금은 후보를 하나 시험할 때마다 **카메라를
   새로 연다.** 읽기 실패는 물론 예외(cv2.error)까지 전부 실패로 처리한다.

쓰는 쪽(모두 같은 규칙으로 열린다):
  vision_node_dg5f.py · dg5f_teleop_gui.py · calibrate_dg5f.py · probe_landmarks.py ·
  calibrate_intrinsics.py · multi_camera_capture.py

설정값(config/rtauto_config.py + 레포 루트 .env):
  RTAUTO_VISION_CAMERA_WIDTH / _HEIGHT = max  → 이 파일이 가장 좋은 크기를 찾아 쓴다(기본)
  숫자(예: 1280 / 720)로 적으면 그 크기를 그대로 요청한다(탐색 안 함)
  RTAUTO_VISION_CAMERA_MIN_FPS               → "쓸 만하다"의 기준선(기본 초당 15장)
  RTAUTO_VISION_CAMERA_FOURCC                → 비우면 기본 포맷/MJPG 실측 비교, 값은 강제 포맷
  RTAUTO_VISION_CAMERA_INDEX = auto          → 꽂힌 카메라 중 가장 좋은 것을 알아서 고른다
                                               (숫자면 그 번호 고정. 기본값은 0)

직접 확인해 보려면 (터미널, 리포 루트, venv 활성화 상태):
    python vision/dg5f/camera_caps.py                 # 0번 카메라
    python vision/dg5f/camera_caps.py 1               # 1번 카메라
    python vision/dg5f/camera_caps.py 0 --refresh     # 저장해 둔 값 무시하고 다시 탐색
    python vision/dg5f/camera_caps.py 0 --backend=dshow --fourcc=MJPG   # 조합 비교
    python vision/dg5f/camera_caps.py --list          # 꽂혀 있는 카메라 전부 보기
"""
import json
import os
import time

from dg5f_paths import CAMERA_CAPS_PATH

# 설정값이 이 단어들 중 하나면 "이 웹캠에서 쓸 수 있는 가장 좋은 크기"라는 뜻이다.
MAX_WORDS = ("max", "auto", "maximum", "best", "")

# 시험해 볼 후보들(넓이 내림차순). 큰 것부터 열어 보고, **속도 기준을 통과한 첫 번째**가
# 답이다. 지원하지 않는 크기를 요청하면 가까운 크기로 깎아 주는 드라이버가 많아서,
# 목록에 없는 크기(예: 2592x1944)도 이 과정에서 자연스럽게 발견된다.
PROBE_SIZES = (
    (3840, 2160),   # 4K
    (2560, 1440),   # QHD
    (1920, 1080),   # FHD
    (1600, 1200),
    (1280, 960),
    (1280, 720),    # HD (예전에 고정으로 요청하던 크기)
    (1024, 768),
    (800, 600),
    (640, 480),     # 웹캠 최소 공통 크기
)

# 손 동작을 따라가려면 초당 몇 장은 나와야 하는가. 이보다 느린 크기는 "더 크더라도" 버린다.
# 호출하는 쪽이 설정값(RTAUTO_VISION_CAMERA_MIN_FPS)으로 바꿀 수 있다.
DEFAULT_MIN_FPS = 15.0

# 이보다 작은 영상은 "진짜 카메라 화면"으로 보지 않는다 — 저장해 두면 다음 실행이 그
# 엉뚱한 값을 그대로 쓰게 되므로, 쓰기는 하되 저장은 하지 않는다.
MIN_SANE_WIDTH, MIN_SANE_HEIGHT = 160, 120

# 크기를 바꾼 직후엔 드라이버가 스트림을 다시 여느라 몇 장은 실패로 돌아온다.
# 이 횟수까지는 다시 읽어 보고, 그래도 안 나오면 "그 크기는 못 쓴다"로 판정한다.
_VERIFY_READS = 12
_VERIFY_SLEEP = 0.05

# 탐색 중 속도를 재는 시간과, 재기 전에 버리는 장수(아래 measure_fps 설명 참고).
_PROBE_SECONDS = 1.5
_PROBE_WARMUP = 5

# 설정에서 FOURCC를 비워 두면 카메라 기본값과 MJPG를 둘 다 실제로 재 본다. 많은 USB 웹캠은
# raw(YUYV 등)로 큰 화면을 보내면 USB 대역폭에 막혀 FPS가 떨어지고, MJPG에서는 같은 해상도가
# 정상 속도로 나온다.
AUTO_FOURCC_CANDIDATES = ("", "MJPG")
CACHE_SCHEMA = 2


class CaptureFormat:
    """실제로 적용된 캡처 형식. `how`는 이 값이 어떻게 정해졌는지를 뜻한다.

    fixed=설정에 적힌 숫자 그대로 / cache=저장해 둔 값 재사용 / probe=이번에 찾아냄
    """

    def __init__(self, width, height, fps, how, measured_fps=0.0, index=None, fourcc=""):
        self.index = index        # 실제로 열린 카메라 번호(설정이 "auto"였을 때 특히 중요)
        self.width = int(width)
        self.height = int(height)
        self.fps = float(fps)                    # 드라이버가 알려준 값(0을 주는 백엔드도 있다)
        self.measured_fps = float(measured_fps)  # 실제로 재 본 값(0이면 안 재 봤다는 뜻)
        self.how = how
        self.fourcc = _normalize_fourcc(fourcc)

    def __repr__(self):
        fourcc = self.fourcc or "기본"
        return f"CaptureFormat({self.width}x{self.height}@{self.fps:.1f}, fourcc={fourcc}, how={self.how})"

    @property
    def text(self):
        how_ko = {"fixed": "설정값 고정", "cache": "저장된 값 재사용",
                  "probe": "이번에 찾아냄", "unknown": "확인 실패"}
        speed = (f"실측 초당 {self.measured_fps:.1f}장" if self.measured_fps
                 else f"드라이버 표기 {self.fps:.1f}fps")
        fourcc = self.fourcc or "기본"
        return f"{self.width}x{self.height}, {speed}, 포맷 {fourcc} ({how_ko.get(self.how, self.how)})"


def parse_size_spec(value):
    """설정 문자열을 크기로 바꾼다. "가장 좋은 크기"를 뜻하면 None, 숫자면 int.

    잘못된 값(예: "abc")은 조용히 넘기지 않고 ValueError로 알린다 — .env 오타를 그대로
    두면 "왜 화면이 작지?"로 한참 헤매게 된다.
    """
    if value is None:
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    text = str(value).strip().lower()
    if text in MAX_WORDS:
        return None
    try:
        number = int(text)
    except ValueError:
        raise ValueError(
            f"카메라 화면 크기 설정값을 이해할 수 없습니다: {value!r}\n"
            f"       숫자(예: 1280) 또는 {'/'.join(w for w in MAX_WORDS if w)} 중 하나여야 합니다.")
    return number if number > 0 else None


def _cv2():
    """cv2는 임포트에만 0.6초가 걸린다 — GUI가 이 모듈을 화면 띄우기 전에 임포트해도
    그 비용을 물지 않도록 실제로 쓸 때 가져온다(dg5f_teleop_gui의 지연 임포트 규칙과 같음)."""
    import cv2
    return cv2


# ----------------------------- 카메라에 직접 묻기 -----------------------------

def frame_size(cap, tries=_VERIFY_READS):
    """실제로 들어온 영상 한 장의 (가로, 세로). 못 받으면 (0, 0).

    ⚠️ `cap.get(CAP_PROP_FRAME_WIDTH)`를 믿지 않는다 — 요청을 받아들이지 않았는데도
    요청값을 그대로 돌려주는 드라이버가 있다. 판정 근거는 **실제 영상**뿐이다.
    """
    for i in range(tries):
        try:
            ok, frame = cap.read()
        except Exception:
            # 지원하지 않는 크기를 요청한 뒤 드라이버가 망가진 상태.
            # (실측: 깨진 프레임이 오면 OpenCV가 cv2.error를 던진다 — False가 아니다.)
            ok, frame = False, None
        if ok and frame is not None and getattr(frame, "size", 0):
            return int(frame.shape[1]), int(frame.shape[0])
        if i + 1 < tries:
            time.sleep(_VERIFY_SLEEP)
    return 0, 0


def measure_fps(cap, seconds=4.0, warmup=10):
    """실제로 초당 몇 장이 들어오는지 재서 돌려준다.

    ⚠️ 드라이버가 알려주는 값(`cap.get(CAP_PROP_FPS)`)을 믿으면 안 된다 — 0을 주거나
    이론값을 주는 백엔드가 있다. 그리고 **반드시 몇 장 버리고 시작한다**: 크기를 바꾼
    직후의 첫 몇 장은 이미 만들어져 있던 것이라 즉시 돌아와, 안 버리고 세면 실제보다
    훨씬 빠르게 나온다(2026-09-16에 이 함정에 걸려 초당 2장짜리를 30장으로 잘못 쟀다).
    """
    for _ in range(warmup):
        try:
            cap.read()
        except Exception:
            return 0.0
    t0 = time.perf_counter()
    frames = 0
    while time.perf_counter() - t0 < seconds:
        try:
            ok, _ = cap.read()
        except Exception:
            break
        frames += int(bool(ok))
    elapsed = time.perf_counter() - t0
    return frames / elapsed if elapsed > 0 else 0.0


def _set_if_needed(cap, prop, value, tolerance=0.5, force=False):
    """이미 그 값이면 호출하지 않는다 — 필요할 때만 드라이버 보고값을 무시하고 강제 적용한다."""
    if not force:
        try:
            current = float(cap.get(prop))
        except Exception:
            current = float("nan")
        if abs(current - float(value)) <= tolerance:
            return False
    cap.set(prop, value)
    return True


def _normalize_fourcc(fourcc):
    return str(fourcc or "").strip().upper()[:4]


def _fourcc_candidates(fourcc):
    explicit = _normalize_fourcc(fourcc)
    if explicit:
        return (explicit,)
    return AUTO_FOURCC_CANDIDATES


def _apply_fourcc(cap, fourcc, force=False):
    """영상 압축 형식 요청(예: MJPG). 효과는 백엔드·카메라마다 다르므로 결과를 믿지 않는다."""
    fourcc = _normalize_fourcc(fourcc)
    if not fourcc:
        return
    cv2 = _cv2()
    try:
        code = cv2.VideoWriter_fourcc(*fourcc)
        _set_if_needed(cap, cv2.CAP_PROP_FOURCC, code, tolerance=0.0, force=force)
    except Exception:
        pass


def _try_size(cap, width, height, fps=None, force_fps=False):
    """크기와 요청 FPS를 적용하고, **실제로 나온** 영상 크기를 돌려준다. 실패하면 (0, 0)."""
    cv2 = _cv2()
    try:
        changed = _set_if_needed(cap, cv2.CAP_PROP_FRAME_WIDTH, width)
        changed = _set_if_needed(cap, cv2.CAP_PROP_FRAME_HEIGHT, height) or changed
        if fps is not None:
            _set_if_needed(cap, cv2.CAP_PROP_FPS, fps, force=force_fps or changed)
    except Exception:
        return 0, 0
    return frame_size(cap)


def _area(size):
    return size[0] * size[1]


# ----------------------------- 가장 좋은 크기 찾기 -----------------------------

def probe_best_size(cap, log=print, reopen=None, fourcc="", min_fps=DEFAULT_MIN_FPS, requested_fps=None):
    """큰 크기부터 실제로 시험해, **속도 기준을 통과한 가장 큰 크기**를 고른다.

    돌려주는 값은 (카메라, (가로, 세로), 실측 초당 장수)다 — 도중에 카메라를 다시 열기
    때문에 호출한 쪽은 **반드시 돌려받은 카메라를 써야 한다**.

    reopen(옛 카메라) → 새 카메라(또는 None). 후보를 하나 시험할 때마다 이걸로 카메라를
    새로 연다. 실패한 요청이 카메라를 망가진 상태로 남기기 때문이다(파일 맨 위 ⚠️ 참고).
    **옛 카메라를 닫는 일은 reopen 쪽 책임**이다 — 여는 방법을 아는 쪽이 정리도 맡는다.
    reopen이 없으면 같은 카메라에서 이어서 시험한다(테스트용 대역 등).

    ⚠️ "요청했더니 원래 크기가 그대로 나왔다"는 **지원한다는 증거가 아니다.** 지원하지
    않는 요청을 조용히 무시하는 드라이버가 있어서, 이걸 성공으로 세면 맨 처음 후보에서
    바로 원래 크기(예: 640x480)를 답으로 내놓는다. 그래서 요청과 정확히 같게 나왔거나,
    원래보다 크게 나온 경우만 "진짜 되는 크기"로 인정한다.
    """
    base = frame_size(cap)          # 아무것도 요청하지 않았을 때 이 카메라가 주는 크기
    tested = set()                  # 같은 크기를 두 번 재지 않는다(깎여서 겹치는 일이 잦다)
    fallback = None                 # 기준엔 못 미쳤지만 영상은 나온 것 중 **가장 큰** 것
    first = True
    for size in PROBE_SIZES:
        if not first and reopen is not None:
            fresh = reopen(cap)
            if fresh is None:
                break                       # 카메라를 다시 열 수 없다 — 여기서 멈춘다
            cap = fresh
            _apply_fourcc(cap, fourcc, force=True)
        first = False

        got = _try_size(cap, *size, fps=requested_fps)
        if not _area(got) or got in tested:
            continue
        if got != size and _area(got) <= _area(base):
            # 요청이 무시됐거나 원래 크기로 깎인 것 — 지원 증거가 아니므로 넘어간다.
            # ⚠️ 여기서 tested에 넣지 말 것. 원래 크기와 같은 후보가 목록 아래쪽에 있으면
            #    (예: 640x480) 그건 **정확히 요청한 대로 나온 진짜 모드**라 따로 재야 한다.
            continue
        tested.add(got)
        fps = measure_fps(cap, seconds=_PROBE_SECONDS, warmup=_PROBE_WARMUP)
        log(f"[카메라] {size[0]}x{size[1]} 요청 → {got[0]}x{got[1]}, 초당 {fps:.1f}장")
        if fps >= min_fps:
            return cap, got, fps
        if fps > 0 and fallback is None:     # 내림차순이라 처음 기록된 것이 가장 크다
            fallback = (got, fps)

    if fallback is not None:
        size, fps = fallback
        log(f"[경고] 초당 {min_fps:.0f}장 이상 나오는 크기가 없어 {size[0]}x{size[1]}"
            f"(초당 {fps:.1f}장)로 엽니다 — 손 동작이 끊겨 보일 수 있습니다.")
    elif _area(base):
        size, fps = base, 0.0                # 아무 후보도 안 통했다 — 원래 크기로 돌아간다
        log(f"[카메라] 더 큰 크기를 쓸 수 없어 이 카메라의 기본 크기 "
            f"{base[0]}x{base[1]}로 엽니다.")
    else:
        return cap, (0, 0), 0.0

    if frame_size(cap) != size:
        if reopen is not None:
            fresh = reopen(cap)
            if fresh is not None:
                cap = fresh
                _apply_fourcc(cap, fourcc, force=True)
        _try_size(cap, *size, fps=requested_fps, force_fps=True)
    if not fps:
        fps = measure_fps(cap, seconds=_PROBE_SECONDS, warmup=_PROBE_WARMUP)
    return cap, size, fps


def _format_rank(item, min_fps):
    fourcc, size, measured = item
    order = AUTO_FOURCC_CANDIDATES.index(fourcc) if fourcc in AUTO_FOURCC_CANDIDATES else 0
    return (measured >= min_fps, _area(size), measured, -order)


def _fixed_format_rank(item, requested, min_fps):
    fourcc, size, measured = item
    order = AUTO_FOURCC_CANDIDATES.index(fourcc) if fourcc in AUTO_FOURCC_CANDIDATES else 0
    return (size == requested, measured >= min_fps, _area(size), measured, -order)


def _finalize_format(cap, size, fourcc, fps, reopen=None):
    if reopen is not None:
        fresh = reopen(cap)
        if fresh is not None:
            cap = fresh
    _apply_fourcc(cap, fourcc, force=True)
    got = _try_size(cap, *size, fps=fps, force_fps=True)
    return cap, got


def probe_best_format(cap, log=print, reopen=None, fourcc="", min_fps=DEFAULT_MIN_FPS, fps=None):
    """FOURCC 후보별로 가장 좋은 크기를 재고, 그중 최선의 형식을 고른다."""
    candidates = _fourcc_candidates(fourcc)
    results = []
    first = True
    for candidate in candidates:
        if not first and reopen is not None:
            fresh = reopen(cap)
            if fresh is None:
                break
            cap = fresh
        first = False
        label = candidate or "기본"
        if len(candidates) > 1:
            log(f"[카메라] {label} 포맷을 시험합니다.")
        _apply_fourcc(cap, candidate, force=True)
        cap, size, measured = probe_best_size(cap, log=log, reopen=reopen,
                                             fourcc=candidate, min_fps=min_fps, requested_fps=fps)
        if _area(size):
            results.append((candidate, size, measured))

    if not results:
        return cap, (0, 0), 0.0, _normalize_fourcc(fourcc)

    selected_fourcc, size, measured = max(results, key=lambda item: _format_rank(item, min_fps))
    cap, confirmed = _finalize_format(cap, size, selected_fourcc, fps, reopen=reopen)
    if _area(confirmed):
        size = confirmed
    if len(candidates) > 1:
        log(f"[카메라] 선택한 포맷: {selected_fourcc or '기본'} "
            f"({size[0]}x{size[1]}, 초당 {measured:.1f}장)")
    return cap, size, measured, selected_fourcc


def probe_fixed_format(cap, width, height, log=print, reopen=None, fourcc="",
                       min_fps=DEFAULT_MIN_FPS, fps=None):
    """고정 해상도는 유지하되, FOURCC가 비어 있으면 포맷 후보만 실측해 고른다."""
    requested = (int(width), int(height))
    candidates = _fourcc_candidates(fourcc)
    results = []
    first = True
    for candidate in candidates:
        if not first and reopen is not None:
            fresh = reopen(cap)
            if fresh is None:
                break
            cap = fresh
        first = False
        _apply_fourcc(cap, candidate, force=True)
        got = _try_size(cap, *requested, fps=fps, force_fps=True)
        if not _area(got):
            continue
        measured = measure_fps(cap, seconds=_PROBE_SECONDS, warmup=_PROBE_WARMUP)
        if len(candidates) > 1:
            log(f"[카메라] {candidate or '기본'} 포맷 {requested[0]}x{requested[1]} "
                f"요청 → {got[0]}x{got[1]}, 초당 {measured:.1f}장")
        results.append((candidate, got, measured))

    if not results:
        return cap, (0, 0), 0.0, _normalize_fourcc(fourcc)

    selected_fourcc, size, measured = max(
        results, key=lambda item: _fixed_format_rank(item, requested, min_fps))
    cap, confirmed = _finalize_format(cap, size, selected_fourcc, fps, reopen=reopen)
    if _area(confirmed):
        size = confirmed
    return cap, size, measured, selected_fourcc


# ----------------------- 찾아낸 값 저장/재사용 -----------------------
# 카메라마다 값이 다르고 PC마다 꽂힌 카메라가 다르므로 이 파일은 git에 넣지 않는다
# (.gitignore). 저장된 값이 실제와 다르면 apply_best_format이 스스로 다시 찾는다.

def _cache_key(index, backend_name, fourcc, fps=None):
    key_fourcc = _normalize_fourcc(fourcc) or "AUTO"
    key = f"{index}|{(backend_name or 'auto').lower()}|{key_fourcc}"
    if fps is not None:
        try:
            key += f"|fps{float(fps):g}"
        except (TypeError, ValueError):
            key += f"|fps{fps}"
    return key


def _cache_load(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _cache_entry(path, key):
    """저장해 둔 {가로, 세로, FOURCC, 실측 초당 장수}. 없거나 깨졌으면 None."""
    entry = _cache_load(path).get(key)
    if not isinstance(entry, dict):
        return None
    try:
        width, height = int(entry["width"]), int(entry["height"])
    except (KeyError, TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    try:
        fps = float(entry.get("measured_fps") or 0.0)
    except (TypeError, ValueError):
        fps = 0.0

    parts = key.split("|")
    key_fourcc = parts[2] if len(parts) >= 3 else ""
    if key_fourcc == "AUTO":
        if int(entry.get("schema", 0) or 0) < CACHE_SCHEMA:
            return None
        cached_fourcc = _normalize_fourcc(entry.get("fourcc", ""))
        if cached_fourcc not in AUTO_FOURCC_CANDIDATES:
            return None
    else:
        cached_fourcc = _normalize_fourcc(entry.get("fourcc", key_fourcc))

    return {"width": width, "height": height, "measured_fps": fps, "fourcc": cached_fourcc}


def _cache_read(path, key):
    entry = _cache_entry(path, key)
    return (entry["width"], entry["height"]) if entry else None


def _cache_write(path, key, size, fps, fourcc=""):
    data = _cache_load(path)
    data[key] = {"schema": CACHE_SCHEMA,
                 "width": int(size[0]), "height": int(size[1]),
                 "fourcc": _normalize_fourcc(fourcc),
                 "measured_fps": round(float(fps), 1),
                 "probed_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    tmp = f"{path}.tmp"
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, path)          # 쓰다 만 파일이 남지 않도록 통째로 교체
    except OSError:
        pass                           # 저장 실패는 다음 실행이 다시 찾을 뿐 — 막지 않는다


# ----------------------------- 바깥에서 쓰는 입구 -----------------------------

def apply_best_format(cap, index=0, backend_name="auto", width=None, height=None,
                      fps=None, fourcc="", min_fps=DEFAULT_MIN_FPS,
                      cache_path=CAMERA_CAPS_PATH, use_cache=True, log=print, reopen=None):
    """열려 있는 카메라에 형식을 적용하고 **(카메라, 적용된 형식)**을 돌려준다.

    width/height는 숫자여도 되고 설정 문자열("max", "1280")이어도 된다 — 설정값을 그대로
    넘길 수 있게 여기서 해석한다. 둘 중 하나만 숫자면 짝이 없으므로 양쪽 다 "가장 좋은
    크기"로 취급한다 — 가로만 정해 놓고 세로를 드라이버가 엉뚱하게 고르는 일을 막는다.

    ⚠️ 카메라는 도중에 다시 열릴 수 있다. 호출한 쪽은 **돌려받은 카메라**를 써야 한다.
    """
    cv2 = _cv2()
    width = parse_size_spec(width)
    height = parse_size_spec(height)
    requested_fourcc = _normalize_fourcc(fourcc)
    selected_fourcc = requested_fourcc
    _apply_fourcc(cap, requested_fourcc, force=True)

    want_best = width is None or height is None
    how = "fixed"
    size = (0, 0)
    measured = 0.0

    if want_best:
        key = _cache_key(index, backend_name, requested_fourcc, fps=fps)
        saved = _cache_entry(cache_path, key) if use_cache else None
        if saved:
            selected_fourcc = saved["fourcc"]
            _apply_fourcc(cap, selected_fourcc, force=True)
            cached = (saved["width"], saved["height"])
            size = _try_size(cap, *cached, fps=fps, force_fps=True)
            if size == cached:
                how = "cache"
                # 속도는 그때 재서 저장해 둔 값을 쓴다 — 여기서 다시 재면 1초를 더 쓴다.
                measured = saved["measured_fps"]
            else:
                # 저장값과 실제가 다르다 — 카메라가 바뀌었거나 다른 앱이 점유 중이다.
                log(f"[카메라] 저장된 값({cached[0]}x{cached[1]})이 맞지 않아 다시 찾습니다.")
                size = (0, 0)
        if not _area(size):
            log("[카메라] 이 웹캠에서 가장 좋은 화면을 찾는 중입니다 — 크기와 속도를 직접 "
                "재느라 수십 초 걸릴 수 있고, 찾은 값은 저장해 다음 실행부터는 건너뜁니다.")
            cap, size, measured, selected_fourcc = probe_best_format(
                cap, log=log, reopen=reopen, fourcc=requested_fourcc,
                min_fps=min_fps, fps=fps)
            how = "probe"
            if size[0] >= MIN_SANE_WIDTH and size[1] >= MIN_SANE_HEIGHT:
                _cache_write(cache_path, key, size, measured, selected_fourcc)
    else:
        cap, size, measured, selected_fourcc = probe_fixed_format(
            cap, width, height, log=log, reopen=reopen, fourcc=requested_fourcc,
            min_fps=min_fps, fps=fps)
        if size != (width, height):
            log(f"[카메라] 요청한 {width}x{height}를 이 카메라가 지원하지 않아 "
                f"{size[0]}x{size[1]}로 열렸습니다.")

    if fps is not None:
        _set_if_needed(cap, cv2.CAP_PROP_FPS, fps, force=True)
    if not _area(size):
        size = frame_size(cap)
        how = "unknown"
    try:
        driver_fps = float(cap.get(cv2.CAP_PROP_FPS))
    except Exception:
        driver_fps = 0.0
    return cap, CaptureFormat(size[0], size[1], driver_fps, how, measured, index, selected_fourcc)


def parse_index_spec(value):
    """카메라 번호 설정을 해석한다. 숫자면 int, "auto"면 None(알아서), "ask"면 ASK(물어보기).

    노트북에 외장 웹캠을 꽂으면 카메라가 두 대가 되는데, 어느 쪽이 0번인지는 OS가 정하고
    재부팅·USB 포트 변경으로 뒤바뀔 수 있다. 그래서 "번호 고정" 말고 "알아서 고르기"가 필요하다.
    """
    if value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip().lower()
    if text in ("auto", "best", ""):
        return None
    if text in ("ask", "pick", "choose"):
        return ASK            # 실행할 때마다 사람에게 창으로 물어본다
    try:
        number = int(text)
    except ValueError:
        raise ValueError(
            f"카메라 번호 설정값을 이해할 수 없습니다: {value!r}\n"
            "       0, 1, 2 같은 숫자 또는 auto(알아서 고르기) / ask(물어보기) 여야 합니다.")
    if number < 0:
        raise ValueError(f"카메라 번호는 0 이상이어야 합니다: {value!r}")
    return number


# 자동으로 고를 때 몇 번까지 열어 볼지. 웹캠을 5대씩 꽂는 구성은 이 파이프라인에 없다.
SCAN_MAX_INDEX = 5

# 설정이 "ask"일 때 쓰는 표시값(숫자 0과 헷갈리지 않게 문자열로 둔다).
ASK = "ask"


def _open_raw(factory, index, backend, cv2):
    """카메라를 **열기만** 한다(크기·속도 설정은 안 건드림). 못 열면 None.

    설정을 적용하면 이 웹캠에서 2.6초가 걸리는데 그냥 열면 1.4초다(실측 2026-09-16).
    "어떤 카메라가 꽂혀 있나"만 알고 싶을 때는 그냥 여는 쪽이 훨씬 싸다.
    """
    cap = factory(index, backend)
    if not cap.isOpened() and backend != cv2.CAP_ANY:
        cap.release()
        cap = factory(index)
    if not cap.isOpened():
        cap.release()
        return None
    return cap


def list_cameras(backend_name="auto", fourcc="", min_fps=DEFAULT_MIN_FPS, fps=None,
                 cache_path=CAMERA_CAPS_PATH, use_cache=True, log=print,
                 max_index=SCAN_MAX_INDEX, stop_after_miss=None, capture_factory=None,
                 with_preview=False, quick=False):
    """0번부터 차례로 열어 보고 **쓸 수 있는 카메라 목록**을 돌려준다.

    각 항목: {"index", "width", "height", "measured_fps", "preview"}. 못 여는 번호는 목록에
    안 들어간다. with_preview=True면 각 카메라에서 사진 한 장을 함께 받아 온다 — 선택 창에서
    "어느 쪽이 외장 웹캠인지" 눈으로 보려고 쓴다.
    stop_after_miss를 주면 그 횟수만큼 연속으로 실패했을 때 멈춘다(자동 고르기에서 시간을
    아끼려고 쓴다 — 카메라 번호는 보통 0부터 빈틈없이 붙는다).

    quick=True면 **열기만 하고 크기·속도는 설정하지 않는다**(이 웹캠 실측 2.6초 → 1.4초).
    크기·속도는 예전에 알아내 저장해 둔 값을 보여 주고, 저장된 값이 없으면 지금 나온 사진
    크기를 쓴다. "어느 카메라가 꽂혀 있나"를 물어보는 화면용이다 — 고른 뒤 실제로 쓸 때
    제대로 다시 연다.
    """
    cv2 = _cv2()
    factory = capture_factory or cv2.VideoCapture
    backend = backend_id(backend_name)
    found = []
    misses = 0
    for index in range(max_index + 1):
        # quick이라도 **처음 보는 카메라는 제대로 재야 한다** — 안 그러면 "둘 다 640x480"으로
        # 보여서 어느 쪽이 좋은 카메라인지 알 수 없고, 추천도 틀린 쪽을 가리킨다.
        saved = (_cache_entry(cache_path, _cache_key(index, backend_name, fourcc, fps=fps))
                 if (quick and use_cache) else None)
        if quick and saved is not None:
            cap = _open_raw(factory, index, backend, cv2)
            fmt = None
        else:
            if quick:
                log(f"[카메라] {index}번은 처음 보는 카메라라 성능을 재 봅니다 "
                    "— 다음부터는 저장된 값을 써서 빨라집니다.")
            cap, fmt = open_camera(index, backend_name=backend_name, fourcc=fourcc,
                                   fps=fps, min_fps=min_fps, cache_path=cache_path,
                                   use_cache=use_cache, log=lambda *_a, **_k: None,
                                   capture_factory=capture_factory)
        if cap is None:
            misses += 1
            if stop_after_miss and misses >= stop_after_miss:
                break
            continue
        misses = 0
        # 선택 창에 보여 줄 사진 한 장. 실패해도 글자 목록만으로 고를 수 있다.
        try:
            ok, frame = cap.read()
        except Exception:
            ok, frame = False, None
        preview = frame if (ok and with_preview) else None
        if fmt is None:
            width, height, measured = saved["width"], saved["height"], saved["measured_fps"]
        else:
            width, height = fmt.width, fmt.height
            measured = fmt.measured_fps or measure_fps(cap, seconds=1.0, warmup=5)
        # ⚠️ 여기서 반드시 닫는다. 하나라도 연 채로 두면 다음 번호를 확인하는 데 0.1초 대신
        # 3초가 걸린다(2026-09-16 실측 — 전체 2.7초 → 19초).
        cap.release()
        found.append({"index": index, "width": width, "height": height,
                      "measured_fps": measured, "preview": preview})
        log(f"[카메라] {index}번: {width}x{height}, 초당 {measured:.1f}장")
    return found


def pick_best_index(backend_name="auto", fourcc="", min_fps=DEFAULT_MIN_FPS, fps=None,
                    cache_path=CAMERA_CAPS_PATH, use_cache=True, log=print,
                    capture_factory=None):
    """꽂혀 있는 카메라 중 **가장 좋은 것**의 번호. 하나도 못 찾으면 None.

    고르는 기준: ① 속도 기준(min_fps)을 넘는 것 중 화면이 가장 큰 것 ② 전부 기준 미달이면
    그중 화면이 가장 큰 것 ③ 같으면 번호가 작은 쪽(보통 내장 카메라).
    """
    cams = list_cameras(backend_name=backend_name, fourcc=fourcc, min_fps=min_fps, fps=fps,
                        cache_path=cache_path, use_cache=use_cache, log=log,
                        stop_after_miss=2, capture_factory=capture_factory, quick=True)
    if not cams:
        return None
    fast = [c for c in cams if c["measured_fps"] >= min_fps] or cams
    best = max(fast, key=lambda c: (c["width"] * c["height"], -c["index"]))
    if len(cams) > 1:
        log(f"[카메라] {len(cams)}대 중 {best['index']}번을 골랐습니다 "
            f"({best['width']}x{best['height']}, 초당 {best['measured_fps']:.1f}장).")
    return best["index"]


def ask_user_to_choose(backend_name="auto", fourcc="", min_fps=DEFAULT_MIN_FPS, fps=None,
                       cache_path=CAMERA_CAPS_PATH, use_cache=True, log=print,
                       capture_factory=None):
    """꽂혀 있는 카메라를 찾아 **사람에게 창으로 물어본다**. 고른 번호(취소하면 None).

    창을 그리는 일은 camera_picker.py가 한다 — 여기서는 카메라를 찾아 넘겨줄 뿐이다.
    카메라가 한 대뿐이면 묻지 않고 그 번호를 쓴다(쓸데없이 클릭하게 만들지 않는다).

    ⚠️ 카메라를 **붙들고 있지 않는다.** "찾을 때 연 카메라를 그대로 쓰면 한 번 덜 열 텐데"
    싶지만, 실측해 보니 반대였다(2026-09-16): 카메라 하나를 연 채로 다음 번호를 확인하면
    없는 번호 하나를 판정하는 데 0.1초 → 3초로 느려져, 전체가 2.7초에서 19초가 됐다.
    그래서 **찾을 때는 다 닫고**, 고른 뒤에 다시 연다.
    """
    log("[카메라] 꽂혀 있는 카메라를 찾는 중입니다 — 잠시 걸립니다…")
    cams = list_cameras(backend_name=backend_name, fourcc=fourcc, min_fps=min_fps, fps=fps,
                        cache_path=cache_path, use_cache=use_cache,
                        log=log, capture_factory=capture_factory,
                        with_preview=True, quick=True, stop_after_miss=2)
    if not cams:
        log("[카메라] 쓸 수 있는 카메라를 찾지 못했습니다.")
        return None
    best = max(cams, key=lambda c: (c["measured_fps"] >= min_fps,
                                    c["width"] * c["height"], -c["index"]))
    import camera_picker
    chosen = camera_picker.choose(cams, recommended_index=best["index"])
    if chosen is not None:
        log(f"[카메라] {chosen}번을 선택했습니다.")
    return chosen


def open_camera(index, backend_name="auto", width=None, height=None, fps=None,
                fourcc="", min_fps=DEFAULT_MIN_FPS, cache_path=CAMERA_CAPS_PATH,
                use_cache=True, log=print, capture_factory=None):
    """카메라를 열고 형식까지 맞춰 (카메라, 적용된 형식)을 돌려준다. 실패하면 (None, None).

    backend_name으로 안 열리면 기본 백엔드(auto)로 한 번 더 시도한다.
    """
    cv2 = _cv2()
    factory = capture_factory or cv2.VideoCapture
    backend = backend_id(backend_name)
    index = parse_index_spec(index)
    if index == ASK:                       # 설정이 "ask" — 창을 띄워 사람에게 물어본다
        index = ask_user_to_choose(
            backend_name=backend_name, fourcc=fourcc, min_fps=min_fps, fps=fps,
            cache_path=cache_path, use_cache=use_cache, log=log,
            capture_factory=capture_factory)
        if index is None:
            log("[카메라] 카메라 선택이 취소됐습니다.")
            return None, None
    elif index is None:                    # 설정이 "auto" — 꽂힌 것 중 가장 좋은 걸 고른다
        index = pick_best_index(backend_name=backend_name, fourcc=fourcc, min_fps=min_fps, fps=fps,
                                cache_path=cache_path, use_cache=use_cache, log=log,
                                capture_factory=capture_factory)
        if index is None:
            log("[카메라] 쓸 수 있는 카메라를 찾지 못했습니다.")
            return None, None

    def _fresh():
        cap = factory(index, backend)
        if not cap.isOpened() and backend != cv2.CAP_ANY:
            cap.release()
            cap = factory(index)
        return cap

    cap = _fresh()
    if not cap.isOpened():
        cap.release()
        return None, None

    def _reopen(old_cap):
        """후보를 시험할 때마다 쓰는 '깨끗한 카메라' 통로 — 옛 것을 닫고 새로 연다."""
        try:
            old_cap.release()
        except Exception:
            pass
        fresh = _fresh()
        return fresh if fresh.isOpened() else None

    cap, fmt = apply_best_format(cap, index=index, backend_name=backend_name, width=width,
                                 height=height, fps=fps, fourcc=fourcc, min_fps=min_fps,
                                 cache_path=cache_path, use_cache=use_cache, log=log,
                                 reopen=_reopen)
    if fmt.width <= 0:      # 영상이 한 장도 안 나온다 — 열렸다고 말하면 안 된다
        cap.release()
        return None, None
    return cap, fmt


def preview_size(width, height, max_width, min_width=320):
    """미리보기 창을 띄울 (가로, 세로). **영상 비율을 그대로 지킨다.**

    왜 필요한가: 예전에는 창을 1280x720으로 고정해 띄웠는데, OpenCV 창은 비율을 지키지
    않고 영상을 창에 늘려 채운다. 그래서 4:3 웹캠(640x480)을 쓰면 손이 가로로 늘어나
    보였다 — 각도 계산에는 영향이 없지만 눈으로 손 모양을 확인하는 일이 어려워진다.
    반대로 아주 큰 영상은 원본 크기 창이 모니터를 넘어가므로 상한도 필요하다.
    """
    if width <= 0 or height <= 0:
        return int(max_width), int(round(max_width * 9 / 16))
    out_w = min(int(max_width), int(width))
    out_w = max(out_w, int(min_width))
    return out_w, max(1, int(round(out_w * height / width)))


def backend_names():
    """OpenCV 백엔드 이름 → 상수. 어느 OS 빌드에나 정의된 enum 값이라 전부 나열해도
    임포트 에러가 나지 않는다 — 실제로 열리는지는 OS/드라이버가 정한다."""
    cv2 = _cv2()
    return {
        "auto": cv2.CAP_ANY,
        "msmf": cv2.CAP_MSMF,                  # Windows 기본
        "dshow": cv2.CAP_DSHOW,                # Windows 레거시 — msmf가 카메라를 못 열 때
        "v4l2": cv2.CAP_V4L2,                  # Linux (/dev/video*)
        "avfoundation": cv2.CAP_AVFOUNDATION,  # macOS
        "gstreamer": cv2.CAP_GSTREAMER,        # Linux 산업용/네트워크 카메라
    }


def backend_id(name):
    """이름이 틀리면 ValueError — 오타를 auto로 조용히 바꿔치기하지 않는다."""
    table = backend_names()
    key = (name or "auto").strip().lower()
    if key not in table:
        raise ValueError(
            f"카메라 백엔드 이름이 잘못됐습니다: {name!r}\n"
            f"       사용 가능: {', '.join(table)}\n"
            "       Windows는 auto/msmf/dshow, Linux는 auto/v4l2, macOS는 auto/avfoundation.")
    return table[key]


def _main(argv):
    """`python vision/dg5f/camera_caps.py [카메라번호|--list] [--refresh] [--backend=auto] [--fourcc=MJPG]`

    `--list`: 꽂혀 있는 카메라를 모두 열어 보고 번호·크기·속도를 표로 보여 준다. 노트북에
    외장 웹캠을 꽂았을 때 **어느 번호가 어느 카메라인지** 알아내는 용도다.

    같은 웹캠도 **백엔드와 전송 포맷 조합에 따라 쓸 수 있는 크기와 속도가 완전히 달라진다**.
    FOURCC를 생략하면 기본 포맷과 MJPG를 실측해 더 나은 쪽을 자동으로 고른다.
    """
    index = 0
    backend = "auto"
    fourcc = ""
    fps = 30
    refresh = False
    show_list = False
    for arg in argv:
        if arg == "--refresh":
            refresh = True
        elif arg == "--list":
            show_list = True
        elif arg.startswith("--backend="):
            backend = arg.split("=", 1)[1]
        elif arg.startswith("--fourcc="):
            fourcc = arg.split("=", 1)[1]
        elif arg.startswith("--fps="):
            fps = float(arg.split("=", 1)[1])
        else:
            index = int(arg)

    if show_list:
        print(f"[camera_caps] 0~{SCAN_MAX_INDEX}번 카메라를 차례로 열어 봅니다 "
              f"(backend={backend}, 포맷={fourcc or '자동'}). 잠시 걸립니다…")
        print("   (없는 번호에서 OpenCV가 빨간 에러 줄을 찍는 건 정상입니다 — "
              "그 번호에 카메라가 없다는 뜻입니다.)")
        print()
        cams = list_cameras(backend_name=backend, fourcc=fourcc, fps=fps, use_cache=not refresh,
                            log=lambda *_a, **_k: None)
        if not cams:
            print("쓸 수 있는 카메라를 찾지 못했습니다.")
            print("다른 앱이 카메라를 쓰고 있지 않은지, Windows 설정 > 개인 정보 > "
                  "카메라에서 접근이 켜져 있는지 확인하세요.")
            return 1
        best = max(cams, key=lambda c: (c["width"] * c["height"], -c["index"]))
        print(f"{'번호':>4s}  {'화면 크기':>13s}  {'초당 장수':>10s}   비고")
        for c in cams:
            note = "← 가장 좋음(auto가 고르는 것)" if c is best else ""
            print(f"{c['index']:>4d}  {c['width']:>5d}x{c['height']:<6d}  "
                  f"{c['measured_fps']:>8.1f}장   {note}")
        print()
        print("원하는 번호를 레포 루트 .env에 적으면 고정됩니다:")
        print(f"    RTAUTO_VISION_CAMERA_INDEX={best['index']}")
        print("매번 알아서 고르게 하려면 숫자 대신 auto 를 적습니다:")
        print("    RTAUTO_VISION_CAMERA_INDEX=auto")
        return 0
    print(f"[camera_caps] 카메라 {index}(backend={backend}, 포맷={fourcc or '자동'})에서 "
          f"쓸 수 있는 가장 좋은 화면을 찾습니다. 저장 파일: {CAMERA_CAPS_PATH}")
    cap, fmt = open_camera(index, backend_name=backend, fourcc=fourcc, fps=fps,
                           use_cache=not refresh)
    if cap is None:
        print(f"[오류] 카메라 {index}를 열 수 없습니다. 번호를 0, 1, 2 순으로 바꿔 보세요.")
        return 1
    measured = measure_fps(cap)
    cap.release()
    print(f"[결과] {fmt.width}x{fmt.height} {fmt.fourcc or '기본 포맷'} — 실측 초당 {measured:.1f}장")
    if measured < DEFAULT_MIN_FPS:
        print(f"[경고] 초당 {measured:.1f}장은 손 동작을 따라가기에 느립니다.")
        print("       자동 탐색에서 기본 포맷과 MJPG가 모두 기준에 못 미쳤습니다.")
        print("       다른 백엔드를 시험하거나 캡처 해상도를 낮춰야 합니다.")


if __name__ == "__main__":
    import sys
    sys.exit(_main(sys.argv[1:]))
