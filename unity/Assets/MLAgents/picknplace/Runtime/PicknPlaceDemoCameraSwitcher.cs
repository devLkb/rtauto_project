using System;
using Cinemachine;
using UnityEngine;

namespace KDT.PicknPlaceTraining
{
    /// <summary>
    /// 라이브 데모(Pipeline_Demo_GraspLift)에서 전체 화면 카메라와 그랩 클로즈업 카메라를
    /// 전환한다 — GraspLift의 GraspLiftDemoCameraSwitcher와 동일한 방식(도메인 의존이 전혀
    /// 없는 순수 Cinemachine 전환 로직이라 이름만 PicknPlace로 맞춰 그대로 옮겼다): CinemachineBrain은
    /// Priority가 가장 높은 CinemachineVirtualCamera를 자동으로 활성화하므로, 전환은 선택된
    /// 카메라만 ActivePriority로 올리고 나머지는 InactivePriority로 내리는 방식으로 이뤄진다.
    /// </summary>
    public sealed class PicknPlaceDemoCameraSwitcher : MonoBehaviour
    {
        public CinemachineVirtualCamera[] cameras = Array.Empty<CinemachineVirtualCamera>();
        public string[] cameraLabels = Array.Empty<string>();
        public int defaultCameraIndex;

        [Tooltip("Game 뷰에 카메라 전환 UI(OnGUI)를 그릴지 여부")]
        public bool showCameraUI = true;

        [Tooltip("줌 슬라이더가 허용하는 FOV 범위(도) — 값이 작을수록 확대")]
        public float minFieldOfView = 15f;
        public float maxFieldOfView = 120f;

        const int ActivePriority = 20;
        const int InactivePriority = 10;

        int _activeIndex;

        public int ActiveIndex => _activeIndex;

        void Awake()
        {
            SetActiveCamera(defaultCameraIndex);
        }

        public void SetActiveCamera(int index)
        {
            if (cameras == null || index < 0 || index >= cameras.Length) return;
            for (int i = 0; i < cameras.Length; i++)
                if (cameras[i] != null)
                    cameras[i].Priority = i == index ? ActivePriority : InactivePriority;
            _activeIndex = index;
        }

        void OnGUI()
        {
            if (!showCameraUI || cameras == null || cameras.Length == 0) return;

            float panelHeight = 75 + cameras.Length * 25;
            GUILayout.BeginArea(new Rect(10, Screen.height - panelHeight - 10, 250, panelHeight), GUI.skin.box);
            GUILayout.Label("카메라");
            for (int i = 0; i < cameras.Length; i++)
            {
                string label = i < cameraLabels.Length && !string.IsNullOrEmpty(cameraLabels[i])
                    ? cameraLabels[i]
                    : (cameras[i] != null ? cameras[i].name : $"Camera {i}");
                if (GUILayout.Button(i == _activeIndex ? $"[{label}]" : label))
                    SetActiveCamera(i);
            }

            CinemachineVirtualCamera active = _activeIndex >= 0 && _activeIndex < cameras.Length
                ? cameras[_activeIndex]
                : null;
            if (active != null)
            {
                LensSettings lens = active.m_Lens;
                GUILayout.Label($"줌: {lens.FieldOfView:F0}°");
                // Slider goes wide->narrow left->right so dragging right feels like zooming in.
                float nextFov = GUILayout.HorizontalSlider(lens.FieldOfView, maxFieldOfView, minFieldOfView);
                if (!Mathf.Approximately(nextFov, lens.FieldOfView))
                {
                    lens.FieldOfView = nextFov;
                    active.m_Lens = lens;
                }
            }
            GUILayout.EndArea();
        }
    }
}
