# -*- coding: utf-8 -*-
"""카메라를 **눈으로 보고 고르는 창**. 찾아낸 카메라 목록을 띄우고 하나를 고르게 한다.

왜 있나 (2026-09-16): 노트북에 외장 웹캠을 꽂으면 카메라가 두 대가 되는데, 어느 쪽이
0번인지는 OS가 정하고 재부팅·USB 포트 변경으로 뒤바뀐다. 번호를 `.env`에 적어 두는
방법만으로는 **시연 직전에 바꾸기가 불편하다** — 파일을 열어 고치고 다시 실행해야 한다.

무엇을 쓰나: 파이썬에 기본으로 들어 있는 tkinter만 쓴다(새로 설치할 것 없음). 각 카메라에서
미리 받아 둔 사진 한 장을 함께 보여 주므로 **어느 쪽이 외장 웹캠인지 화면을 보고 안다**.
사진 표시는 Pillow(PIL)가 있으면 쓰고, 없으면 글자 목록만 보여 준다 — 어느 쪽이든 고르기는
된다. 창을 띄울 수 없는 환경(화면 없는 리눅스 등)에서는 터미널에 번호를 물어본다.

이 파일은 **화면만** 담당한다 — 카메라를 찾고 여는 일은 camera_caps.py가 한다.
"""
import sys

# 창 크기 — 사진 미리보기 폭에 목록 너비를 더한 값. 화면이 작은 노트북도 고려한 크기다.
PREVIEW_W = 320

#: `choose(..., allow_rescan=True)` 에서 사람이 "다시 찾기"를 눌렀을 때 돌려주는 값.
RESCAN = "rescan"
WINDOW_MIN_W, WINDOW_MIN_H = 620, 360


def describe(cam, recommended_index=None):
    """목록 한 줄에 보여 줄 글. 사람이 읽고 바로 고를 수 있게 쓴다."""
    mark = "  ← 추천" if cam["index"] == recommended_index else ""
    saved = "  (저장된 값)" if cam.get("cached") else ""
    return (f"{cam['index']}번  —  {cam['width']}x{cam['height']}, "
            f"초당 {cam['measured_fps']:.0f}장{saved}{mark}")


def choose(cams, recommended_index=None, title="사용할 카메라를 고르세요", allow_rescan=False):
    """카메라 목록을 보여 주고 고른 번호를 돌려준다. 취소하면 None.

    cams: camera_caps.list_cameras()가 준 목록. 각 항목에 "preview"(사진, 없어도 됨)가
    있으면 함께 보여 준다.
    allow_rescan=True 면 "다시 찾기" 버튼(터미널에선 r)이 생기고, 누르면 `RESCAN` 을 돌려준다
    — 저장된 값으로 만든 빠른 목록에서 쓴다. 이때는 한 대뿐이어도 창을 띄운다(다른 카메라를
    새로 꽂았을 수 있으므로).
    """
    if not cams:
        return None
    if len(cams) == 1 and not allow_rescan:
        return cams[0]["index"]          # 고를 게 하나뿐이면 묻지 않는다
    try:
        return _choose_with_window(cams, recommended_index, title, allow_rescan)
    except Exception as e:                # 화면이 없거나 tkinter가 없는 환경
        print(f"[카메라] 선택 창을 띄울 수 없어 터미널로 묻습니다 ({type(e).__name__})")
        if allow_rescan:
            return _choose_in_terminal(cams, recommended_index, allow_rescan)
        return _choose_in_terminal(cams, recommended_index)


def _choose_in_terminal(cams, recommended_index, allow_rescan=False):
    """창을 못 띄울 때의 대비책 — 번호를 타이핑해 고른다."""
    print("\n사용할 카메라를 고르세요:")
    for cam in cams:
        print("   " + describe(cam, recommended_index))
    default = recommended_index if recommended_index is not None else cams[0]["index"]
    hint = ", r = 다시 찾기" if allow_rescan else ""
    try:
        answer = input(f"번호 입력 (그냥 Enter = {default}번{hint}): ").strip()
    except EOFError:
        return default
    if not answer:
        return default
    if allow_rescan and answer.lower() == "r":
        return RESCAN
    valid = {str(c["index"]) for c in cams}
    return int(answer) if answer in valid else default


def _to_photo(preview):
    """사진(BGR 배열)을 tkinter가 그릴 수 있는 형식으로. Pillow가 없으면 None."""
    if preview is None:
        return None
    try:
        from PIL import Image, ImageTk
    except ImportError:
        return None
    rgb = preview[:, :, ::-1]                       # OpenCV는 파랑·초록·빨강 순서다
    img = Image.fromarray(rgb)
    scale = PREVIEW_W / max(1, img.width)
    img = img.resize((PREVIEW_W, max(1, int(img.height * scale))))
    return ImageTk.PhotoImage(img)


def _choose_with_window(cams, recommended_index, title, allow_rescan=False):
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title(title)
    root.minsize(WINDOW_MIN_W, WINDOW_MIN_H)

    chosen = {"index": None}
    photos = {}                                      # 파이썬이 사진을 지우지 않게 붙들어 둔다

    frame = ttk.Frame(root, padding=12)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="어느 카메라를 쓸지 고르세요. 목록을 누르면 사진이 바뀝니다.",
              font=("", 10)).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

    listbox = tk.Listbox(frame, height=max(3, len(cams)), exportselection=False,
                         font=("", 11), activestyle="dotbox")
    for cam in cams:
        listbox.insert("end", describe(cam, recommended_index))
    listbox.grid(row=1, column=0, sticky="nsew", padx=(0, 12))

    preview_label = ttk.Label(frame, text="(사진 없음)", anchor="center",
                              relief="groove", width=30)
    preview_label.grid(row=1, column=1, sticky="nsew")
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(1, weight=1)

    def show_preview(_event=None):
        sel = listbox.curselection()
        if not sel:
            return
        cam = cams[sel[0]]
        photo = photos.get(cam["index"])
        if photo is None:
            photo = _to_photo(cam.get("preview"))
            photos[cam["index"]] = photo
        if photo is None:
            why = ("빠른 목록이라 사진 없음" if cam.get("cached")
                   else "사진 없음 — Pillow 미설치")
            preview_label.configure(image="", text=f"({why})")
        else:
            preview_label.configure(image=photo, text="")

    def accept(_event=None):
        sel = listbox.curselection()
        chosen["index"] = cams[sel[0]]["index"] if sel else recommended_index
        root.destroy()

    def cancel(_event=None):
        chosen["index"] = None
        root.destroy()

    buttons = ttk.Frame(frame)
    buttons.grid(row=2, column=0, columnspan=2, sticky="e", pady=(10, 0))
    ttk.Button(buttons, text="이 카메라로 시작", command=accept).pack(side="left", padx=4)
    if allow_rescan:
        def rescan():
            chosen["index"] = RESCAN
            root.destroy()
        ttk.Button(buttons, text="다시 찾기(사진 포함, 느림)",
                   command=rescan).pack(side="left", padx=4)
    ttk.Button(buttons, text="취소", command=cancel).pack(side="left")

    listbox.bind("<<ListboxSelect>>", show_preview)
    listbox.bind("<Double-Button-1>", accept)
    root.bind("<Return>", accept)
    root.bind("<Escape>", cancel)
    root.protocol("WM_DELETE_WINDOW", cancel)

    # 추천 카메라를 미리 골라 둔다 — Enter만 쳐도 바로 시작되게.
    start = next((i for i, c in enumerate(cams) if c["index"] == recommended_index), 0)
    listbox.selection_set(start)
    listbox.see(start)
    show_preview()

    root.update_idletasks()
    root.eval("tk::PlaceWindow . center")
    listbox.focus_set()
    root.mainloop()
    return chosen["index"]


if __name__ == "__main__":       # 창만 따로 띄워 보는 용도(카메라 없이 모양 확인)
    demo = [{"index": 0, "width": 640, "height": 480, "measured_fps": 30.0, "preview": None},
            {"index": 1, "width": 1920, "height": 1080, "measured_fps": 30.0, "preview": None}]
    print("고른 번호:", choose(demo, recommended_index=1))
    sys.exit(0)
