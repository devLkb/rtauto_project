## 작업 목표

`Grasp` 브랜치에서 **DG5F 로봇 핸드를 이용하여 물체를 파지(Grasp)하고 들어 올리는(Lift) 단계까지 수행하는 강화학습 모델을 구현하라.**

### 작업 수행 방식

* **Worker는 Codex를 사용하라.**
* 메인 에이전트는 작업을 분석하고 계획한 뒤, 실제 코드 탐색·수정·구현 작업은 Codex worker에게 적극적으로 위임하라.
* 현재 작업 대상 브랜치는 `Grasp`이다.
* 다른 브랜치에 작업하지 말고 `Grasp` 브랜치를 기준으로 구현하라.

---

## 참고 구현

아래 Isaac Lab 기반 DG5F 강화학습 프로젝트의 코드를 분석하고 참고하라.

Repository:

`https://github.com/VAlikV/IsaacLab_delto_envs`

특히 DG5F를 이용한 물체 조작, Grasp, Lift와 관련된 다음 요소들을 중점적으로 분석하라.

* Observation 구성
* Action 구성
* Reward 설계
* Grasp 성공 판정
* Lift 성공 판정
* Episode 종료 조건
* Reset 조건
* 물체와 손 사이 거리 계산
* 손가락 접촉 및 파지 판정 방식
* 물체를 들어 올렸는지 판단하는 기준
* PPO 학습에 필요한 환경 구성

단, **해당 Repository의 코드는 Isaac Sim / Isaac Lab용 코드이므로 그대로 복사해서 사용해서는 안 된다.**

우리 프로젝트는

* Unity
* Unity ML-Agents
* DG5F
* PPO

환경을 사용하고 있다.

따라서 Isaac Lab 코드에서는 **강화학습의 논리와 설계 방식만 참고하고**, 실제 구현은 현재 Unity 프로젝트와 ML-Agents 구조에 맞게 다시 작성하라.

---

# 중요: 기존 프로젝트 코드에 얽매이지 말 것

현재 프로젝트에 존재하는 기존 강화학습 코드와 강화학습 구조는 **무시하거나 폐기해도 된다.**

기존 코드의 구조를 유지하기 위해 비정상적인 우회 구현을 하지 마라.

Isaac Lab 구현과 현재 Unity 환경을 분석한 결과 더 적절한 구조가 있다면 기존 코드를 수정하거나 제거하고 **Grasp + Lift 학습에 적합한 구조로 새로 구현해도 된다.**

단, DG5F 로봇 모델 및 Unity 프로젝트 자체에서 반드시 필요한 구성요소까지 무작정 제거해서는 안 된다.

---

# 학습 목표

에이전트의 최종 행동 순서는 다음과 같다.

`물체 접근 → 손가락 파지 → 안정적인 Grasp → 물체 Lift`

이번 `Grasp` 브랜치에서는 최소한 **파지 성공 후 물체를 실제로 들어 올리는 것까지 학습 가능해야 한다.**

단순히 손가락을 닫았다고 Grasp 성공으로 판단하지 마라.

실제로 물체가 손에 의해 안정적으로 구속되어 있어야 하며, 이후 손 또는 로봇팔이 상승했을 때 물체가 함께 상승해야 한다.

---

# 학습 Object 변경 허용

현재 Scene에서 사용 중인 **공 형태의 Object가 DG5F에 비해 너무 작아 안정적인 파지가 어려울 경우 해당 Object를 그대로 사용할 필요가 없다.**

필요하다면 학습에 적합한 크기의 **Cube Object를 새로 생성하여 학습 대상으로 사용하라.**

Cube의 크기는 다음 요소를 고려하여 결정하라.

* DG5F 손 크기
* 손가락 사이 간격
* 파지 가능한 범위
* Collider 크기
* 물리 시뮬레이션 안정성
* 너무 쉽게 잡히거나 너무 어렵게 잡히지 않는 크기

적당한 크기를 코드와 Scene 구조를 분석하여 합리적으로 결정하라.

필요하다면 Cube의

* Rigidbody
* Collider
* Mass
* Friction
* 위치 초기화 범위

등도 학습에 적합하도록 설정하라.

---

# Reward 설계

Isaac Lab의 DG5F Grasp/Lift 구현을 참고하되 Unity ML-Agents에 맞는 Reward를 설계하라.

최소한 다음 상태를 고려하라.

### 1. Object 접근

손 또는 적절한 기준점과 Object 사이의 거리가 감소하면 보상을 줄 수 있다.

단, 기존 Reach 학습 구조를 반드시 유지할 필요는 없다.

### 2. Grasp

단순히 손가락을 닫는 행동 자체에는 큰 보상을 주지 마라.

Object와 실제 접촉하면서 파지에 성공했는지를 판정해야 한다.

가능하다면 여러 손가락 또는 손바닥과의 접촉 상태, Object의 상대 위치 등을 이용하여 잘못된 Grasp 판정을 방지하라.

### 3. Lift

Grasp 이후 Object의 높이가 초기 높이보다 증가하면 보상을 제공하라.

목표 높이 이상 안정적으로 들어 올렸을 경우 큰 성공 보상을 제공하라.

### 4. 잘못된 행동

필요하다면 다음에 대해 패널티를 적용하라.

* Object를 멀리 밀어냄
* Object를 떨어뜨림
* 비정상적인 과도한 움직임
* Grasp 없이 팔만 상승
* Object가 학습 가능 영역 밖으로 이동

Reward 값은 임의로 결정하고 끝내지 말고, 각 Reward가 왜 필요한지 코드 주석 또는 문서로 설명하라.

---

# Observation / Action

현재 프로젝트의 DG5F 구조를 먼저 확인하고 Observation과 Action을 설계하라.

현재 프로젝트의 물리 관절 구조와 실제 ML-Agents Action 구조가 다를 수 있으므로 이를 반드시 확인하라.

불필요하게 Observation 차원을 크게 만들지 말고 **Grasp + Lift에 실제로 필요한 정보 중심으로 구성하라.**

예를 들면 다음 정보들을 검토할 수 있다.

* 로봇 관절 상태
* 손/손바닥 위치
* Object 위치
* Object 회전
* Object 속도
* Object와 손의 상대 위치
* Object와 손의 상대 거리
* 손가락 접촉 상태
* Grasp 여부
* Object의 초기 높이 대비 현재 높이

단, 위 목록을 그대로 구현하라는 의미가 아니다.

Isaac Lab 구현과 현재 Unity 프로젝트를 분석한 뒤 필요한 정보만 선택하라.

---

# Episode / Reset

학습이 안정적으로 이루어질 수 있도록 Episode 종료 조건과 Reset 로직도 구현하라.

예:

성공:

* Object를 목표 높이까지 들어 올리고 일정 조건을 만족

실패:

* Object를 떨어뜨림
* Object가 작업 공간을 크게 벗어남
* 제한 시간 초과
* 회복 불가능한 로봇 상태

Reset 시에는

* Robot joint
* DG5F finger 상태
* Object 위치
* Object rotation
* Rigidbody velocity / angular velocity

등 학습에 영향을 주는 상태가 정상적으로 초기화되는지 확인하라.

---

# 구현 시 주의사항

1. Isaac Lab 코드를 그대로 포팅하지 마라.
2. Isaac Lab의 Reward/Observation/Termination 설계 의도를 이해한 후 Unity ML-Agents 방식으로 변환하라.
3. 기존 강화학습 코드와 구조를 반드시 유지할 필요는 없다.
4. 현재 코드가 잘못 설계되어 있다면 과감하게 수정하라.
5. 학습이 실제로 실행될 수 있는 상태까지 구현하라.
6. 단순 컴파일 성공을 완료 기준으로 삼지 마라.
7. NullReference, 잘못된 Collider 감지, Rigidbody 초기화 문제 등 Unity에서 발생할 수 있는 오류를 점검하라.
8. Behavior Parameters와 ML-Agents trainer 설정도 현재 Observation/Action 구조와 일치하는지 확인하라.
9. 필요하다면 YAML PPO 설정도 수정하거나 새로 작성하라.
10. 기존 Reach 단계 구현이 방해된다면 재사용하지 않아도 된다.

---

# 완료 후 보고

작업이 끝나면 다음 내용을 정리하여 보고하라.

1. 변경/추가한 파일
2. 삭제하거나 사용하지 않게 된 기존 코드
3. Observation 구성

   * 각 값의 의미
   * 전체 Observation 차원
4. Action 구성

   * 각 Action의 의미
   * 전체 Action 차원
5. Reward 구성

   * 각 Reward 수식 또는 계산 방식
   * 각 Reward가 필요한 이유
6. Grasp 성공 판정 방식
7. Lift 성공 판정 방식
8. Episode 성공/실패/Timeout 조건
9. Reset 과정
10. Cube를 새로 만들었다면

    * 크기
    * Mass
    * Collider
    * Rigidbody/물리 설정
    * 해당 크기를 선택한 이유
11. ML-Agents PPO YAML 변경사항
12. 실제 학습 실행 명령어
13. 구현하면서 발견한 기존 코드의 문제점
14. 아직 남아 있는 문제나 추가 검증이 필요한 부분

가장 중요한 것은 **기존 코드를 최소 수정하는 것이 아니라, DG5F가 Unity ML-Agents 환경에서 실제로 Grasp → Lift를 학습할 수 있는 구조를 만드는 것**이다.
