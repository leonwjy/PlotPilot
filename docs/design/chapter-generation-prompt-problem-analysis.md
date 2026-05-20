# 正文生成 Prompt、输入输出与第一章未完成问题整理

## 目标

这份文档用于把当前“正文生成”相关的 prompt、输入输出、策略、技术逻辑和已暴露的问题整理到一处，方便后续继续调 prompt。

这次关注点不是“正文写得好不好看”本身，而是一个更基础的问题：

- 第一章虽然已经生成了 3000 多字；
- 但章节大纲的关键内容明显还没有完整兑现；
- 也就是“字数到了，章节没写完”。

下面先把现状讲清楚，再单独收束这个问题。

---

## 1. 当前正文生成主链路

当前默认思路已经从“多节拍拼接”切到“单节拍整章”。

主链路可以概括为：

```text
章节大纲
-> outline-single-beat-plan
-> ChapterExecutionPlan(atoms=1)
-> chapter-single-beat-instructions
-> chapter-generation-main
-> anti-ai / prose-discipline / continuity / shuangwen 等附加约束
-> LLM 输出正文
```

代码中的关键位置：

- [docs/design/single-beat-generation-strategy.md](/Users/leonwei/Documents/workspace/PlotPilot/docs/design/single-beat-generation-strategy.md:1)
- [application/engine/dag/plan/outline_beat_planner.py](/Users/leonwei/Documents/workspace/PlotPilot/application/engine/dag/plan/outline_beat_planner.py:1)
- [application/engine/services/context_builder.py](/Users/leonwei/Documents/workspace/PlotPilot/application/engine/services/context_builder.py:896)
- [application/workflows/auto_novel_generation_workflow.py](/Users/leonwei/Documents/workspace/PlotPilot/application/workflows/auto_novel_generation_workflow.py:1459)
- [application/engine/services/autopilot_daemon.py](/Users/leonwei/Documents/workspace/PlotPilot/application/engine/services/autopilot_daemon.py:1847)

这里最重要的一点是：

- 现在系统想做的是“把一章当成一个完整故事单元来写”；
- 不是把它拆成很多小镜头分别补字。

---

## 2. 当前实际生效的 Prompt 组成

### 2.1 章前规划 Prompt

用途：先把“章纲”变成一个单 atom 的整章执行任务，而不是拆成很多 beat。

相关文件：

- [infrastructure/ai/prompt_packages/nodes/outline-single-beat-plan/package.yaml](/Users/leonwei/Documents/workspace/PlotPilot/infrastructure/ai/prompt_packages/nodes/outline-single-beat-plan/package.yaml:1)
- [application/engine/dag/plan/outline_beat_planner.py](/Users/leonwei/Documents/workspace/PlotPilot/application/engine/dag/plan/outline_beat_planner.py:80)

它的职责不是直接写正文，而是把大纲转成：

- 本章要完成什么故事单元；
- 这个单元的焦点是什么；
- 目标字数是多少。

### 2.2 单节拍整章指令 Prompt

用途：告诉模型“这不是章节片段，而是一整章”。

相关文件：

- [infrastructure/ai/prompt_packages/nodes/chapter-single-beat-instructions/system.md](/Users/leonwei/Documents/workspace/PlotPilot/infrastructure/ai/prompt_packages/nodes/chapter-single-beat-instructions/system.md:1)
- [infrastructure/ai/prompt_packages/nodes/chapter-single-beat-instructions/user.md](/Users/leonwei/Documents/workspace/PlotPilot/infrastructure/ai/prompt_packages/nodes/chapter-single-beat-instructions/user.md:1)
- [application/engine/services/context_builder.py](/Users/leonwei/Documents/workspace/PlotPilot/application/engine/services/context_builder.py:896)

这层会明确告诉模型：

- 目标字数 `target_words`
- 建议下限 `min_words`
- 建议上限 `max_words`
- 必须完成的故事单元：
  - 谁在场
  - 当前目标
  - 阻碍升级
  - 主角行动
  - 转折或兑现
  - 章尾新期待

这一层本来是为了解决“只写成半章”的问题，但它同时也引入了强烈的“接近上限就收束”信号。

### 2.3 主正文 Prompt

用途：真正生成章节正文。

相关文件：

- [infrastructure/ai/prompt_packages/nodes/chapter-generation-main/system.md](/Users/leonwei/Documents/workspace/PlotPilot/infrastructure/ai/prompt_packages/nodes/chapter-generation-main/system.md:1)
- [infrastructure/ai/prompt_packages/nodes/chapter-generation-main/user.md](/Users/leonwei/Documents/workspace/PlotPilot/infrastructure/ai/prompt_packages/nodes/chapter-generation-main/user.md:1)
- [application/workflows/auto_novel_generation_workflow.py](/Users/leonwei/Documents/workspace/PlotPilot/application/workflows/auto_novel_generation_workflow.py:1459)

这一层承担的东西很多：

- 写作姿态
- 信息密度
- 感官优先
- 角色差异化
- 段落聚合
- 去 AI 味
- 前章衔接
- 事实锁 `fact_lock`
- 已完成节拍 / 已知线索
- 字数约束
- 爽文节奏约束

它已经不是单一 prompt，而是一个“大模板 + 多个注入块”的组合体。

### 2.4 行文纪律 Prompt

用途：限制八股、凑字、总结句、重复震惊、空转内心戏。

相关文件：

- [infrastructure/ai/prompt_packages/nodes/chapter-prose-discipline/user.md](/Users/leonwei/Documents/workspace/PlotPilot/infrastructure/ai/prompt_packages/nodes/chapter-prose-discipline/user.md:1)
- [application/workflows/prose_discipline.py](/Users/leonwei/Documents/workspace/PlotPilot/application/workflows/prose_discipline.py:1)

它给正文一个额外信号：

- 每 300～500 字要有新事实；
- 每段都要推进事情；
- 如果是 `single` 模式，超过目标后只补必要兑现和钩子；
- 不要为了写透继续膨胀篇幅。

这条规则对“去水”很有效，但对“复杂大纲完整兑现”未必友好。

### 2.5 连贯性 / 续写 Prompt

用途：多节拍或断点续写时，避免重复铺垫和硬切。

相关文件：

- [application/workflows/beat_continuation.py](/Users/leonwei/Documents/workspace/PlotPilot/application/workflows/beat_continuation.py:1)
- [infrastructure/ai/prompt_packages/nodes/autopilot-stream-beat/user.md](/Users/leonwei/Documents/workspace/PlotPilot/infrastructure/ai/prompt_packages/nodes/autopilot-stream-beat/user.md:1)
- [infrastructure/ai/prompt_packages/nodes/anti-ai-mid-generation-refresh/user.md](/Users/leonwei/Documents/workspace/PlotPilot/infrastructure/ai/prompt_packages/nodes/anti-ai-mid-generation-refresh/user.md:1)

这套机制主要解决：

- 上一段写到哪了；
- 下一段该怎么自然接；
- 写偏后如何中段刷新。

对“第一章写不完”有帮助，但不是根因层。

---

## 3. 输入输出

## 3.1 输入

正文生成实际吃进去的，不只有大纲。

核心输入包括：

- `outline`：章节大纲
- `context`：上下文总包，含 Bible 摘要、前情、向量召回等
- `storyline_context`：故事线 / 里程碑
- `plot_tension`：情节张力与节奏要求
- `style_summary`：风格约束
- `voice_anchors`：人物声线 / 小动作锚点
- `fact_lock`：事实锁、已完成节拍、已揭露线索
- `beat_prompt`：当前节拍说明；单节拍时其实就是“整章执行任务”
- `beat_target_words` 或 `chapter_target_words`
- `chapter_draft_so_far`：同章已写内容，供续写衔接
- `generation_prefs`：如 `outline_partition_mode`、`beat_hard_cap_enabled`、`smart_truncate_enabled`

关键代码：

- [application/workflows/auto_novel_generation_workflow.py](/Users/leonwei/Documents/workspace/PlotPilot/application/workflows/auto_novel_generation_workflow.py:1459)
- [application/engine/services/context_builder.py](/Users/leonwei/Documents/workspace/PlotPilot/application/engine/services/context_builder.py:150)

### 3.2 输出

最终输出不只是“一段正文文本”。

系统会产出：

- `content`：正文
- `word_count`
- 共享状态里的运行遥测：
  - `beat_target_words`
  - `chapter_target_words`
  - `beat_hard_cap`
  - `beat_max_words_hint`
  - `last_smart_truncate`
- 章节状态：
  - `draft`
  - `completed`

相关位置：

- [application/engine/dag/nodes/execution_nodes.py](/Users/leonwei/Documents/workspace/PlotPilot/application/engine/dag/nodes/execution_nodes.py:182)
- [application/engine/services/autopilot_daemon.py](/Users/leonwei/Documents/workspace/PlotPilot/application/engine/services/autopilot_daemon.py:1863)

---

## 4. 策略

当前正文生成的核心策略可以概括为六条。

### 4.1 单节拍整章

目标是让模型把一章看成一个连续故事单元：

```text
目标 -> 阻碍 -> 行动 -> 转折 -> 兑现/代价 -> 新期待
```

这条逻辑来自：

- [docs/design/single-beat-generation-strategy.md](/Users/leonwei/Documents/workspace/PlotPilot/docs/design/single-beat-generation-strategy.md:31)

### 4.2 高信息密度

不是让模型靠景物、情绪词、解释腔补字，而是要求：

- 每段都推进；
- 每 300～500 字有新事实；
- 不允许连续空转。

### 4.3 反 AI 味

系统对下面这些东西有明显压制：

- 直接情绪标签
- 套路比喻
- 微表情
- 纠正式对照
- 哲学总结句
- 众人震惊排比

### 4.4 章节衔接优先

要求本章前三句话就接住前章的情绪和悬念，不允许像重开一章。

### 4.5 爽文冷启动

前 1～3 章有额外强化指令，尤其第一章：

- 前 300 字内要出现压制 / 不公 / 质疑
- 中段要有第一次底牌显露
- 结尾要有钩子

相关代码：

- [application/workflows/auto_novel_generation_workflow.py](/Users/leonwei/Documents/workspace/PlotPilot/application/workflows/auto_novel_generation_workflow.py:2010)

### 4.6 接近目标字数就收束

这条策略非常重要，也是当前问题的源头之一。

系统会反复告诉模型：

- 达到目标附近后，优先收束；
- 接近上限后，不要再铺陈；
- 不要为了“写完整章节”继续膨胀篇幅。

这会带来一个副作用：

- 当“大纲复杂度”高于“目标字数预算”时；
- 模型更容易选择“收束得体”，而不是“把后半段大纲硬写完”。

---

## 5. 问题

这里单独整理“第一章 3000 多字但大纲没写完”的问题。

### 5.1 表层现象

现象不是“完全没生成”，而是：

- 文本量已经上来了；
- 开头铺垫、氛围、冲突起势也大概率已经写了；
- 但大纲里的后续关键推进、转折、兑现、钩子，没有完整落地；
- 最终读感像“写到半章就开始准备收尾”。

### 5.2 当前最可能的根因

#### 问题一：字数目标和大纲完成度之间存在冲突

单节拍指令明确要求：

- `target_words`
- `min_words = target * 0.82`
- `max_words = target * 1.12`

代码位置：

- [application/engine/services/context_builder.py](/Users/leonwei/Documents/workspace/PlotPilot/application/engine/services/context_builder.py:904)
- [application/workflows/auto_novel_generation_workflow.py](/Users/leonwei/Documents/workspace/PlotPilot/application/workflows/auto_novel_generation_workflow.py:1498)

如果一章目标是 3000 字，那么正文会反复收到类似信号：

- 2460 字以后可以补足；
- 3000 字附近要开始收束；
- 3360 字附近必须结束。

如果第一章大纲本身承担了：

- 主角出场
- 世界基调落地
- 压制建立
- 冲突展开
- 底牌显露
- 反应链
- 章尾钩子

那么 3000 多字很可能天然不够。

这时模型会优先服从“篇幅纪律”，而不是“大纲完整兑现”。

#### 问题二：运行时 token 预算也在强化提前收束

在自动驾驶主链路里，节拍生成时的输出 token 是按目标字数近似放大的：

- `max_tokens = int(adjusted_target * 1.12)`

代码位置：

- [application/engine/services/autopilot_daemon.py](/Users/leonwei/Documents/workspace/PlotPilot/application/engine/services/autopilot_daemon.py:1953)

这意味着：

- prompt 在提醒“接近上限就收”；
- 运行参数也没有给太多“超纲展开”的空间；
- 两边一起把模型推向“控制篇幅优先”。

#### 问题三：行文纪律把“超目标继续展开”定义成负面行为

`chapter-prose-discipline` 明确说：

- `beat_target_words` 是目标，不是最低消费；
- `single` 模式超过目标后只补必要兑现和钩子；
- 禁止继续增加新回合、新旁观者反应或新的解释段。

文件位置：

- [infrastructure/ai/prompt_packages/nodes/chapter-prose-discipline/user.md](/Users/leonwei/Documents/workspace/PlotPilot/infrastructure/ai/prompt_packages/nodes/chapter-prose-discipline/user.md:28)

这条规则能防止水文，但也会把“后半段大纲还没写到”误判成“不该继续展开”。

#### 问题四：第一章还有额外冷启动约束，会吃掉更多篇幅

首章并不是普通章节。

系统额外要求它：

- 快速起势
- 快速建立压制
- 中段要给第一次底牌
- 结尾要钩人

这实际上提升了第一章的“信息密度成本”。

也就是说：

- 同样 3000 字；
- 第一章能消耗在“必要任务”上的篇幅，比普通章节更大；
- 留给后续大纲推进的空间更少。

#### 问题五：维护层存在 prompt 认知错位

代码里存在一个值得警惕的点：

- `AutoNovelGenerationWorkflow` 实际读取的是 `chapter-generation-main`
- 但代码注释与仓库里还存在 `workflow-chapter-generation`

相关位置：

- [application/workflows/auto_novel_generation_workflow.py](/Users/leonwei/Documents/workspace/PlotPilot/application/workflows/auto_novel_generation_workflow.py:84)
- [application/workflows/auto_novel_generation_workflow.py](/Users/leonwei/Documents/workspace/PlotPilot/application/workflows/auto_novel_generation_workflow.py:1731)
- [infrastructure/ai/prompt_packages/nodes/workflow-chapter-generation/package.yaml](/Users/leonwei/Documents/workspace/PlotPilot/infrastructure/ai/prompt_packages/nodes/workflow-chapter-generation/package.yaml:1)

这会带来一个现实问题：

- 你以为自己在改“运行时主 prompt”；
- 实际生效的可能是另一个节点；
- 最后很难判断“为什么改了 prompt 但效果不对”。

这不是第一章没写完的直接原因，但它会放大排查难度。

---

## 6. 大纲

从当前策略看，系统理想中的一章，不是“事件列表”，而是“一个完整闭环”。

推荐把章纲理解成下面这类结构：

```text
1. 主角此刻要什么
2. 现实里有什么阻碍
3. 阻碍如何升级
4. 主角如何行动
5. 行动带来什么可见结果
6. 本章如何形成转折、兑现或代价
7. 章尾留下什么新期待
```

如果第一章大纲超出这个闭环很多，比如同时承担：

- 世界观落地
- 主角身份建立
- 多角色登场
- 第一轮冲突
- 第一轮压制
- 第一轮反打
- 后续反派钩子

那它在 3000 字附近收束，大概率不是“模型偷懒”，而是“任务装得过满”。

---

## 7. 举例

### 7.1 当前系统想要的“单节拍整章”

示意例子：

```text
敌人嘲讽主角，旁人认为主角不可能赢。主角原本还有别的事，暂时无法应战。敌人设局逼主角出手，主角一度被压制，最后用底牌破局，并透露下一位反派的信息。
```

系统希望模型把它写成：

```text
目标 -> 阻碍 -> 被迫行动 -> 压制升级 -> 破局 -> 反馈链 -> 新钩子
```

### 7.2 第一章没写完时更像什么

如果目标字数只有 3000 左右，模型很可能变成：

```text
开场起势 -> 压制建立 -> 对峙拉长 -> 角色反应铺开 -> 接近字数目标 -> 提前收束
```

这样就会出现：

- 前半段写得不算差；
- 但“破局”“兑现”“更大钩子”还没真正到位。

### 7.3 一个更具体的失败模式

假设第一章大纲包含 6 个任务：

```text
1. 主角出场
2. 不公与压制
3. 多角色试探
4. 被迫应战
5. 第一次底牌显露
6. 留下更大威胁
```

当系统同时要求：

- 首章高张力
- 情绪通过动作体现
- 对话要有弦外之音
- 不许空转
- 接近 3000 字必须收束

那么最容易发生的就是：

- 1-4 写得很充分；
- 5 只露半截；
- 6 直接被压缩成很弱的尾句，甚至来不及写。

---

## 8. 技术逻辑

这里按“从上游到下游”的顺序简要梳理。

### 8.1 章纲先被规划成单 atom

`partition_mode = single` 时，即便大纲是编号列表，也优先走单节拍。

证据：

- [tests/unit/application/engine/test_outline_single_beat_plan.py](/Users/leonwei/Documents/workspace/PlotPilot/tests/unit/application/engine/test_outline_single_beat_plan.py:14)

这说明第一章不是因为“拆太碎”而没写完，当前默认更像是“整章预算不足”。

### 8.2 单节拍模式会生成目标区间

`ContextBuilder.build_beat_prompt()` 会计算：

- `min_words = target * 0.82`
- `max_words = target * 1.12`

证据：

- [application/engine/services/context_builder.py](/Users/leonwei/Documents/workspace/PlotPilot/application/engine/services/context_builder.py:904)

### 8.3 主 prompt 再重复一次字数边界

`_build_prompt()` 会把同样的边界再写进 `length_rule`。

证据：

- [application/workflows/auto_novel_generation_workflow.py](/Users/leonwei/Documents/workspace/PlotPilot/application/workflows/auto_novel_generation_workflow.py:1498)

这意味着字数收束不是一个弱提醒，而是至少被提示了两轮。

### 8.4 自动驾驶还会按目标字数设置生成上限

单节拍写作时：

- `max_tokens = int(adjusted_target * 1.12)`

证据：

- [application/engine/services/autopilot_daemon.py](/Users/leonwei/Documents/workspace/PlotPilot/application/engine/services/autopilot_daemon.py:1953)

### 8.5 硬截断在单节拍模式下通常会关闭

设计文档和运行逻辑都说明：

- `single` 模式下会尽量避免 beat hard cap 硬截断

证据：

- [docs/design/single-beat-generation-strategy.md](/Users/leonwei/Documents/workspace/PlotPilot/docs/design/single-beat-generation-strategy.md:99)
- [application/engine/services/autopilot_daemon.py](/Users/leonwei/Documents/workspace/PlotPilot/application/engine/services/autopilot_daemon.py:1847)

所以当前“写不完”更像是软收束，不像是被强行砍断。

### 8.6 续写机制更多是在解决“接不顺”

`format_prior_draft_for_prompt()` 会保留近期全文、压缩远期正文，让续写更稳。

证据：

- [application/workflows/beat_continuation.py](/Users/leonwei/Documents/workspace/PlotPilot/application/workflows/beat_continuation.py:53)

这说明它主要解决：

- 重复铺垫
- 节拍断裂
- 对话接不上

而不是解决“大纲复杂但字数不够”的问题。

---

## 9. 本质

这次第一章没写完，本质不是单一 bug。

更准确地说，它是一个“目标冲突”：

- 系统想要整章完整；
- 系统又强烈要求接近目标字数就收束；
- 第一章还被额外要求高张力、高钩子、高信息密度；
- 如果章纲装的内容超过 3000 多字预算，模型最终会优先保证“写得像一章”，而不是“覆盖完大纲全部事项”。

换句话说，当前系统更像是在优化：

- 不水
- 不散
- 不像 AI
- 有章感

但还没有把“章纲完成率”放到和“字数纪律”同等优先级。

---

## 10. 这次问题的初步结论

针对“第一章 3000 多字，但是大纲内容估计一般还没有写到”，当前可以先下这个初步结论：

### 结论一

这更像“预算不匹配”，不是“模型完全失控”。

### 结论二

当前 prompt 系统把“接近目标字数就收束”表达得太强了，强到会压过“大纲必须完整兑现”。

### 结论三

第一章因为有额外冷启动约束，天然比普通章节更容易出现“前面写满了，后面没写到”。

### 结论四

仓库里存在 `chapter-generation-main` 与 `workflow-chapter-generation` 的认知错位，后续改 prompt 时必须先确认到底改哪个节点，否则很容易白改。

---

## 11. 接下来建议先整理的几个问题

如果下一步是继续优化，而不是马上改代码，建议优先把这几个问题定下来：

1. 第一章到底希望以“完整兑现大纲”为第一优先，还是以“控制在 3000～3500 字”为第一优先。
2. 第一章是否应该拥有独立于普通章节的字数策略，而不是复用通用 `target * 0.82 ~ 1.12` 区间。
3. 单节拍模式下，是否要把“接近字数就收束”改成“先完成大纲关键点，再谈收束”。
4. 是否需要增加一个新的显式约束：大纲里的关键事件未完成时，禁止提前进入章尾收束。
5. 提示词广场里真正应该编辑的正文主节点，到底统一为 `chapter-generation-main`，还是改回 `workflow-chapter-generation`，避免维护混乱。

---

## 12. 本文涉及的关键文件

- [docs/design/single-beat-generation-strategy.md](/Users/leonwei/Documents/workspace/PlotPilot/docs/design/single-beat-generation-strategy.md:1)
- [application/workflows/auto_novel_generation_workflow.py](/Users/leonwei/Documents/workspace/PlotPilot/application/workflows/auto_novel_generation_workflow.py:1459)
- [application/engine/services/autopilot_daemon.py](/Users/leonwei/Documents/workspace/PlotPilot/application/engine/services/autopilot_daemon.py:1847)
- [application/engine/services/context_builder.py](/Users/leonwei/Documents/workspace/PlotPilot/application/engine/services/context_builder.py:896)
- [application/workflows/prose_discipline.py](/Users/leonwei/Documents/workspace/PlotPilot/application/workflows/prose_discipline.py:1)
- [application/workflows/beat_continuation.py](/Users/leonwei/Documents/workspace/PlotPilot/application/workflows/beat_continuation.py:1)
- [infrastructure/ai/prompt_packages/nodes/chapter-generation-main/system.md](/Users/leonwei/Documents/workspace/PlotPilot/infrastructure/ai/prompt_packages/nodes/chapter-generation-main/system.md:1)
- [infrastructure/ai/prompt_packages/nodes/chapter-generation-main/user.md](/Users/leonwei/Documents/workspace/PlotPilot/infrastructure/ai/prompt_packages/nodes/chapter-generation-main/user.md:1)
- [infrastructure/ai/prompt_packages/nodes/chapter-single-beat-instructions/user.md](/Users/leonwei/Documents/workspace/PlotPilot/infrastructure/ai/prompt_packages/nodes/chapter-single-beat-instructions/user.md:1)
- [infrastructure/ai/prompt_packages/nodes/chapter-prose-discipline/user.md](/Users/leonwei/Documents/workspace/PlotPilot/infrastructure/ai/prompt_packages/nodes/chapter-prose-discipline/user.md:1)
- [infrastructure/ai/prompt_packages/nodes/workflow-chapter-generation/package.yaml](/Users/leonwei/Documents/workspace/PlotPilot/infrastructure/ai/prompt_packages/nodes/workflow-chapter-generation/package.yaml:1)
