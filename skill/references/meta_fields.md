# Meta Fields Guide — Spatiotemporal Flow (Step 3)

캡션 작성 후 메타 필드를 채운다. 장면 흐름 검색·필터링·캡션 평가의 보조 신호.

## 필드 요약

| 필드 | 종류 | Required/Nullable | 한 줄 정의 |
| --- | --- | --- | --- |
| `shot_type` | enum | **Required** | 카메라 거리/구도 |
| `motion_type` | enum | **Required** | 프레임 간 지배적인 움직임의 종류 |
| `temporal_change` | enum | **Required** | 프레임 간 변화의 크기 |
| `text_on_screen` | string list | **Nullable** | 화면 자막/배너 (1~3개, 없으면 null) |
| `mood` | multi-select | **Nullable** | 분위기 1~3개 (확신 없으면 null) |

3개 ref에서 **객관적 필드**(`shot_type`, `motion_type`, `temporal_change`)는 거의 일치해야 한다. **주관적 필드** `mood`만 변동 가능.

> "비워도 된다"는 "비워라"가 아니다. nullable 필드는 해당 없음/확신 없을 때만 비운다.

---

## 1. `shot_type` — Required, enum

카메라 거리·구도. 프레임마다 거리가 다르면 **대표(가장 많은 비중)** 기준, 단 거리 변화 자체는 `motion_type: camera_motion`으로 표시.

| 값 | 정의 |
| --- | --- |
| `closeup` | 얼굴/사물이 화면 대부분을 차지하는 매우 가까운 샷 |
| `medium` | 인물 상반신 또는 중간 거리 |
| `full` | 인물 전신 또는 대상 전체 |
| `wide` | 와이드 샷, 전경 또는 여러 인물 |
| `detail` | 특정 부분 클로즈업(소재·라벨·디테일) |
| `ots` | 어깨 너머 샷 |

## 2. `motion_type` — Required, enum

프레임을 거치며 나타나는 **지배적인 움직임**을 하나 고른다.

| 값 | 정의 | 단서 |
| --- | --- | --- |
| `static` | 프레임 간 의미 있는 움직임이 거의 없음 | 구도·인물·사물 위치가 거의 동일 |
| `subject_motion` | 인물/주체가 움직임 | 자세·위치·동작이 프레임마다 바뀜 |
| `camera_motion` | 카메라/구도가 움직임 | 줌인·줌아웃·팬·틸트로 프레임 거리/각도가 바뀜 |
| `object_motion` | 화면 속 사물·제품이 움직임 | 사람은 거의 정지인데 사물이 들리거나 회전 |
| `scene_transition` | 컷·페이드 등 장면 전환이 일어남 | 프레임 간 내용이 크게 달라지거나 검은/페이드 화면 |

**판단**: 사람과 카메라가 둘 다 움직이면 더 두드러진 쪽. 모호하면 `subject_motion` 우선, 거의 안 움직이면 `static`.

## 3. `temporal_change` — Required, enum

프레임 간 변화의 **크기**.

| 값 | 정의 |
| --- | --- |
| `none` | 변화 없음 (단일 프레임, 또는 사실상 동일한 프레임들) |
| `minor` | 작은 변화 (손 위치·표정·약간의 줌 등 부분 변화) |
| `major` | 큰 변화 (인물·구도가 뚜렷이 바뀌거나 장면 전환) |

`temporal_change: none`이면 `motion_type`은 보통 `static`.

## 4. `text_on_screen` — Nullable, string list

화면에 보이는 핵심 자막/배너/가격 1~3개. 보이는 그대로(음성·추측 금지). 프레임마다 자막이 다르면 가장 핵심적인 것 위주. 없거나 가독 불가면 `null`.

## 5. `mood` — Nullable, multi-select

씬 분위기 1~3개: `energetic` | `calm` | `luxurious` | `casual` | `warm` | `professional`. 시각 단서(조명·색감·움직임 속도·구도)로만. **확신 없으면 `null`.** 4개 이상 금지.

- ✅ 빠른 움직임 + 밝은 조명 → `energetic`
- ❌ 색상/제품 카테고리만으로 mood 추론 금지.
