using UnityEngine;
using UnityEngine.InputSystem;

namespace KDT.PicknPlaceTraining
{
    /// <summary>
    /// 라이브 데모(Pipeline_Demo_GraspLift)의 유일한 카메라 — Main Camera에 직접 붙어 그 transform을
    /// Unity Scene 뷰의 플라이스루 조작과 동일한 방식으로 움직인다: 우클릭 드래그로 시점 회전, WASD로
    /// 바라보는 방향 기준 이동, Q/E(또는 Ctrl/Space)로 수직 이동, 휠로 이동 속도 조절.
    /// ProjectSettings의 activeInputHandler가 "Input System Package (New)" 전용(1)이라
    /// UnityEngine.Input(레거시)은 런타임에 예외를 던진다 — 반드시 UnityEngine.InputSystem의
    /// Keyboard.current/Mouse.current로 읽는다.
    /// </summary>
    public sealed class PicknPlaceFreeFlyCamera : MonoBehaviour
    {
        [Tooltip("이동 속도[m/s]")]
        public float moveSpeed = 1.5f;
        [Tooltip("Shift를 누르고 있을 때 이동 속도 배율")]
        public float sprintMultiplier = 3f;
        [Tooltip("마우스 우클릭 드래그 회전 감도")]
        public float lookSensitivity = 3f;
        public float minMoveSpeed = 0.2f;
        public float maxMoveSpeed = 10f;

        float _yaw;
        float _pitch;
        bool _looking;

        void Start()
        {
            Vector3 euler = transform.eulerAngles;
            _yaw = euler.y;
            _pitch = euler.x;
        }

        void Update()
        {
            Keyboard keyboard = Keyboard.current;
            Mouse mouse = Mouse.current;
            if (keyboard == null || mouse == null) return;

            if (mouse.rightButton.wasPressedThisFrame) StartLooking();
            else if (mouse.rightButton.wasReleasedThisFrame) StopLooking();

            if (_looking)
            {
                // 레거시 Input.GetAxis("Mouse X/Y")의 기본 감도(0.1)와 체감이 비슷하도록 맞춘 배율.
                Vector2 delta = mouse.delta.ReadValue() * 0.1f;
                _yaw += delta.x * lookSensitivity;
                _pitch -= delta.y * lookSensitivity;
                _pitch = Mathf.Clamp(_pitch, -89f, 89f);
                transform.rotation = Quaternion.Euler(_pitch, _yaw, 0f);
            }

            // 플랫폼마다 스크롤 한 칸의 크기가 달라 부호만 사용한다(값 그대로 쓰면 한 칸에 속도가
            // 과도하게 튐).
            float scroll = mouse.scroll.ReadValue().y;
            if (Mathf.Abs(scroll) > 0.01f)
                moveSpeed = Mathf.Clamp(moveSpeed * (1f + Mathf.Sign(scroll) * 0.1f), minMoveSpeed, maxMoveSpeed);

            bool sprint = keyboard.leftShiftKey.isPressed || keyboard.rightShiftKey.isPressed;
            float speed = moveSpeed * (sprint ? sprintMultiplier : 1f);

            Vector3 move = Vector3.zero;
            if (keyboard.wKey.isPressed) move += transform.forward;
            if (keyboard.sKey.isPressed) move -= transform.forward;
            if (keyboard.aKey.isPressed) move -= transform.right;
            if (keyboard.dKey.isPressed) move += transform.right;
            if (keyboard.eKey.isPressed || keyboard.spaceKey.isPressed) move += Vector3.up;
            if (keyboard.qKey.isPressed || keyboard.leftCtrlKey.isPressed) move -= Vector3.up;

            if (move.sqrMagnitude > 1e-6f)
                transform.position += move.normalized * speed * Time.deltaTime;
        }

        void StartLooking()
        {
            _looking = true;
            Cursor.lockState = CursorLockMode.Locked;
            Cursor.visible = false;
        }

        void StopLooking()
        {
            _looking = false;
            Cursor.lockState = CursorLockMode.None;
            Cursor.visible = true;
        }

        void OnDisable()
        {
            if (_looking) StopLooking();
        }

        void OnGUI()
        {
            const float width = 420f;
            GUILayout.BeginArea(new Rect((Screen.width - width) / 2f, 10, width, 45), GUI.skin.box);
            GUILayout.Label($"자유 시점 — 우클릭 드래그: 회전 / WASD: 이동 / Q,E: 상하 / Shift: 가속 / 휠: 속도({moveSpeed:F1}m/s)");
            GUILayout.EndArea();
        }
    }
}
