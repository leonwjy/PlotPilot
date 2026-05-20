# 单节拍整章生成策略

## 策略

默认将「章纲节拍划分」从多节拍拆分改为单节拍整章扩写。

新的默认链路是：

```text
章节大纲
-> CPMS: outline-single-beat-plan
-> ChapterExecutionPlan(atoms=1)
-> CPMS: chapter-single-beat-instructions
-> CPMS: chapter-generation-main / workflow-chapter-generation
-> 正文生成
```

代码只负责选择模式、渲染提示词、校验 JSON 和传递运行状态。写作规则、单节拍任务描述、正文反 AI 味规则都放在 `infrastructure/ai/prompt_packages` 中维护。

## 问题

多节拍模式在测试中暴露出几个明显问题：

- 章节被切成多个局部任务后，正文容易像片段拼接，而不是自然流动的一章。
- 每个节拍都重新起势，导致铺垫重复、推进缓慢。
- 单拍字数偏小时，模型容易用形容词、氛围词、内心独白和解释腔凑字。
- 前一拍没有写透，后一拍已经继续推进，最后出现节拍未完成、章节完成感弱。
- 节拍硬帽或截断策略介入时，容易出现正文中途断掉。

## 原因

网文的一章通常不是多个孤立镜头，而是一个完整故事单元。

更稳定的章节骨架是：

```text
目标 -> 阻碍 -> 行动 -> 转折 -> 兑现/代价 -> 新期待
```

多节拍拆分会把这个闭环切散。模型每次只看到局部节拍，就会优先完成局部描述，而不是维持整章的情绪蓄力、冲突递进和爽点兑现。

本项目已有 `ChapterExecutionPlan`、`PromptRegistry`、`prompt_packages` 和提示词广场。更合适的做法不是在 Python 中硬编码写作规则，而是新增 CPMS 节点，把“单节拍怎样计划”和“整章怎样写”交给提示词包。

## 举例

原章纲：

```text
敌人嘲讽主角，旁人认为主角不可能赢。主角原本还要解决另一件事，暂时无法应战。敌人设局逼主角出手，主角一度被压制，最后用金手指破局，并透露下一位反派的信息。
```

多节拍模式可能拆成：

```text
1. 敌人嘲讽
2. 旁人质疑
3. 主角被迫应战
4. 主角被压制
5. 主角破局
6. 透露下一反派
```

风险是每一段都只完成局部功能，正文容易重复写嘲讽、质疑、震惊，最后破局和钩子不够饱满。

单节拍模式会收束为一个整章执行任务：

```text
围绕章纲完成一个完整故事单元：先立主角目标与情绪缺口，再用敌人嘲讽、旁人轻视和现实阻碍压紧局势；通过设局让主角不得不行动；中段写出压制和误判；后段完成破局、反馈和收获；章尾以下一位反派的信息留下新期待。
```

这样模型获得的是完整章节任务，而不是多个碎片任务。

## 技术逻辑

新增 CPMS 节点：

- `outline-single-beat-plan`：将章纲规划为一个 atom。
- `chapter-single-beat-instructions`：单节拍模式下的整章写作指令。
- `chapter-prose-discipline`：正文反八股、控水分、去 AI 味规则。

新增偏好：

```python
outline_partition_mode = "single" | "auto" | "beat_sheet"
```

含义：

- `single`：默认。通过 `outline-single-beat-plan` 生成单 atom。
- `auto`：保留旧逻辑，BeatSheet、显式结构、LLM 多 atom、fallback。
- `beat_sheet`：优先使用 BeatSheet；没有可用 BeatSheet 时回落单节拍。

关键实现点：

- `build_chapter_execution_plan_async()` 接收 `partition_mode`。
- `single` 模式通过 `PromptRegistry.render("outline-single-beat-plan")` 渲染提示词，再调用 LLM 生成单 atom。
- `ContextBuilder.build_beat_prompt()` 在 `total_beats == 1` 时渲染 `chapter-single-beat-instructions`。
- `build_prose_discipline_block()` 优先渲染 `chapter-prose-discipline`，失败时才使用兼容兜底。
- 全托管单节拍模式下关闭 beat hard cap，避免整章正文中途被硬截断。
- `bundle_meta.yaml` 提升到 `5.2.0-single-beat-cpms`，便于提示词包同步。

## 本质

这次调整的本质不是“少拆几个节拍”，而是把正文生成的注意力从“完成多个局部片段”拉回“写完一个完整章节”。

多节拍适合精细导演，但当前主要矛盾是正文完整性和自然度。单节拍模式让模型把整章看成一个连续故事单元，更容易形成目标、阻碍、行动、兑现和钩子的闭环。

同时，写作审美规则必须留在 CPMS 中。代码只做流程和安全控制，提示词包负责表达写法。这样后续可以在提示词广场继续打磨“网文味”“爽点”“反 AI 味”，不用反复修改业务代码。
