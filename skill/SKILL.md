---
name: heimdex-caption-eval
description: Generate 3-reference caption labels describing the SPATIOTEMPORAL FLOW of a single live-commerce scene from its ordered keyframes. Produces JSON with 3 distinct Korean captions (each 30–80 chars, written from different temporal lenses — action/event flow, spatial & viewpoint change, whole-scene narrative arc) plus meta fields (shot_type, motion_type, temporal_change, text_on_screen, mood) per reference. The keyframes are CHRONOLOGICALLY ORDERED samples of one scene; the caption's job is to describe what happens, moves, and changes ACROSS them — not to extract product details. Use this skill whenever keyframes from one scene are uploaded and the goal is to describe how the scene unfolds over time. Trigger phrases include "이 씬 흐름 캡션", "키프레임 흐름 설명", "시공간 흐름 캡션", "장면 전개 라벨링", "describe the scene flow", "spatiotemporal caption".
---

# Heimdex Caption Eval — Spatiotemporal Flow Labeling Skill

라이브 커머스 씬의 **시간 순서대로 정렬된 키프레임 1장 이상**을 받아서, 그 장면이 **시간에 따라 어떻게 전개되는지**(누가/무엇이 움직이고, 구도가 어떻게 바뀌고, 어떤 사건이 이어지는지)를 설명하는 **3개 reference 캡션 + ref별 메타 필드** JSON을 생성한다.

이 데이터셋의 목적은 제품 정보 추출이 아니라 **장면의 시공간 흐름(spatiotemporal flow) 이해**다.

## 입력

- 같은 씬에서 **시간 순서대로** 추출된 키프레임 (보통 1~3장). 첫 이미지 = 가장 이른 시점, 마지막 이미지 = 가장 늦은 시점.
- (선택) 사용자가 `scene_id` 지정 / 파일명 사용 / 자동 부여(`scene_001`).

## 핵심 원칙 — 단일 프레임이 아니라 프레임 "사이"를 본다

이전 버전과 정반대다. 키프레임 간 변화는 버려야 할 노이즈가 **아니라** 이 데이터셋의 **메인 신호**다.

- 여러 프레임을 **시간 순서대로** 비교하며 "처음 → 중간 → 끝"에 무엇이 달라지는지 본다.
- 프레임이 1장뿐이거나 거의 동일하면 → 변화 정보가 없으므로 **공간 구성만** 묘사하고 `temporal_change`를 `none`으로 둔다.

## 워크플로우

### Step 1 — 키프레임을 시간 순서로 비교 관찰

모든 키프레임을 첫 장부터 마지막 장까지 순서대로 훑으며 정리:

- **누가/무엇이** 등장하는가, 그리고 프레임마다 그 위치·자세·존재가 어떻게 바뀌는가
- **움직임의 종류** — 인물이 움직이나, 카메라/구도가 바뀌나, 화면 속 사물이 움직이나, 장면이 전환되나, 아니면 정적인가
- **공간 관계** — 좌/우/중앙/전경/배경, 그리고 프레임 간 그 배치 변화
- **화면 텍스트** — 자막·가격·배너 (보이는 그대로, 음성·추측 금지)
- **카메라 거리/구도** — closeup / medium / full / wide / detail / ots

프레임 간 변화가 작으면 "거의 변화 없음"이라고 정직하게 적는다.

### Step 2 — 3개 캡션 작성 (서로 다른 시간적 시점)

`references/caption_writing_principles.md`를 적용한다. **반드시 3개 ref를 다른 시간적 렌즈로** 작성:

| ref | 시간적 렌즈 | 강조 | 시작 패턴 예시 |
| --- | --- | --- | --- |
| `ref_a` | **행동·사건 흐름** | 주체가 프레임을 거치며 하는 동작의 순서 | "여성이 먼저 ~하다가 이어서 ~한다" |
| `ref_b` | **공간·시점 변화** | 위치·구도·카메라가 프레임마다 어떻게 바뀌는지 | "왼쪽에 있던 ~가 중앙으로 이동하고 화면이 ~된다" |
| `ref_c` | **장면 요약 서사** | 시작→끝을 한 문장으로 압축한 전개 | "~로 시작해 ~로 마무리되는 장면" |

각 캡션은:
- **30~80자** (Unicode 글자수, 공백 포함). 검증 스크립트가 강제.
- 가능하면 시간 순서(먼저/이어서/끝에) 또는 변화(이동/전환/줌)를 드러낸다.
- 외부 지식·평가어·추측 금지. **음성·브랜드·가격 추측 금지.**
- 한국어 색상 표기 (분홍, 검정, 흰; 핑크/블랙 ❌).

3개 캡션은 **어순만 바꾸는 게 아니라** 강조하는 시간적 측면(행동 / 공간·카메라 / 요약 서사)이 달라야 한다.

### Step 3 — 메타 필드 (ref별)

`references/meta_fields.md`의 정의에 따라 채운다.

객관적 필드(`shot_type`, `motion_type`, `temporal_change`)는 같은 씬을 보므로 3개 ref에서 거의 일치해야 한다. 주관적 필드 `mood`만 ref 간 변동이 자연스럽다. `text_on_screen`은 보이는 그대로(없으면 `null`).

### Step 4 — JSON 작성

`assets/output_template.json`을 시작점으로 복사. 통합 포맷 1개 객체에 ref 3개를 모두 채운다(`scene_id`, `keyframe_paths`, `references[ref_a/b/c]`, 각 ref의 `annotator_id`=`claude_synthetic_a/b/c` + `annotated_at` ISO8601 UTC).

### Step 5 — 검증

```bash
python scripts/validate_output.py <output.json>
```

체크: 정확히 3개 ref(ref_a/b/c), 캡션 30~80자, enum 유효성(`shot_type`/`motion_type`/`temporal_change`), nullable 형식(`text_on_screen`/`mood` 1~3개 또는 null), 3개 ref 캡션 다양성.

## 시공간 그라운딩 — 환각 금지 (가장 중요)

키프레임은 연속 영상이 아니라 **드문드문한 시점 표본**이다. 보이지 않는 중간 동작을 지어내지 말 것.

- ✅ 주어진 프레임 **사이에서 실제로 보이는 변화만** 묘사한다.
- ❌ 2장만 보고 "방을 가로질러 걸어간다" 같은 연속 동작 날조 금지 (프레임 사이 경로는 알 수 없다).
- 프레임이 거의 동일 → "프레임 간 변화가 거의 없다"고 적고 공간 구성 위주로 묘사, `temporal_change: none`.
- 1장만 입력 → 시간 정보 없음. 공간 구성만 묘사, `temporal_change: none`, `motion_type: static`, `notes`에 "키프레임 1장, 시간 정보 없음".
- 음성·브랜드·가격은 화면에 보일 때만(그 경우 `text_on_screen`). 캡션에서 추측 금지.

## 흔한 실수

- **단일 프레임 묘사** → 프레임 간 변화를 안 보고 한 장만 묘사. 반드시 순서대로 비교할 것.
- **변화 날조** → 근거 없는 중간 동작 추가. 보이는 변화만.
- **3개 ref가 어순만 다름** → 행동 흐름 / 공간·카메라 변화 / 요약 서사로 시점을 명확히 분리.
- **제품 정보 과다** → 이 데이터셋은 흐름 이해용. 제품명·가격은 핵심이 아니다(보이면 `text_on_screen`).
- **objective 필드 불일치** → 같은 씬은 같은 `shot_type`/`motion_type`/`temporal_change`.
