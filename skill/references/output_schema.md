# Output Schema — Spatiotemporal Flow (Step 4)

통합 포맷(`captions_combined`) 단일 객체 — 한 씬에 3개 ref가 `references` 배열에 들어 있다.

## 스키마

```json
{
  "scene_id": "string (Required)",
  "keyframe_paths": ["string", "..."],
  "references": [
    {
      "ref_id": "ref_a | ref_b | ref_c (Required)",
      "annotator_id": "string (Required, e.g. claude_synthetic_a)",
      "annotated_at": "ISO8601 UTC string (Required)",
      "caption": "string, 30~80 Unicode chars (Required)",
      "shot_type": "closeup | medium | full | wide | detail | ots (Required)",
      "motion_type": "static | subject_motion | camera_motion | object_motion | scene_transition (Required)",
      "temporal_change": "none | minor | major (Required)",
      "text_on_screen": ["string", "..."] | null,
      "mood": ["energetic | calm | luxurious | casual | warm | professional", "..."] | null,
      "notes": "string"
    }
    // ref_b, ref_c 동일 구조
  ]
}
```

## ref 시점 매핑

| `ref_id` | 시간적 렌즈 | `annotator_id` |
| --- | --- | --- |
| `ref_a` | 행동·사건 흐름 | `claude_synthetic_a` |
| `ref_b` | 공간·시점 변화 | `claude_synthetic_b` |
| `ref_c` | 장면 요약 서사 | `claude_synthetic_c` |

ref_id 순서는 항상 a → b → c. 시점이 정해져 있으므로 배열 순서를 바꾸지 말 것.

## 다중 씬 wrapper (Optional)

```json
{ "scenes": [ { "scene_id": "...", "keyframe_paths": [...], "references": [...] } ] }
```

검증 스크립트는 단일 씬 객체와 wrapper 둘 다 받는다.
