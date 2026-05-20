本章目标字数（参考）: {target_chapter_words}

### 章节大纲（原文）
{outline}

### 输出格式（严格遵守）
只输出一个 JSON 对象，顶层键为 `atoms`（数组）。数组元素为对象，必填字段：
- `id`：字符串，如 b1、b2……
- `intent`：字符串，概括该叙事单元必须完成的推进（局势/事件/信息变化）

可选字段：
- `weight`：正数，相对字数权重。
- `extensions`：对象，建议包含：
  - `focus`：action/dialogue/suspense/emotion/sensory/power_reveal/cultivation/pacing 之一；
  - `scene_type`：normal/combat/dialogue/reveal/cultivation/transition 之一；
  - `completion_check`：这一拍写完时必须能检查到的结果；
  - `must_include`：必须出现的动作、信息或后果；
  - `avoid`：本拍要避免的水分、AI味或跑偏方式。

### 自检
- 每个 intent 是否都能回答「这一小段写完，读者对剧情或局势多了什么新信息」？
- 是否避免了「按句号个数当拍数」？
- 是否按 {target_chapter_words} 字预算动态决定了拍数，而不是固定套起承转合？
- 如果含战斗，是否拆成动作链，并要求碰撞、后果、反制，而不是环境和心理说明？
