// DemoUiLayout.cs
// 시연 씬 HUD(OnGUI 박스)들이 서로 겹치지 않게 쌓아주는 공용 배치기.
//
// 왜 필요한가: 각 컴포넌트가 `new Rect(Screen.width - 250, 194, ...)`처럼 자기 y좌표를
// 직접 박아 두면, 다른 패널의 높이가 바뀌거나 패널이 하나 늘어날 때마다 나머지 전부의
// 좌표를 손으로 다시 맞춰야 한다. 실제로 이 저장소에서 그 방식으로 여러 번 겹쳤다
// (Dg5fSender.OnGUI 주석의 "2026-09-01에 실제로 겹쳐 있던 것을 바로잡았다", 그리고
// 팔 관절 패널이 화면 오른쪽 전체를 덮어 그 아래 네 개 패널을 전부 가리던 문제).
// 좌표를 계산으로 뽑으면 그 부류의 버그가 구조적으로 사라진다.
//
// 배치 규칙 — 손/모드는 왼쪽, 팔/URSim은 오른쪽:
//   Left()  : 제어 모드, DG5F 손 관련 패널
//   Right() : UR16e 팔 관절 · URSim 연동 패널
// 각 패널은 자기 높이만 알려주면 되고, 호출 순서대로 위에서 아래로 쌓인다.
//
// IMGUI는 한 프레임에 OnGUI를 여러 번(Layout / Repaint / 입력 이벤트) 호출하므로
// 프레임 번호만으로 초기화하면 두 번째 패스에서 좌표가 어긋난다 — (프레임, 이벤트 종류)가
// 바뀔 때 초기화한다.
//
// 아직 옮기지 않은 것: HandSliderUI·ArmTargetIK(둘 다 프리뷰 씬 전용, 폭 320으로 이
// 열 폭보다 넓다). Pipeline_Demo_GraspLift에는 더 이상 붙지 않아 여기 패널들과 겹칠 일이
// 없어서 그대로 뒀다 — 프리뷰 씬에 패널이 더 붙는 날 함께 옮길 것.

using UnityEngine;

public static class DemoUiLayout
{
    public const float LeftWidth = 280f;
    public const float RightWidth = 264f;
    const float Margin = 10f;
    const float Gap = 6f;

    static int _frame = -1;
    static EventType _event = EventType.Ignore;
    static float _leftY;
    static float _rightY;

    /// 왼쪽 열에 height 높이의 패널 자리를 하나 잡는다.
    public static Rect Left(float height)
    {
        BeginPassIfNeeded();
        Rect r = new Rect(Margin, _leftY, LeftWidth, height);
        _leftY += height + Gap;
        return r;
    }

    /// 오른쪽 열에 height 높이의 패널 자리를 하나 잡는다.
    public static Rect Right(float height)
    {
        BeginPassIfNeeded();
        Rect r = new Rect(Screen.width - RightWidth - Margin, _rightY, RightWidth, height);
        _rightY += height + Gap;
        return r;
    }

    /// 오른쪽 열에서 지금 위치부터 화면 바닥까지 남은 높이. 스크롤뷰를 가진 큰 패널이
    /// "필요한 만큼, 단 화면을 넘지 않게" 잡을 때 쓴다.
    public static float RightRemaining()
    {
        BeginPassIfNeeded();
        return Mathf.Max(120f, Screen.height - Margin - _rightY);
    }

    /// 왼쪽 열의 남은 높이. Right쪽과 같은 용도.
    public static float LeftRemaining()
    {
        BeginPassIfNeeded();
        return Mathf.Max(120f, Screen.height - Margin - _leftY);
    }

    static void BeginPassIfNeeded()
    {
        EventType type = Event.current != null ? Event.current.type : EventType.Ignore;
        if (Time.frameCount == _frame && type == _event) return;
        _frame = Time.frameCount;
        _event = type;
        _leftY = Margin;
        _rightY = Margin;
    }
}
