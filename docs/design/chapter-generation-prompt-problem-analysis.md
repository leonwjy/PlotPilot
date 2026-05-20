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

## 5. 当前三本实测正文的问题记录

下面是对本地数据库中最近 3 本已生成小说正文的抽查结果，目的是先把“真实输出长什么样”记录下来，避免只看 prompt 不看成品。

### 5.1 抽查对象

| 小说 | 状态 | 配置字数 | 已完成章数 | 备注 |
|---|---|---:|---:|---|
| 丹武双修 | writing | 2500 | 3 | 第 4 章仍是 draft |
| 高武 | auditing | 2500 | 4 | 前 4 章已完成 |
| 规则怪谈 | writing | 2500 | 3 | 第 4 章仍是 draft |

### 5.2 字数超标是稳定现象

三本书的已完成章节都明显超过配置字数，不是单章偶发。

| 小说 | 章 | 配置字数 | 实际字数 | 超出 |
|---|---:|---:|---:|---:|
| 丹武双修 | 1 | 2500 | 3279 | +779 |
| 丹武双修 | 2 | 2500 | 4180 | +1680 |
| 丹武双修 | 3 | 2500 | 4373 | +1873 |
| 高武 | 1 | 2500 | 4248 | +1748 |
| 高武 | 2 | 2500 | 3463 | +963 |
| 高武 | 3 | 2500 | 3972 | +1472 |
| 高武 | 4 | 2500 | 4015 | +1515 |
| 规则怪谈 | 1 | 2500 | 3714 | +1214 |
| 规则怪谈 | 2 | 2500 | 4561 | +2061 |
| 规则怪谈 | 3 | 2500 | 4281 | +1781 |

初步判断：

- 现有“目标字数附近收束”的约束没有真正压住输出；
- 实际正文更像是在“满足大纲 + 继续补肉”模式里持续膨胀；
- 当前超字数幅度已经足以说明，字数约束不是软弱地被忽略，就是被后续扩写/续写链路冲掉了。

### 5.3 正文的八股/模板化倾向

这里说的“八股”不是传统的“首先、其次、最后”，而是更广义的 AI 模板味，主要表现为：

- 开头大量使用感官钩子和高密度名词堆叠，常见“血雾、锁链、矿道、残影、光焰”等连续上场；
- 句式常见“不是 X。是 Y。”这种否定转折模板；
- 动作被拆得很细，但推进信息的密度不一定同步增加；
- 对比喻、抽象情绪、身体感受的依赖偏高，容易显得“很会写，但写法像一个模子”。

抽样开头里能看到这些倾向：

- `丹武双修`：一上来是塌方、岩浆、矿脉、通风井、断针、刀光等高强度意象连续推进；
- `高武`：大量“不是水”“不是……是……”式解释腔，配合矿道、髓雾、基因锁等设定词密集堆叠；
- `规则怪谈`：`像...一样`、`仿佛...` 这类比喻和解释性句式更密，且整体有更明显的“镜头化拆分”感。

### 5.4 需要继续盯的具体问题

1. 字数控制没有按配置落点，章节稳定超长。
2. 正文倾向于先铺景再推进，信息推进和篇幅增长不同步。
3. 句式模板感偏重，尤其是“否定转折 + 解释式补充 + 名词堆叠”的组合。
4. 视觉和动作很足，但有时会变成“写得像章回体演示”，而不是自然流动的章节。
5. 目前还没做更细的自动统计，例如：
   - 句长分布；
   - 段落信息密度；
   - 近似重复句式；
   - 比喻/否定转折/抽象情绪的章节级占比。

### 5.5 结论

现在可以先把问题暂时归成两类：

- **硬问题**：正文超出配置字数；
- **软问题**：正文有明显模板化、八股化倾向。

下一步如果继续修，建议先区分：

1. 是生成阶段就超字数；
2. 还是生成后处理/续写/补段把字数拉高；
3. 以及八股味主要来自主 prompt、辅助 prompt，还是续写刷新链路。

---

## 6. 酒馆预设 Anti-AI / COT 方法吸收评估

本次参考目录：

- `/Users/leonwei/Downloads/strict_cleaned_jsons`

抽查到的有效方法不是单纯“禁词表”，而是三类能力：

1. **生成前规则压缩**：把“不要 AI 味”拆成可执行动作，例如白描、直述、有限视角、动作链、删除纠正式对照。
2. **生成中自检**：每个自然段或关键段落前做极短预检，先判断意图、雷区和替代写法，再输出正文。
3. **生成后审计重写**：输出后按禁忌项、句式、比喻、节奏、角色合理性检查，并按问题类型重写。

这些方法可以用于修复现在正文的问题，但需要用项目现有 `infrastructure/ai/prompt_packages` 的节点方式落地，不建议硬编码规则。

### 6.1 可吸收的去 AI 味规则

酒馆预设里反复出现、且与当前正文问题高度相关的规则：

- **比喻最小化**：能用感官和动作直写的内容，不用“像 / 仿佛 / 宛如 / 如同”补解释；比喻只保留给无法白描的抽象体验。
- **禁纠正式对照**：少用或禁用“不是 A，而是 B”“不是……是……”这类先否定再解释的句式，改成直接叙述动作和结果。
- **禁补丁式解释**：禁止前句写完后再用破折号、比喻、抽象名词反复找补。
- **动作链优先**：人物做什么、看到什么、停在哪里、付出什么代价，要比“他感到某种情绪”优先。
- **有限视角**：只写当前 POV 能看见、听见、判断到的内容，不替角色总结命运，不提前暗示作者知道后续。
- **段落承担任务**：每段至少推进动作、信息、关系、决策、风险中的一项；纯氛围段不能连续出现。
- **活人台词**：对白短一点，有停顿、绕弯、改口和弦外之音，不像汇报任务。
- **输出前清洗**：比喻、八股句式、抽象情绪、机械设定解释、总结金句都要在最后过一遍。

这些规则和当前项目里的 `anti-ai-behavior-protocol`、`chapter-prose-discipline`、`anti-ai-chapter-audit` 有重叠，但酒馆预设提供了更强的“执行动作”表达。

### 6.2 不建议直接照搬的部分

不建议吸收：

- 破限、角色扮演越权、安全绕过类内容；
- 大量固定风格人格、作者声明、平台变量；
- 过长的黑名单原文堆叠；
- 要求把思维链显式输出给读者的格式。

可吸收的是方法，不是原文。尤其是 COT 部分，项目里应转化为“内部审计工作流”或“隐藏草稿/审计/重写节点”，不要让正文里出现 `<think>`、HTML 注释、自检说明或审计痕迹。

### 6.3 COT 模式对当前问题是否有用

有用，但要改造成项目自己的形式。

酒馆 COT 的核心不是“输出长思维链”，而是：

```text
写前确认目标
-> 识别本段最容易犯的八股/比喻/水文风险
-> 先在内部拦截第一直觉模板句
-> 输出修正后的正文
-> 输出后再审计一次
```

对应到 PlotPilot，可以设计为：

```text
chapter-generation-main
-> anti-ai-self-check / paragraph-draft-check（新 prompt 节点，内部规则）
-> 正文输出
-> anti-ai-chapter-audit
-> anti-ai-revision-plan（新 prompt 节点，输出 JSON 修订计划）
-> anti-ai-prose-rewrite（新 prompt 节点，只重写正文，不改剧情事实）
-> 二次 anti-ai-chapter-audit
```

这个链路能修两个问题：

- **正文超字数**：生成前/生成后都要求“删重复解释、删比喻找补、删重复体感”，而不是继续补肉。
- **八股倾向**：审计结果按问题类型驱动重写，不只在 prompt 里提前喊“不要八股”。

### 6.4 现有节点梳理

当前相关 prompt 节点：

| 节点 | 当前职责 | 问题 |
|---|---|---|
| `chapter-generation-main` | 主正文生成 | 规则很重，且 `length_rule` 默认仍有 3200-4200 的历史倾向 |
| `workflow-chapter-generation` | 运行时章节生成模板 | 与主节点有功能重复，运行时轻量版仍有固定 Anti-AI 条款 |
| `chapter-prose-discipline` | 反八股 / 控水分注入块 | 适合继续增强为“酒馆方法吸收层” |
| `anti-ai-behavior-protocol` | 生成前行为协议 | 可吸收白描、直述、有限视角、动作链等原则 |
| `anti-ai-mid-generation-refresh` | 中段刷新提示 | 有节点，但主生成链路里还没形成真正的段落级闭环 |
| `anti-ai-chapter-audit` | LLM 章后审计 JSON | DAG 节点存在，主托管流程实际更多走 Python `ClicheScanner` |
| `voice-rewrite` | 文风相似度偏离时重写 | 偏声线，不是专门去八股 |
| `review-improvement-suggestions` | 审稿建议 | 产出建议，不直接修正文 |
| `chapter-bridge-fix` | 重写首段衔接 | 只处理章首衔接 |

当前主流程里已经有：

- 生成前注入：`anti-ai-behavior-protocol`、`anti-ai-character-state-lock`、`anti-ai-allowlist-explain`、`chapter-prose-discipline`
- 章后审计：`_run_anti_ai_audit()`，会落库并可触发暂停
- 文风漂移：只保留有限次定向修正/告警，最终仍保留章节

缺口是：

- 审计结果没有稳定反向驱动“正文级重写”；
- `anti-ai-mid-generation-refresh` 没有真正参与流式/分段生成；
- `voice-rewrite`、`review-improvement-suggestions`、`anti-ai-chapter-audit` 之间没有统一的修订计划格式；
- 主生成节点和运行时生成节点存在规则重复，容易一边改了另一边仍旧生效。

### 6.5 建议的 prompt_packages 落地方式

保持“不硬编码修复”的前提下，建议新增或增强这些 prompt 节点：

1. 增强 `chapter-prose-discipline`
   - 吸收“比喻只限抽象体验”“直述替代否定反衬”“动作链推进”“输出前清洗”。
   - 作为生成前全局约束，继续由现有 `build_prose_discipline_block()` 渲染。

2. 增强 `anti-ai-chapter-audit`
   - 把现有 8 类审计扩展为更贴近当前问题的分类：
     - 比喻找补
     - 否定转折
     - 动作拆帧空转
     - 设定名词堆叠
     - 抽象情绪
     - 解释腔
     - 总结金句
     - 段落无新增信息
   - 输出必须包含 `rewrite_directives`，供下一节点消费。

3. 新增 `anti-ai-revision-plan`
   - 输入：正文、审计 JSON、目标字数、章纲。
   - 输出：JSON 修订计划，明确删哪里、合并哪里、保留哪些剧情事实。
   - 这个节点只做计划，不写正文。

4. 新增 `anti-ai-prose-rewrite`
   - 输入：原正文、修订计划、章纲、事实锁、目标字数。
   - 输出：修订后的完整正文。
   - 规则：不新增剧情、不新增角色、不改变事实，只删水、改句式、压比喻、压八股，并把字数拉回目标窗口。

5. 复用 `voice-rewrite`，但不要让它承担 Anti-AI 主修复
   - 它适合处理声线漂移；
   - 去八股应该走新的 `anti-ai-prose-rewrite`，避免声线修正和八股修正互相污染。

6. 保留 `chapter-bridge-fix` 的单一职责
   - 只修首段衔接；
   - 不并入 Anti-AI 重写，否则会让桥段修复承担太多职责。

### 6.6 推荐整合形态

短期可行版本：

```text
生成
-> Python ClicheScanner + LLM anti-ai-chapter-audit
-> 若严重/中等/超字数超过阈值：
   -> anti-ai-revision-plan
   -> anti-ai-prose-rewrite
   -> 再审计
-> 保存
```

中期更理想版本：

```text
按段生成 / 流式生成
-> 每 600-900 字运行一次轻量 anti-ai-mid-generation-refresh
-> 注入下一段修正提示
-> 章后完整审计
-> 必要时整章重写
```

其中所有策略文本都应放在 `prompt_packages/nodes/*`，代码只负责：

- 选择节点；
- 渲染变量；
- 传递审计 JSON；
- 判断是否进入重写；
- 保存最终正文。

### 6.7 是否能修复当前正文问题

可以，但仅增强生成前 prompt 不够。

当前已经有很多“不要八股”的前置规则，实际输出仍然八股和超长，说明模型会在大纲覆盖、冲突慢写、信息密度、爽点反馈等指令压力下继续膨胀。更有效的修复应是：

- 生成前：规则更具体，减少模板句入口；
- 生成中：段落级轻审计，阻止模式连续扩散；
- 生成后：用审计结果驱动重写，把超字数和八股一起压回去。

这条路线符合项目当前 CPMS / `prompt_packages` 架构，也不需要把酒馆规则硬编码进业务逻辑。

### 6.8 完成度审计：判断章节/节拍是否写完

审计应该加入“完成度”维度。

现在已有 `chapter-state-extraction`，但它的职责是从正文里抽取已经发生的 9 类叙事变量：

- 新角色
- 关键行为
- 关系变化
- 伏笔种下/回收
- 核心事件
- 时间推进
- 故事线推进

它能回答“正文实际写了什么”，但不能回答“章纲/节拍要求是否全部写完”。所以需要新增一个明确的完成度审计节点：

```text
chapter-completion-audit
```

建议输入：

- `outline`：章节大纲
- `beat_plan`：当前章节 atoms / 当前 beat intent
- `content`：已生成正文
- `target_words`：目标字数
- `word_count`：当前字数
- `fact_lock`：事实锁与已完成节拍

建议输出 JSON：

```json
{
  "completion_score": 0,
  "is_complete": false,
  "covered_units": [
    {"id": "b1", "status": "covered", "evidence": "正文中对应证据"}
  ],
  "missing_units": [
    {"id": "b2", "reason": "只铺垫，未出现行动结果"}
  ],
  "partial_units": [
    {"id": "b3", "reason": "行动出现了，但转折/代价未兑现"}
  ],
  "ending_state": "unfinished/soft_landing/hard_cliffhanger/complete",
  "next_action": "continue/rewrite/finish/append_bridge",
  "word_budget_assessment": "under/ok/over",
  "rewrite_directives": []
}
```

这会比现在只看字数更精准：

- 如果章节字数到了但 `missing_units` 不为空，说明“没写完”，不能收尾；
- 如果章节超字数但所有 beat 都完成，应该触发压缩重写；
- 如果某个 beat 没完成，后续多节点模式可以只补当前 beat，而不是整章重写。

### 6.9 缺字漏字审计

审计还应加入基础文本健康检查，单独处理“缺字漏字”和输出残损。

建议新增或并入一个节点：

```text
prose-integrity-audit
```

检查项：

- 句子残缺：明显缺主语、谓语、宾语，或句子中途断掉；
- 标点残损：引号未闭合、括号未闭合、连续异常标点；
- 缺字漏字：常见词组残缺、同音/近形误替、明显少一个连接词；
- 角色名错误：角色名缺字、错字、前后不一致；
- 断流：段落末尾像流式输出被截断；
- 重复粘连：同一句、同一短语连续重复；
- JSON/提示词泄漏：正文里出现审计、自检、标签、变量名。

这个节点不负责审美，只负责“正文是否完整可读”。它应在 Anti-AI 审计前后都能运行：

- 生成后先查残损，避免拿坏文本去做风格审计；
- 重写后再查一次，避免修文引入错漏。

### 6.10 统一 Anti-AI 中心，不要东一块西一块

当前 Anti-AI 相关内容分散在：

- `chapter-generation-main`
- `workflow-chapter-generation`
- `chapter-prose-discipline`
- `anti-ai-behavior-protocol`
- `anti-ai-chapter-audit`
- `anti-ai-mid-generation-refresh`
- `voice-rewrite`
- `review-improvement-suggestions`
- Python `ClicheScanner`
- Python `MidGenerationRefresh`
- DAG `val_anti_ai` / `anti_ai_audit`

建议统一成一个“Anti-AI Prompt Center”，仍然使用 `prompt_packages`，但职责分层清楚：

```text
anti-ai-style-canon          # 去 AI 味总规则：白描、直述、有限视角、比喻最小化
anti-ai-generation-guard     # 生成前注入：简短、强约束、可执行
anti-ai-segment-audit        # 300-500 字段落/beat 审计
anti-ai-chapter-audit        # 整章审计
anti-ai-revision-plan        # 根据审计生成修订计划
anti-ai-prose-rewrite        # 按计划重写正文
prose-integrity-audit        # 缺字漏字/残损审计
chapter-completion-audit     # 章节/节拍完成度审计
```

旧节点建议归位：

| 现有内容 | 建议归属 |
|---|---|
| `chapter-prose-discipline` | 合并为 `anti-ai-generation-guard` 的一部分，保留兼容键 |
| `anti-ai-behavior-protocol` | 合并为 `anti-ai-style-canon` + `anti-ai-generation-guard` |
| `anti-ai-chapter-audit` | 升级为统一整章审计，输出可驱动重写的 JSON |
| `anti-ai-mid-generation-refresh` | 改为 `anti-ai-segment-audit` 的修正提示来源 |
| `review-improvement-suggestions` | 只保留泛审稿建议，不再承担 Anti-AI 修复 |
| `voice-rewrite` | 只处理声线漂移，不处理八股 |
| `chapter-bridge-fix` | 保持首段衔接，不并入 Anti-AI |
| Python `ClicheScanner` | 作为快速硬扫，结果喂给 LLM 审计节点 |

原则：

- 规则文本全部放在 `prompt_packages/nodes/*`；
- Python 只做调度、阈值判断、正则快速扫描和数据传递；
- 不再让每个生成节点自己写一份 Anti-AI 禁令。

### 6.11 酒馆去 AI 味方法整理为项目规则

可吸收成项目规则的内容可以整理为 10 条：

1. **白描优先**：能直接写动作、物件、温度、声音，就不解释情绪。
2. **比喻最小化**：`像 / 仿佛 / 宛如 / 如同` 只允许用于无法直写的抽象体验；普通视觉、动作、疼痛、声音不打比方。
3. **禁否定反衬**：避免“不是 A，而是 B”“不是……是……”，改为直接写 B 或写动作结果。
4. **禁补丁解释**：禁止用破折号、括号、同义改述给前一句补意义。
5. **动作链推进**：人物先做一件可见的事，再产生后果；少写纯心理判断。
6. **有限视角**：只写当前 POV 能知道的内容，不用作者视角总结命运或预告后续。
7. **段落有任务**：每 300-500 字必须有新事实、动作结果、关系变化、线索或决策。
8. **活人对白**：台词短、有试探、有停顿、有信息差；避免像说明书或任务汇报。
9. **删模板爽点**：少写泛化“众人震惊”“空气凝固”“一切才刚开始”，改写成具体人物的具体反应。
10. **输出前清洗**：最终正文不得带自检、审计、思考标签、变量名、JSON 或提示词痕迹。

这些规则应该进入 `anti-ai-style-canon`，再由 `anti-ai-generation-guard` 压缩成短规则注入主生成 prompt。

### 6.12 300-500 字 COT 预检/审计/重写

可以参考酒馆 COT，但要实现为“隐藏的段落级审计工作流”，不要显式输出思维链。

推荐粒度：

- 300-500 字作为一个 prose segment；
- 或一个 beat 写完就审计；
- 如果 beat 本身很短，允许累计到 300 字左右再审；
- 如果连续生成超过 600 字仍未审，强制切段审计。

建议流程：

```text
segment_write
-> prose-integrity-audit
-> anti-ai-segment-audit
-> chapter-completion-audit(beat_scope)
-> segment-revision-plan
-> segment-rewrite
-> append_to_draft
```

段落级审计要回答：

- 这 300-500 字是否完成了当前 beat 的一个明确推进？
- 有没有 AI 味高发句式？
- 有没有比喻/否定反衬/解释腔？
- 有没有缺字漏字或残句？
- 是否超出当前 beat 字数预算？
- 是否应该继续当前 beat、进入下一 beat、或结束章节？

这就是项目版 COT：

- 模型可以“内部预检”；
- 系统用节点“外部审计”；
- 正文只保留最终重写后的内容。

### 6.13 单节点模式是否应该先放一放

建议短期先把“单节点整章模式”放一放，改用多节点/多 beat 模式验证。

原因：

- 单节点整章模式很难在 2500 字内同时完成大纲覆盖、去 AI 味、字数控制和收尾判断；
- 它只能章后才知道没写完，修复成本高；
- COT 段落级审计天然需要中间断点，单节点流式硬接会更复杂；
- 多节点模式可以逐 beat 判断“写完没”“是否超字”“是否需要重写”。

推荐先采用“多节点，不是旧式碎片化”的折中：

```text
outline-beat-partition
-> beat_write(b1, 300-500 字)
-> beat_completion_audit
-> anti-ai-segment-audit
-> segment_rewrite_if_needed
-> beat_write(b2...)
-> chapter-completion-audit
-> chapter-level-rewrite-if-needed
```

注意，多节点模式不是回到“机械拆句”：

- beat 必须是叙事推进单元，不是按句号切分；
- 每个 beat 都有目标、阻碍、行动、结果；
- beat 完成后再进入下一 beat；
- 章尾由 `chapter-completion-audit` 判断，而不是只看字数。

优先级建议：

1. 先实现多节点 beat 生成 + segment audit；
2. 再接 `chapter-completion-audit`；
3. 再接 `anti-ai-prose-rewrite`；
4. 最后再考虑把同样能力迁回单节点流式模式。

这样更容易定位问题，也更符合“写一段、审一段、修一段”的 COT 思路。

### 6.14 打斗场景专项：不要把战斗写成场景导览

可以，打斗问题能靠这套多节点方案明显改善，但前提是要把“打斗”从场景导向，改成动作编排导向。

现在之所以容易写跑偏，根因不是模型不会写打斗，而是现有提示词里战斗常被描述成：

- 场景铺设
- 氛围渲染
- POV 镜头
- 环境变化
- 角色心理

这些词本身没错，但它们更适合“战前铺垫”“战后余波”“秘境/擂台/副本开场”，不适合一场正打着的搏杀主体。

#### 战斗应该长什么样

一个合格的网文打斗段，核心不是“场景漂亮”，而是“状态变化连续”：

1. **起手**：谁先动，动作是什么，距离多远。
2. **碰撞**：招式/武器/拳脚/身法发生实碰，谁占上风。
3. **代价**：谁受伤、谁失位、谁被逼出底牌。
4. **反制**：战斗状态翻转，主角或对手做出即时调整。
5. **结果**：至少出现一个明确结果，不能悬空停在氛围里。

战斗段落里，环境可以出现，但必须服务动作：

- 不是“风很大，所以显得很紧张”；
- 而是“风把尘土卷进眼里，他偏头，才躲开那一下劈落的刀”。

#### 战斗不该写成什么样

要压掉这些写法：

- 连续多段场景描写，没有实碰。
- 大量心理分析替代动作。
- 一打起来先讲环境、再讲回忆、再讲设定。
- 一直写“他知道、他觉得、他意识到”，但没有流血、位移、受压、反击。
- 把战斗写成“镜头扫场”，没有招式结果。

#### 需要新增的战斗审计维度

建议在 `anti-ai-segment-audit` 或 `chapter-completion-audit` 中，给战斗场景单独加一组检查：

- 是否有明确起手动作；
- 是否有至少一次实质碰撞；
- 是否有受伤/流血/衣物破损/位移失衡等后果；
- 是否有一次即时反制；
- 是否在 1-2 个 beat 内完成状态翻转或阶段推进；
- 是否存在过长的环境/心理空转。

如果这些都没有，战斗就算“写了很多字”，也仍然是空。

#### 战斗节拍建议

战斗最好单独走“战斗 beat”，而不是和普通场景 beat 混用。

推荐节拍：

- `battle_opening`: 起手、逼近、第一击
- `battle_exchange`: 攻防回合、试探、拆招
- `battle_escalation`: 受伤、压制、底牌
- `battle_reversal`: 反制、翻盘、流血
- `battle_end`: 结果、代价、后续钩子

每个 beat 只盯一个动作任务，不要把场景、设定、回忆、心理都塞进去。

#### 对 2500 字章节的判断

可以做到，而且比现在更稳，但条件是：

- 把 `chapter-generation-main` 里的历史性长字数倾向降掉；
- 把 `beat` 预算改成更细的 300-500 字审计单位；
- 把战斗 beat 的“必须完成项”明确成动作结果，而不是场景漂亮；
- 把 `chapter-completion-audit` 作为收束门，而不是只看字数。

比较现实的 2500 字分配是：

- 开场/引战：300-400 字
- 交锋升级：500-600 字
- 核心碰撞：700-800 字
- 反转/受伤/翻盘：500-600 字
- 收尾/钩子：300-400 字

这不是硬切句子，而是把一个章拆成几个叙事推进单元，再让每个单元完成自己的动作任务。


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
- [infrastructure/ai/prompt_packages/nodes/outline-beat-partition/system.md](/Users/leonwei/Documents/workspace/PlotPilot/infrastructure/ai/prompt_packages/nodes/outline-beat-partition/system.md:1)
- [infrastructure/ai/prompt_packages/nodes/anti-ai-chapter-audit/system.md](/Users/leonwei/Documents/workspace/PlotPilot/infrastructure/ai/prompt_packages/nodes/anti-ai-chapter-audit/system.md:1)
- [infrastructure/ai/prompt_packages/nodes/anti-ai-mid-generation-refresh/user.md](/Users/leonwei/Documents/workspace/PlotPilot/infrastructure/ai/prompt_packages/nodes/anti-ai-mid-generation-refresh/user.md:1)
- [infrastructure/ai/prompt_packages/nodes/chapter-state-extraction/system.md](/Users/leonwei/Documents/workspace/PlotPilot/infrastructure/ai/prompt_packages/nodes/chapter-state-extraction/system.md:1)
- [application/engine/rules/mid_generation_refresh.py](/Users/leonwei/Documents/workspace/PlotPilot/application/engine/rules/mid_generation_refresh.py:1)
- [application/engine/rules/stream_ac_scanner.py](/Users/leonwei/Documents/workspace/PlotPilot/application/engine/rules/stream_ac_scanner.py:1)


## 13. 全面修复方案：从固定节拍改为动态执行闭环

### 13.1 总目标

当前问题不是单点提示词不够强，而是章节生成缺少一条稳定闭环：

> 目标字数 + 章纲密度 → 动态拆节拍 → 分段生成 → 段内审计重写 → 章节完成审计 → 必要时局部返修。

需要同时解决四类问题：

- 正文字数远超配置目标；
- 正文出现八股、空泛、AI 味、模板腔；
- 节拍像固定模板，不像按章纲与字数生成的执行单元；
- 打斗场景被写成环境/心理/场景说明，而不是连续动作冲突。

修复原则：

- 所有写作规则、审计规则、重写规则优先落在 `infrastructure/ai/prompt_packages`；
- 业务代码只负责调度节点、传递变量、解析结果、控制返修，不把风格规则硬编码进 Python；
- 多节拍模式先作为主路径，单节拍整章模式暂时降级为兼容/兜底模式；
- 生成结果必须以“是否完成章纲”和“是否控制在目标字数附近”为终点，而不是只看模型有没有输出完。

### 13.2 节拍规划修复

正常节拍应根据目标字数、章纲内容密度、事件因果来拆分，不应固定为起承转合或题材模板。

当前状态：

- `GenerationPreferences.outline_partition_mode` 默认是 `single`；
- `auto_novel_generation_workflow.py` 存在显式 `partition_mode="single"` 的调用路径；
- `outline-beat-partition` 虽然支持动态 atoms，但提示词只把目标字数写成“参考”，没有要求按字数预算计算节拍数；
- `ContextBuilder.MIN_BEAT_WORDS = 800` 会把较细节拍合并，和 300-500 字 COT 段审计目标冲突；
- 题材 Agent 的 `get_beat_templates()` / `get_opening_beats()` 仍有固定模板，容易盖过章纲自身结构。

建议改造：

1. 将全托管主路径切到 `auto` 多节拍。
2. `outline-beat-partition` 输出从简单 atoms 升级为“预算感知 atoms”：
   - `id`
   - `intent`
   - `target_words`
   - `weight`
   - `scene_type`
   - `completion_check`
   - `must_include`
   - `avoid`
3. 节拍数量由预算动态决定：
   - 1800 字以内：3-4 拍；
   - 2500 字左右：4-6 拍；
   - 3000-4000 字：6-8 拍；
   - 大纲密度高时增加拍数但降低单拍字数；
   - 大纲密度低时减少拍数，避免模型用空话填充。
4. 主题模板改为“题材 hint”，只参与 focus / avoid / must_include，不直接替代节拍结构。
5. 开篇固定模板只作为没有有效章纲时的兜底，不应优先于用户章纲。

### 13.3 生成闭环修复

推荐把当前章节生成拆为两层：

- 宏观 beat：按章纲拆出的 4-6 个推进单元；
- 微段 segment：每 300-500 字生成一次，生成后立刻审计、必要时重写。

执行流：

1. `outline-beat-partition`：按章纲与目标字数拆宏观 beat。
2. `beat-segment-plan`：把当前 beat 拆成 1-2 个 300-500 字微段。
3. `chapter-generation-main` 或新增 segment writer：生成当前微段正文。
4. `anti-ai-segment-audit`：审计 AI 味、空泛、八股、比喻滥用、动作缺失。
5. `prose-integrity-audit`：审计缺字、漏字、断句、重复段、残留标记。
6. `chapter-completion-audit`：判断该 beat 是否完成，是否需要补写或收尾。
7. `anti-ai-prose-rewrite`：只重写问题片段，不整章重来。
8. 汇总成章后再跑章末完成审计。

这个流程不输出显式 COT。审计与修订计划只在系统内部使用，最终落盘只保留正文。

### 13.4 字数控制方案

字数控制不能只靠最终截断，否则会造成章节突然断尾。应前置到节拍预算和段落预算。

建议：

- 章节目标 2500 字时，允许窗口为 2300-2700；
- 每个 beat 生成前传入：
  - 当前 beat 目标字数；
  - 当前 beat 最大字数；
  - 已生成字数；
  - 剩余字数；
  - 本 beat 是否必须收束；
- 每个 300-500 字微段生成后统计正文长度；
- 超过当前 beat 预算 15% 时不继续扩写，只允许“压缩收尾”；
- 章节进入最后 20% 预算时，提示词切换为“收束模式”，禁止新增大事件和新人物；
- 章末审计如果发现未完成章纲，应优先局部补写缺失事件，而不是继续自由扩写。

重点：截断只能当安全网，不能当主要字数控制手段。

### 13.5 反 AI 味集中治理

当前系统里已经散落存在反 AI 味、审计、刷新、重写逻辑，需要集中成一个 Prompt Center。

建议新增或整理以下 CPMS 节点：

- `anti-ai-style-canon`：统一风格戒律，沉淀“不要八股”的总规则；
- `anti-ai-generation-guard`：生成前注入，约束正文写法；
- `anti-ai-segment-audit`：300-500 字微段审计；
- `anti-ai-chapter-audit`：章末整体审计；
- `anti-ai-revision-plan`：只输出返修计划；
- `anti-ai-prose-rewrite`：只输出重写后的正文；
- `prose-integrity-audit`：缺字漏字、断句残留、重复片段检查；
- `chapter-completion-audit`：章纲/节拍完成度检查。

这些节点应共享同一套风格定义，避免“东一块西一块”。

反 AI 味核心规则整理：

- 少用抽象判断，多用人物动作和物理后果；
- 少用“不是 A，而是 B”；
- 少用宏大形容词、价值判断、总结句；
- 少用连续排比、连续反问、连续顿悟；
- 少用“仿佛、像是、似乎、某种、难以言喻”这类软化词；
- 比喻只在必要时使用，且必须贴近角色经验；
- 对白要带目的、遮掩、误解、试探，不能像台词说明书；
- 情绪要通过手、眼、呼吸、停顿、选择来显示，不靠旁白反复解释；
- 段落结尾避免统一升华，允许停在动作、物件、未说完的话上。

### 13.6 章节完成审计

章末审计不应只判断质量，还要判断“这一章有没有写完”。

`chapter-completion-audit` 需要检查：

- 章纲每个关键事件是否落地；
- 主角目标是否发生推进；
- 阻碍是否出现并产生实际影响；
- 本章承诺的冲突是否兑现；
- 必要信息是否被交代；
- 章尾是否有阶段性结果；
- 是否强行开新坑导致本章没收；
- 是否为了凑字重复解释同一件事；
- 是否为了压字跳过关键动作。

输出建议：

- `completed: true/false`
- `missing_items`
- `overwritten_items`
- `needs_rewrite_segments`
- `suggested_patch_mode`: `append_closure | rewrite_segment | compress_tail | pass`

### 13.7 缺字漏字与正文完整性审计

新增 `prose-integrity-audit`，不要和文风审计混在一起。

检查项：

- 段落是否突然中断；
- 是否出现半句话、缺主语、缺宾语；
- 是否有重复段落、重复句式、重复人名；
- 是否残留 JSON、Markdown、审计说明、模型自述；
- 是否出现明显错别字、漏字、粘连词；
- 是否有角色名错写、称谓前后不一致；
- 是否发生视角突然漂移；
- 是否有打斗或对话中动作结果缺失。

这个节点适合在段落级和章末都跑一次。

### 13.8 战斗场景专项方案

战斗不能按普通“场景描写”处理，应该按动作链处理。

战斗 beat 建议：

- `battle_opening`：起手、逼近、第一击；
- `battle_exchange`：攻防回合、试探、拆招；
- `battle_escalation`：受伤、压制、底牌；
- `battle_reversal`：反制、翻盘、流血；
- `battle_end`：胜负、代价、后续影响。

战斗生成要求：

- 每 150-250 字必须出现一次实质动作推进；
- 动作必须有结果：命中、闪避、格挡、后退、受伤、失衡、兵器破损、衣物破损、流血；
- 环境只能服务动作，不允许单独铺陈一大段；
- 心理只能短促插入，必须被下一步动作打断或兑现；
- 招式/功法不能只报名字，要写出运动方向、接触点、后果；
- 旁观者反应只能作为战斗结果的反馈，不能替代战斗本身。

战斗审计要求：

- 是否有明确起手；
- 是否有至少一次实质碰撞；
- 是否有受伤、流血、破损、位移、失衡之一；
- 是否有即时反制；
- 是否在 1-2 个 beat 内完成阶段翻转；
- 是否存在过长环境/心理空转；
- 是否把“战斗很激烈”写成旁白，而没有让读者看到激烈。

### 13.9 实施顺序

建议分四步做，避免一次性大改导致无法定位问题。

第一步：修节拍主路径。

- 去掉工作流里写死的 `partition_mode="single"`；
- 让全托管读取 `generation_prefs.outline_partition_mode`；
- 将新书默认或推荐模式改为 `auto`；
- 强化 `outline-beat-partition` 的预算拆拍规则。

第二步：建反 AI 味中心。

- 整理现有 anti-ai prompt；
- 新增段级审计、重写、正文完整性审计节点；
- 把风格戒律统一引用，减少重复和冲突。

第三步：接入 300-500 字 COT 式内部闭环。

- 每个 beat 内按 segment 生成；
- 段后审计；
- 不合格则局部重写；
- 只把正文 append 到最终章节。

第四步：战斗专项。

- 在 `outline-beat-partition` 中识别 combat/battle scene_type；
- 战斗 beat 使用动作链 completion_check；
- 审计不通过时局部重写战斗段。

### 13.10 对 2500 字章节的可行性判断

按这个方案，可以稳定做到 2500 字左右完成一章。

推荐结构：

- 4-6 个宏观 beat；
- 每个 beat 1-2 个 300-500 字 segment；
- 总计约 6-8 个 segment；
- 每段生成后审计，避免最后整章才发现跑偏。

示例预算：

- 开场/引战：350 字；
- 冲突进入：450 字；
- 核心交锋：600 字；
- 反转或代价：500 字；
- 结果落地：350 字；
- 章尾钩子：250 字。

这样既能完成章节，又不会靠环境描写、心理总结和八股句式把字数撑爆。
