# -*- coding: utf-8 -*-
"""다중 웹캠 캡처 매니저 — 카메라 N대를 스레드로 독립 구동.

디지털 트윈 다시점 모니터링처럼 "웹캠 여러 대를 동시에" 쓰는 용도. DG5F 손 추적
파이프라인(vision_node_dg5f.py)은 지금도 카메라 1대만 쓴다 — 이 모듈은 그걸 건드리지
않는 별도 진입점이다.

왜 카메라별로 스레드를 분리하나:
  cap.read()는 블로킹 호출이라, 한 스레드에서 N대를 순서대로 읽으면 그중 하나가
  느리거나 응답을 안 하는 순간 나머지 카메라의 프레임레이트까지 같이 떨어진다.
  카메라별 전용 스레드 + "최신 프레임 한 장"만 들고 있는 슬롯으로 분리하면, 한 대가
  느려도 나머지는 자기 프레임레이트를 유지한다 — dg5f_teleop_gui.py가 이미 쓰는
  단일 카메라 캡처 스레드 패턴을 N대로 확장한 것뿐이다.

⚠️ 카메라 형식(화면 크기·초당 장수) 적용은 camera_caps.py가 단독으로 맡는다. cap.set()의
  실제 효과는 백엔드·카메라 조합마다 다르다는 게 이미 실측돼 있어서다(이 웹캠+Windows
  MSMF는 W/H/FPS set 하나당 3.7~3.9초가 붙는데 결과는 무변화, FOURCC는 아예 무시하고
  False를 반환). 그래서 "요청은 하되 **실제로 나온 영상**으로 확인"하는 정책을 따른다 —
  요청이 반영됐다고 가정하지 않는다. 웹캠 여러 대를 한 USB 버스에 물리면 대역폭이
  모자라 크기·초당 장수가 깎이므로, 열었을 때 실제 값을 반드시 확인할 것
  (open_all() 반환값 또는 CameraStream.actual_*).
"""
import sys
import threading
import time
from pathlib import Path

import cv2
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # vision/ — cv_window(X 로 창 닫기)
import cv_window  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config.rtauto_config import (
    VISION_CAMERA_INDICES, VISION_CAMERA_WIDTH, VISION_CAMERA_HEIGHT,
    VISION_CAMERA_FPS, VISION_CAMERA_BACKEND, VISION_CAMERA_FOURCC,
    VISION_CAMERA_MIN_FPS,
)

import camera_caps

# 백엔드 이름표와 "실제로 나온 크기를 확인하는" 규칙은 camera_caps가 단독으로 소유한다 —
# 예전엔 이 파일과 vision_node_dg5f.py가 같은 표를 각자 들고 있었다(같은 값 두 번 타이핑).
BACKEND_NAMES = camera_caps.backend_names()


class CameraStream:
    """카메라 1대를 전용 스레드로 읽어 "최신 프레임 한 장"만 들고 있는다.

    capture_factory는 실물 카메라 없이 로직만 검증하는 테스트에서 cv2.VideoCapture를
    가짜 객체로 갈아끼우는 훅이다 — 운영 코드에서는 항상 기본값(cv2.VideoCapture) 그대로 쓴다.
    """

    def __init__(self, index, width=VISION_CAMERA_WIDTH, height=VISION_CAMERA_HEIGHT,
                 fps=VISION_CAMERA_FPS, backend_name=VISION_CAMERA_BACKEND,
                 fourcc=VISION_CAMERA_FOURCC, min_fps=VISION_CAMERA_MIN_FPS,
                 capture_factory=cv2.VideoCapture, log=print):
        self.index = index
        # width/height는 숫자여도 되고 설정 문자열("max")이어도 된다 — camera_caps가 해석한다.
        self._width, self._height, self._fps = width, height, fps
        self._backend_name = backend_name
        self._fourcc = fourcc
        self._min_fps = min_fps
        self._capture_factory = capture_factory
        self._log = log
        self._cap = None
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._frame = None
        self.opened = False
        self.actual_width = self.actual_height = 0
        self.actual_fps = 0.0
        self.error = ""

    def open(self):
        """카메라를 연다. 실패해도 예외를 던지지 않고 self.opened=False + self.error로 알린다 —
        호출자(MultiCameraCapture)가 한 대 실패로 전체를 멈추지 않게 하기 위함."""
        backend = BACKEND_NAMES.get(self._backend_name, cv2.CAP_ANY)
        cap = self._capture_factory(self.index, backend)
        if not cap.isOpened() and backend != cv2.CAP_ANY:
            cap.release()
            cap = self._capture_factory(self.index)
        if not cap.isOpened():
            self.error = f"카메라 {self.index}를 열 수 없습니다"
            self.opened = False
            return False
        # 화면 크기·초당 장수 적용은 camera_caps가 소유한다. 거기서 두 가지를 같이 해결한다:
        #   ① 설정이 "max"면 이 카메라가 낼 수 있는 가장 큰 크기를 찾아 쓴다(찾은 값은 저장).
        #   ② 이미 원하는 값이면 cap.set()을 아예 호출하지 않는다 — 실측(2026-09-02, 실물
        #      웹캠 + MSMF)으로 set 한 번이 ~3.5초인데, 값이 같아도 스트림을 통째로 다시
        #      열며 그 3.5초를 그대로 문다.
        # 카메라 수 × 비용이 되지 않도록 MultiCameraCapture.open_all()이 병렬로 연다.
        # 돌려받은 cap을 그대로 쓴다 — 크기 탐색 중 드라이버가 망가지면 camera_caps가
        # 카메라를 다시 열고 **새 객체**를 돌려주기 때문이다(옛 객체는 이미 닫혀 있다).
        cap, fmt = camera_caps.apply_best_format(
            cap, index=self.index, backend_name=self._backend_name,
            width=self._width, height=self._height, fps=self._fps,
            fourcc=self._fourcc, min_fps=self._min_fps, log=self._log,
            reopen=self._reopen)
        self.actual_width = fmt.width
        self.actual_height = fmt.height
        self.actual_fps = fmt.fps
        if fmt.width <= 0:          # 영상이 한 장도 안 나온다 — 열렸다고 말하면 안 된다
            self.error = f"카메라 {self.index}에서 영상이 오지 않습니다"
            cap.release()
            self.opened = False
            return False
        self._cap = cap
        self.opened = True
        return True

    def _reopen(self, old_cap):
        """크기 탐색 중 드라이버가 망가졌을 때 같은 카메라를 새로 여는 통로."""
        try:
            old_cap.release()
        except Exception:
            pass
        backend = BACKEND_NAMES.get(self._backend_name, cv2.CAP_ANY)
        fresh = self._capture_factory(self.index, backend)
        return fresh if fresh.isOpened() else None

    def start(self):
        if not self.opened:
            raise RuntimeError(f"카메라 {self.index}: open()에 성공해야 start() 가능")
        self._thread = threading.Thread(target=self._loop, daemon=True, name=f"cam{self.index}")
        self._thread.start()

    def _loop(self):
        while not self._stop.is_set():
            ok, frame = self._cap.read()
            if ok:
                with self._lock:
                    self._frame = frame
            else:
                time.sleep(0.01)  # 일시적 read 실패로 폴링만 도는 것 방지

    def read(self):
        """최신 프레임(아직 없으면 None) — non-blocking, 캡처 스레드와 락으로만 동기화."""
        with self._lock:
            return self._frame

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self._cap is not None:
            self._cap.release()
        self.opened = False


class MultiCameraCapture:
    """카메라 여러 대를 한 번에 열고/읽고/닫는다. 일부가 실패해도 나머지는 계속 돈다."""

    def __init__(self, indices=None, capture_factory=cv2.VideoCapture, **stream_kwargs):
        self.indices = list(indices) if indices is not None else list(VISION_CAMERA_INDICES)
        self._capture_factory = capture_factory
        self._stream_kwargs = stream_kwargs
        self.streams = {}

    def open_all(self):
        """카메라마다 open을 시도한다. 실패한 것도 self.streams에 남겨(opened=False)
        나중에 .error로 사유를 확인할 수 있게 한다. 반환값: {index: 성공여부}.

        ⚠️ 카메라별로 스레드를 나눠 **동시에** connect한다 — 순차로 열면 안 되는 이유는
        실측으로 확인됐다: 이 웹캠(Windows MSMF)은 cap.set(W/H/FPS/BUFFERSIZE) 협상에
        카메라 1대당 ~14초가 걸린다(calibrate_dg5f.py 주석의 "set 하나당 3.7~3.9초" 실측과
        같은 현상). 순차로 열면 3대에 40초 넘게 걸려 사실상 못 쓴다 — 스레드로 병렬화하면
        전체 시간이 "합"이 아니라 "가장 느린 카메라 1대" 수준으로 줄어든다.
        """
        for idx in self.indices:
            self.streams[idx] = CameraStream(
                idx, capture_factory=self._capture_factory, **self._stream_kwargs)
        threads = [threading.Thread(target=s.open, name=f"open-cam{idx}")
                   for idx, s in self.streams.items()]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return {idx: s.opened for idx, s in self.streams.items()}

    def start_all(self):
        for s in self.streams.values():
            if s.opened:
                s.start()

    def read_all(self):
        """{index: frame(np.ndarray) or None} — 못 연 카메라는 항상 None."""
        return {idx: (s.read() if s.opened else None) for idx, s in self.streams.items()}

    def any_opened(self):
        return any(s.opened for s in self.streams.values())

    def all_opened(self):
        return bool(self.streams) and all(s.opened for s in self.streams.values())

    def stop_all(self):
        for s in self.streams.values():
            if s.opened:
                s.stop()


def main():
    """스탠드얼론 스모크 테스트: config에 설정된 카메라들을 열어 각각 미리보기 창에 띄운다.

    카메라가 하나도 물려 있지 않아도 죽지 않고 실패 사유를 그대로 출력한다 — 물리
    카메라가 없는 개발 PC에서도 "인덱스 목록 파싱이 맞는지/설정이 읽히는지"는 이걸로
    확인할 수 있다. 종료: 아무 미리보기 창에서 q.
    """
    mgr = MultiCameraCapture()
    print(f"[multi_camera] 시도할 인덱스: {mgr.indices}")
    opened = mgr.open_all()
    for idx, ok in opened.items():
        s = mgr.streams[idx]
        if ok:
            print(f"[multi_camera] 카메라 {idx} 열림 — {s.actual_width}x{s.actual_height} "
                  f"@ {s.actual_fps:.1f}fps")
        else:
            print(f"[multi_camera] 카메라 {idx} 실패 — {s.error}")
    if not mgr.any_opened():
        print("[multi_camera] 열린 카메라가 없습니다. 종료.")
        return
    mgr.start_all()
    try:
        while True:
            shown = []
            for idx, frame in mgr.read_all().items():
                if frame is not None:
                    cv2.imshow(f"cam{idx}", frame)
                    shown.append(f"cam{idx}")
            if cv2.waitKey(1) & 0xFF == ord("q") or cv_window.closed(*shown):
                break
    finally:
        mgr.stop_all()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
