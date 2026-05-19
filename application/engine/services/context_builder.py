"""上下文构建器 - 双轨融合版

核心设计：
- 使用 ContextBudgetAllocator 进行洋葱模型优先级挤压
- T0: 强制内容（伏笔、角色锚点、当前幕摘要）—— 绝不删减
- T1: 可压缩内容（图谱子网、近期幕摘要）—— 按比例压缩
- T2: 动态内容（最近章节）—— 动态水位线
- T3: 可牺牲内容（向量召回）—— 预算不足时归零

与 AutoNovelGenerationWorkflow 拼接时：Layer1≈T0+T1，Layer2 段名为 RECENT CHAPTERS（T2），
Layer3 段名为 VECTOR RECALL（T3）；见 assemble_chapter_bundle_context_text。
"""
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from application.engine.dtos.scene_director_dto import SceneDirectorInput

from application.world.services.bible_service import BibleService
from domain.bible.services.relationship_engine import RelationshipEngine
from domain.novel.services.storyline_manager import StorylineManager
from domain.novel.repositories.novel_repository import NovelRepository
from domain.novel.repositories.chapter_repository import ChapterRepository
from domain.novel.repositories.plot_arc_repository import PlotArcRepository
from domain.novel.repositories.foreshadowing_repository import ForeshadowingRepository
from domain.ai.services.vector_store import VectorStore
from domain.ai.services.embedding_service import EmbeddingService
from application.engine.services.context_budget_allocator import ContextBudgetAllocator
from application.engine.dag.plan.schema import ChapterExecutionPlan

logger = logging.getLogger(__name__)


@dataclass
class Beat:
    """微观节拍（Beat）

    将章节大纲拆分为多个微观节拍，强制 AI 放慢节奏，增加感官细节。
    """
    description: str  # 节拍描述
    target_words: int  # 目标字数
    focus: str  # 聚焦点：sensory（感官）、dialogue（对话）、action（动作）、emotion（情绪）
    expansion_hints: List[str] = None  # 扩写维度提示（如何达到目标字数）
    scene_goal: str = ""  # 场景目标（从规划阶段继承）
    transition_from_prev: str = ""  # 🔗 从上一节拍如何过渡（对话延续/动作接续/情绪过渡/场景切换）
    location_id: str = ""  # 微观坐标（由 ATG visit_sequence 绑定；无 ATG 时为空）
    beat_type: str = "progress"  # 节拍类型：setup / progress / confrontation / reveal / payoff / hook
    must_keep: bool = False  # 是否为章纲核心节点；核心节点不得被粗暴吞并
    acceptance_criteria: List[str] = None  # 本节拍必须兑现的要点
    forbidden_drift: str = ""  # 本节拍最容易滑向的空转方式

    def __post_init__(self):
        if self.expansion_hints is None:
            self.expansion_hints = []
        if self.acceptance_criteria is None:
            self.acceptance_criteria = []


class ContextBuilder:
    """上下文构建器（双轨融合版）
    
    智能组装章节生成所需的上下文，使用洋葱模型优先级挤压。
    """

    def __init__(
        self,
        bible_service: BibleService,
        storyline_manager: StorylineManager,
        relationship_engine: RelationshipEngine,
        vector_store: VectorStore,
        novel_repository: NovelRepository,
        chapter_repository: ChapterRepository,
        plot_arc_repository: Optional[PlotArcRepository] = None,
        embedding_service: Optional[EmbeddingService] = None,
        foreshadowing_repository: Optional[ForeshadowingRepository] = None,
        story_node_repository=None,
        bible_repository=None,
        chapter_element_repository=None,
        triple_repository=None,
        # feed-forward 三件套（V8+）：接入后 T0/T1 槽位才会有内容
        causal_edge_repository=None,
        character_state_repository=None,
        narrative_debt_repository=None,
        # 故事线 + 汇流点（供预算分配器使用）
        storyline_repository=None,
        confluence_point_repository=None,
        worldbuilding_repository=None,
    ):
        self.bible_service = bible_service
        self.storyline_manager = storyline_manager
        self.relationship_engine = relationship_engine
        self.vector_store = vector_store
        self.novel_repository = novel_repository
        self.chapter_repository = chapter_repository
        self.plot_arc_repository = plot_arc_repository
        self.embedding_service = embedding_service
        self.foreshadowing_repository = foreshadowing_repository
        self.story_node_repository = story_node_repository
        self.bible_repository = bible_repository
        self.chapter_element_repository = chapter_element_repository
        self.triple_repository = triple_repository
        self.storyline_repository = storyline_repository
        self.confluence_point_repository = confluence_point_repository
        self.worldbuilding_repository = worldbuilding_repository

        # ContextAssembler：提供 ANCHOR / SCARS / DEBT_DUE / CAUSAL_CHAINS 槽位
        context_assembler = None
        try:
            from application.engine.services.context_assembler import ContextAssembler
            context_assembler = ContextAssembler(
                causal_edge_repo=causal_edge_repository,
                character_state_repo=character_state_repository,
                debt_repo=narrative_debt_repository,
                foreshadowing_repo=foreshadowing_repository,
                chapter_repo=chapter_repository,
                bible_repo=bible_repository,
                story_node_repo=story_node_repository,
                novel_repository=novel_repository,
                storyline_repo=storyline_repository,
            )
        except Exception as _e:
            logger.warning("ContextAssembler 初始化失败: %s", _e)

        # MemoryEngine：提供 FACT_LOCK / COMPLETED_BEATS / REVEALED_CLUES 槽位
        memory_engine = None
        if bible_repository:
            try:
                from application.engine.services.memory_engine import MemoryEngine
                from infrastructure.persistence.database.connection import get_database
                memory_engine = MemoryEngine(
                    llm_service=None,
                    bible_repository=bible_repository,
                    db_connection=get_database(),
                )
            except Exception as _e:
                logger.warning("MemoryEngine 初始化失败: %s", _e)

        # 预算分配器（核心组件）
        self.budget_allocator = ContextBudgetAllocator(
            foreshadowing_repository=foreshadowing_repository,
            chapter_repository=chapter_repository,
            bible_repository=bible_repository,
            story_node_repository=story_node_repository,
            chapter_element_repository=chapter_element_repository,
            triple_repository=triple_repository,
            vector_store=vector_store,
            embedding_service=embedding_service,
            context_assembler=context_assembler,
            memory_engine=memory_engine,
            storyline_repository=storyline_repository,
            confluence_point_repository=confluence_point_repository,
            worldbuilding_repository=worldbuilding_repository,
        )

    def estimate_tokens(self, text: str) -> int:
        """估算文本 token 数（委托 ContextBudgetAllocator）。"""
        return self.budget_allocator.estimate_tokens(text)

    def build_voice_anchor_system_section(self, novel_id: str) -> str:
        """Bible 角色声线/小动作锚点"""
        return self.bible_service.build_character_voice_anchor_section(novel_id)

    def build_context(
        self,
        novel_id: str,
        chapter_number: int,
        outline: str,
        max_tokens: int = 35000,
        scene_director: SceneDirectorInput = None,
    ) -> str:
        """构建上下文（使用预算分配器）
        
        Args:
            novel_id: 小说 ID
            chapter_number: 章节号
            outline: 章节大纲
            max_tokens: 最大 token 数
            scene_director: 场记（模型或 dict；allocator 内统一为 dict）
        
        Returns:
            组装好的上下文字符串
        """
        allocation = self.budget_allocator.allocate(
            novel_id=novel_id,
            chapter_number=chapter_number,
            outline=outline,
            total_budget=max_tokens,
            scene_director=scene_director,
        )
        
        return allocation.get_final_context()

    def build_structured_context(
        self,
        novel_id: str,
        chapter_number: int,
        outline: str,
        max_tokens: int = 35000,
        scene_director: SceneDirectorInput = None,
    ) -> Dict[str, Any]:
        """构建结构化上下文，返回详细信息
        
        Returns:
            {
                "layer1_text": "核心上下文（T0+T1）",
                "layer2_text": "最近章节（T2）",
                "layer3_text": "向量召回（T3）",
                "token_usage": {
                    "layer1": int,
                    "layer2": int,
                    "layer3": int,
                    "total": int,
                },
            }
        """
        allocation = self.budget_allocator.allocate(
            novel_id=novel_id,
            chapter_number=chapter_number,
            outline=outline,
            total_budget=max_tokens,
            scene_director=scene_director,
        )
        
        # 从 BudgetAllocation 中提取三层内容
        layer1_parts = []
        layer2_parts = []
        layer3_parts = []
        
        layer1_tokens = 0
        layer2_tokens = 0
        layer3_tokens = 0
        
        for name, slot in allocation.slots.items():
            if not slot.content.strip():
                continue
            
            if slot.tier.value in ["t0_critical", "t1_compressible"]:
                layer1_parts.append(f"=== {slot.name.upper()} ===\n{slot.content}")
                layer1_tokens += slot.tokens
            elif slot.tier.value == "t2_dynamic":
                layer2_parts.append(f"=== {slot.name.upper()} ===\n{slot.content}")
                layer2_tokens += slot.tokens
            elif slot.tier.value == "t3_sacrificial":
                layer3_parts.append(f"=== {slot.name.upper()} ===\n{slot.content}")
                layer3_tokens += slot.tokens
        
        return {
            "layer1_text": "\n\n".join(layer1_parts),
            "layer2_text": "\n\n".join(layer2_parts),
            "layer3_text": "\n\n".join(layer3_parts),
            "token_usage": {
                "layer1": layer1_tokens,
                "layer2": layer2_tokens,
                "layer3": layer3_tokens,
                "total": allocation.used_tokens,
            },
        }

    # 扩写维度提示（根据节拍类型动态注入）
    EXPANSION_HINTS = {
        "action": [
            "加入招式物理碰撞细节：打击感、力量传导、声音",
            "描写环境破坏：招式对周围的影响、碎片飞溅",
            "旁观者反应：惊呼、恐惧、议论",
            "战斗节奏变化：快攻、僵持、反击",
        ],
        "dialogue": [
            "加入微表情描写：眼神变化、嘴角牵动",
            "肢体语言：手势、站姿、身体朝向",
            "潜台词暗示：话中有话、欲言又止",
            "对话节奏：打断、沉默、抢话",
        ],
        "sensory": [
            "光影变化：明暗对比、光线方向",
            "声音细节：环境音、脚步声、呼吸声",
            "温度触感：冷热、干湿、材质纹理",
            "气味味道：空气中的气息、食物香气",
        ],
        "emotion": [
            "内心独白：想法、疑问、自我说服",
            "回忆闪回：与当前情绪相关的往事",
            "身体反应：心跳、手抖、冷汗",
            "情绪转变：从一种情绪到另一种的过渡",
        ],
        "suspense": [
            "心理推演：主角的推理过程、疑点",
            "五官感知变化：异常的细节、违和感",
            "时间拉长：等待、观察、试探",
            "悬念钩子：未解之谜、意外转折",
        ],
        "hook": [
            "开篇冲击：立即抓住读者的事件或画面",
            "人物特质展示：通过行动而非描述",
            "冲突暗示：不安、危机、悬念",
            "世界观速写：通过细节而非说明",
        ],
        "character_intro": [
            "外貌特征：独特的外表标记",
            "性格展示：通过言行而非描述",
            "关系暗示：与其他角色的互动方式",
            "记忆点：让读者记住的特征",
        ],
    }

    # 节拍数量上限：全局硬帽，实际以区间策略为准
    MAX_BEATS = 8
    # 章节目标字数 -> 节拍上限
    CHAPTER_BEAT_POLICY = [
        {"min_words": 0, "max_words": 900, "max_beats": 2},
        {"min_words": 901, "max_words": 1500, "max_beats": 3},
        {"min_words": 1501, "max_words": 2800, "max_beats": 4},
        {"min_words": 2801, "max_words": 4000, "max_beats": 5},
        {"min_words": 4001, "max_words": 6000, "max_beats": 6},
        {"min_words": 6001, "max_words": 99999, "max_beats": 7},
    ]
    # 按节拍类型控制“相对篇幅权重”，实际字数应随整章目标字数等比放大
    BEAT_TYPE_WORD_WEIGHTS = {
        "setup": 0.9,
        "progress": 1.0,
        "confrontation": 1.22,
        "reveal": 1.24,
        "payoff": 0.92,
        "hook": 0.82,
    }
    # 动态字数边界：相对于“本章平均每拍字数”的倍率，而不是固定绝对字数
    BEAT_TYPE_DYNAMIC_RATIOS = {
        "setup": (0.65, 1.05),
        "progress": (0.80, 1.20),
        "confrontation": (0.90, 1.55),
        "reveal": (0.90, 1.60),
        "payoff": (0.70, 1.10),
        "hook": (0.55, 1.00),
    }

    def magnify_outline_to_beats(
        self,
        chapter_number: int,
        outline: str,
        target_chapter_words: int = 2500,
        beat_sheet: Optional[Any] = None,
        chapter_execution_plan: Optional[ChapterExecutionPlan] = None,
        scene_director: Optional[Any] = None,
    ) -> List[Beat]:
        """节拍放大器：将章节大纲拆分为微观节拍

        核心策略（选项 C：动态弹性扩写与前置预估）：
        1. 优先使用章前执行计划 ``chapter_execution_plan``（planning_outline_partition / CPMS 拆拍）
        2. 否则使用规划阶段的 BeatSheet（含 estimated_words）
        3. 无上述二者时回退到关键词识别 + 25% 均分
        4. 根据 focus 类型注入扩写维度提示（expansion_hints）
        5. 拍数上限 MAX_BEATS；每拍目标字数 < MIN_BEAT_WORDS 时合并相邻拍
        """
        beats: List[Beat]
        # === 路径 A：章前执行计划（与 DAG planning_outline_partition 同源）===
        if chapter_execution_plan is not None and chapter_execution_plan.atoms:
            beats = self._build_beats_from_execution_plan(
                chapter_execution_plan, outline, target_chapter_words
            )
        # === 路径 B：有规划阶段的 BeatSheet ===
        elif beat_sheet is not None and hasattr(beat_sheet, 'scenes') and beat_sheet.scenes:
            beats = self._build_beats_from_beat_sheet(beat_sheet, outline, target_chapter_words)
        else:
            # === 路径 C：无 Plan/BeatSheet，回退到关键词识别 ===
            beats = self._build_beats_from_outline(chapter_number, outline, target_chapter_words)

        beats = self._cap_and_merge_beats(beats, target_chapter_words)
        self._bind_atg_locations_if_present(beats, scene_director)
        return beats

    def _build_beats_from_execution_plan(
        self,
        plan: ChapterExecutionPlan,
        outline: str,
        target_chapter_words: int,
    ) -> List[Beat]:
        """将 ``ChapterExecutionPlan.atoms`` 投影为微观节拍（须落实章纲意图）。"""
        atoms = plan.atoms
        if not atoms:
            return []
        total_w = sum(max(0.01, float(a.weight)) for a in atoms)
        mode = (plan.provenance or {}).get("mode", "")
        logger.info(
            "节拍放大器（章前执行计划）：%d 拍，provenance_mode=%s outline≈%d 字，整章目标 %d 字",
            len(atoms),
            mode,
            len((outline or "").strip()),
            target_chapter_words,
        )
        beats: List[Beat] = []
        for atom in atoms:
            intent = (atom.intent or "").strip()
            if not intent:
                continue
            share = max(0.01, float(atom.weight)) / total_w
            w = max(1, int(target_chapter_words * share))
            ext = atom.extensions if isinstance(atom.extensions, dict) else {}
            raw_focus = ext.get("focus") or ext.get("type")
            if isinstance(raw_focus, str) and raw_focus.strip():
                focus_s = raw_focus.strip()
            else:
                focus_s = self._infer_focus_from_outline(intent)
            trans = ext.get("transition_from_prev")
            transition = str(trans).strip() if trans else ""
            loc_id = ext.get("location_id")
            location_id = str(loc_id).strip() if isinstance(loc_id, str) and loc_id.strip() else ""
            beat_type = self._infer_beat_type(intent, ext)
            acceptance = self._build_acceptance_criteria(intent, beat_type)
            forbidden_drift = self._build_forbidden_drift(beat_type)

            beats.append(
                Beat(
                    description=(
                        "【章纲节选·须落实】以下要点必须写入正文（可合理扩写，不得跳过核心因果；"
                        "人物姓名须与 Bible 一致）：\n"
                        + intent
                    ),
                    target_words=w,
                    focus=focus_s,
                    expansion_hints=self._generate_expansion_hints(focus_s, w),
                    scene_goal=intent,
                    transition_from_prev=transition,
                    location_id=location_id,
                    beat_type=beat_type,
                    must_keep=True,
                    acceptance_criteria=acceptance,
                    forbidden_drift=forbidden_drift,
                )
            )
        return beats

    def _bind_atg_locations_if_present(self, beats: List[Beat], scene_director: Optional[Any]) -> None:
        """若场记携带 ATG，将 visit_sequence 映射到各节拍。"""
        if not beats or scene_director is None:
            return
        graph_payload = getattr(scene_director, "action_transition_graph", None)
        if graph_payload is None:
            return
        try:
            from application.engine.services.spatial_coherence import assign_visit_locations_to_beats
        except ImportError:
            return
        seq = list(graph_payload.visit_sequence or [])
        if not seq:
            entry_first = [n.location_id for n in graph_payload.nodes if getattr(n, "is_entry_point", False)]
            seen = set(entry_first)
            tail = [n.location_id for n in graph_payload.nodes if n.location_id and n.location_id not in seen]
            seq = entry_first + tail
        if not seq:
            seq = [n.location_id for n in graph_payload.nodes if getattr(n, "location_id", "").strip()]
        assign_visit_locations_to_beats(beats, seq)

    def _cap_and_merge_beats(self, beats: List[Beat], target_chapter_words: int) -> List[Beat]:
        """控制节拍数量与字数分布。

        新策略：
        1. 章节目标字数先决定本章允许的最大拍数。
        2. 优先保留 must_keep 的章纲核心节点；不得因最低字数阈值直接吞并。
        3. 重新分配各拍字数时，按 beat_type 约束详略，而不是平均使力。
        """
        if not beats:
            return beats

        max_beats = self._resolve_max_beats(target_chapter_words)

        # 先按章节容量压拍数，但尽量不动 must_keep
        while len(beats) > max_beats:
            merge_idx = self._pick_merge_index(beats, allow_force=True)
            if merge_idx is None:
                break
            beats = self._merge_two_beats(beats, merge_idx)

        self._rebalance_target_words(beats, target_chapter_words)

        logger.info(
            "节拍整形：%d 拍（上限=%d），各拍字数=%s，总目标=%d",
            len(beats),
            max_beats,
            [b.target_words for b in beats],
            sum(b.target_words for b in beats),
        )
        return beats

    def _merge_two_beats(self, beats: List[Beat], idx: int) -> List[Beat]:
        """将 beats[idx] 与 beats[idx+1] 合并为一拍。"""
        a, b = beats[idx], beats[idx + 1]
        merged = Beat(
            description=f"{a.description} / {b.description}",
            target_words=a.target_words + b.target_words,
            focus=a.focus,  # 保留前拍的 focus 类型
            expansion_hints=list(dict.fromkeys(a.expansion_hints + b.expansion_hints))[:4],
            scene_goal=f"{a.scene_goal or ''} {b.scene_goal or ''}".strip(),
            transition_from_prev=a.transition_from_prev or '',
            location_id=(a.location_id or b.location_id or "").strip(),
            beat_type=self._merge_beat_types(a.beat_type, b.beat_type),
            must_keep=bool(a.must_keep or b.must_keep),
            acceptance_criteria=list(dict.fromkeys((a.acceptance_criteria or []) + (b.acceptance_criteria or [])))[:6],
            forbidden_drift=a.forbidden_drift or b.forbidden_drift,
        )
        return beats[:idx] + [merged] + beats[idx + 2:]

    def _build_beats_from_beat_sheet(
        self,
        beat_sheet: Any,
        outline: str,
        target_chapter_words: int,
    ) -> List[Beat]:
        """从 BeatSheet 构建 Beat 列表（使用规划阶段的预估字数）"""
        beats = []
        scenes = beat_sheet.scenes

        for i, scene in enumerate(scenes):
            # 从 Scene 提取信息
            estimated_words = getattr(scene, 'estimated_words', 600)
            goal = getattr(scene, 'goal', '')
            title = getattr(scene, 'title', '')
            tone = getattr(scene, 'tone', '')

            # 根据 goal/标题 推断 focus 类型
            focus = self._infer_focus_from_scene(scene, outline)

            # 生成扩写维度提示
            expansion_hints = self._generate_expansion_hints(focus, estimated_words)

            beat = Beat(
                description=f"{title}：{goal}" if goal else title,
                target_words=estimated_words,
                focus=focus,
                expansion_hints=expansion_hints,
                scene_goal=goal,
                transition_from_prev=getattr(scene, 'transition_from_prev', '') or '',
                beat_type=self._infer_beat_type(goal or title, {"tone": tone}),
                must_keep=True,
                acceptance_criteria=self._build_acceptance_criteria(goal or title, self._infer_beat_type(goal or title, {"tone": tone})),
                forbidden_drift=self._build_forbidden_drift(self._infer_beat_type(goal or title, {"tone": tone})),
            )
            beats.append(beat)

        # 验证总字数
        total_estimated = sum(b.target_words for b in beats)
        logger.info(
            f"节拍放大器（BeatSheet）：{len(beats)} 个场景，"
            f"预估总字数 {total_estimated} 字（目标 {target_chapter_words} 字）"
        )

        # 如果总字数差距过大，发出警告但不强制调整
        if total_estimated < target_chapter_words * 0.7:
            logger.warning(
                f"规划阶段预估字数 {total_estimated} 低于目标 {target_chapter_words} 的 70%，"
                f"将在章节完成时弹性处理"
            )

        return beats

    def _segment_user_outline(self, outline: str) -> List[str]:
        """将用户章纲拆成多条，供「章纲优先」节拍；支持编号列表、项目符号、空行段、单段按句切分。"""
        text = (outline or "").strip()
        if not text:
            return []
        if re.search(r"(?m)^\s*\d+[\.、．\)]", text):
            parts = re.split(r"\n(?=\s*\d+[\.、．\)]\s)", text)
            segs = [p.strip() for p in parts if p.strip()]
            if len(segs) >= 2:
                return segs
        if re.search(r"(?m)^\s*[-*•]\s+\S", text):
            parts = re.split(r"\n(?=\s*[-*•]\s)", text)
            segs = [p.strip() for p in parts if p.strip()]
            if len(segs) >= 2:
                return segs
        paras = [p.strip() for p in re.split(r"\n\s*\n+", text) if p.strip()]
        if len(paras) >= 2:
            return paras
        if len(text) >= 20:
            # 中文句间无空格，不依赖 \s+ ——直接按句末标点切分
            sents = [
                s.strip()
                for s in re.split(r"(?<=[。！？；])", text)
                if len(s.strip()) > 8
            ]
            if len(sents) >= 2:
                return sents
        if len(text) >= 400:
            n = min(self.MAX_BEATS, max(2, (len(text) + 499) // 500))
            approx = max(1, len(text) // n)
            segs: List[str] = []
            idx = 0
            for k in range(n):
                if k == n - 1:
                    chunk = text[idx:].strip()
                else:
                    end = min(len(text), idx + approx)
                    brk = end
                    for j in range(end, min(len(text), end + 80)):
                        if text[j] in "。！？；":
                            brk = j + 1
                            break
                    chunk = text[idx:brk].strip()
                    idx = brk
                if chunk:
                    segs.append(chunk)
            if len(segs) >= 2:
                return segs
        return [text]

    def _build_beats_from_outline_segments(
        self,
        segments: List[str],
        target_chapter_words: int,
    ) -> List[Beat]:
        """按用户章纲条文生成节拍（每段必须落实，字数按段长比例分配）。"""
        clean = [s.strip() for s in segments if s and s.strip()]
        if not clean:
            return []
        total_w = sum(max(1, len(s)) for s in clean)
        beats: List[Beat] = []
        for seg in clean:
            w = max(1, int(target_chapter_words * max(1, len(seg)) / total_w))
            focus = self._infer_focus_from_outline(seg)
            beats.append(
                Beat(
                    description=(
                        "【章纲节选·须落实】以下要点必须写入正文（可合理扩写，不得跳过核心因果；"
                        "人物姓名须与 Bible 一致）：\n"
                        + seg
                    ),
                    target_words=w,
                    focus=focus,
                    expansion_hints=self._generate_expansion_hints(focus, w),
                    beat_type=self._infer_beat_type(seg),
                    must_keep=True,
                    acceptance_criteria=self._build_acceptance_criteria(seg, self._infer_beat_type(seg)),
                    forbidden_drift=self._build_forbidden_drift(self._infer_beat_type(seg)),
                )
            )
        return beats

    def _build_beats_from_outline(
        self,
        chapter_number: int,
        outline: str,
        target_chapter_words: int,
    ) -> List[Beat]:
        """无 BeatSheet 时，从大纲关键词推断节拍（回退逻辑）"""
        raw = (outline or "").strip()
        segments = self._segment_user_outline(raw)
        outline_chars = len(raw)
        if len(segments) >= 2 or (len(segments) == 1 and outline_chars >= 15):
            beats = self._build_beats_from_outline_segments(segments, target_chapter_words)
            logger.info(
                "节拍放大器（章纲优先）：用户大纲拆为 %d 个节拍，章纲约 %d 字，整章目标 %d 字",
                len(beats),
                outline_chars,
                target_chapter_words,
            )
            return beats

        beats = []
        base_beat_words = max(400, int(target_chapter_words * 0.25))

        # 开篇黄金法则前三章特殊拦截
        if chapter_number == 1:
            beats = [
                Beat(
                    description="开篇黄金法则：展现核心冲突，介绍主角出场，建立情感冲击（前300字内必须抓住读者）",
                    target_words=int(base_beat_words * 1.2),
                    focus="hook",
                    expansion_hints=self._generate_expansion_hints("hook", int(base_beat_words * 1.2)),
                    beat_type="hook",
                ),
                Beat(
                    description="剧情引入及人物初步互动：展现主角特质并暗示即将发生的事件",
                    target_words=int(base_beat_words * 1.5),
                    focus="character_intro",
                    expansion_hints=self._generate_expansion_hints("character_intro", int(base_beat_words * 1.5)),
                    beat_type="progress",
                ),
                Beat(
                    description="世界观或当前场景细节：通过具体行动展现，不用抽象叙述",
                    target_words=int(base_beat_words * 1.3),
                    focus="sensory",
                    expansion_hints=self._generate_expansion_hints("sensory", int(base_beat_words * 1.3)),
                    beat_type="setup",
                ),
                Beat(
                    description="埋下后续剧情伏笔或抛出首个悬念：铺垫第二章",
                    target_words=int(base_beat_words * 1.0),
                    focus="suspense",
                    expansion_hints=self._generate_expansion_hints("suspense", int(base_beat_words * 1.0)),
                    beat_type="hook",
                ),
            ]
        elif chapter_number == 2:
            beats = [
                Beat(
                    description="承接首章悬念：深化关键人物关系，展现性格差异",
                    target_words=int(base_beat_words * 1.3),
                    focus="dialogue",
                    expansion_hints=self._generate_expansion_hints("dialogue", int(base_beat_words * 1.3)),
                    beat_type="progress",
                ),
                Beat(
                    description="推进主要情节线：引入新的次要冲突或阻碍",
                    target_words=int(base_beat_words * 1.8),
                    focus="action",
                    expansion_hints=self._generate_expansion_hints("action", int(base_beat_words * 1.8)),
                    beat_type="confrontation",
                ),
                Beat(
                    description="情绪细节及内心活动：展示人物面对变故的真实反映",
                    target_words=int(base_beat_words * 1.0),
                    focus="emotion",
                    expansion_hints=self._generate_expansion_hints("emotion", int(base_beat_words * 1.0)),
                    beat_type="payoff",
                ),
                Beat(
                    description="为第三章冲突高潮做气氛铺垫",
                    target_words=int(base_beat_words * 0.8),
                    focus="suspense",
                    expansion_hints=self._generate_expansion_hints("suspense", int(base_beat_words * 0.8)),
                    beat_type="hook",
                ),
            ]
        elif chapter_number == 3:
            beats = [
                Beat(
                    description="前三章的剧情小结或高潮前奏：紧张气氛描写",
                    target_words=int(base_beat_words * 1.0),
                    focus="sensory",
                    expansion_hints=self._generate_expansion_hints("sensory", int(base_beat_words * 1.0)),
                    beat_type="setup",
                ),
                Beat(
                    description="冲突爆发/悬念高潮：激烈的动作或对峙",
                    target_words=int(base_beat_words * 2.0),
                    focus="action",
                    expansion_hints=self._generate_expansion_hints("action", int(base_beat_words * 2.0)),
                    beat_type="confrontation",
                ),
                Beat(
                    description="暴露深层问题或引出更高层面人物背景",
                    target_words=int(base_beat_words * 1.3),
                    focus="emotion",
                    expansion_hints=self._generate_expansion_hints("emotion", int(base_beat_words * 1.3)),
                    beat_type="reveal",
                ),
                Beat(
                    description="建立长线悬念结局：为整卷后续发展铺设巨大好奇心",
                    target_words=int(base_beat_words * 0.7),
                    focus="suspense",
                    expansion_hints=self._generate_expansion_hints("suspense", int(base_beat_words * 0.7)),
                    beat_type="hook",
                ),
            ]
        # 根据大纲关键词推断
        elif "争吵" in outline or "冲突" in outline or "质问" in outline:
            beats = self._build_conflict_beats(base_beat_words)
        elif "战斗" in outline or "打斗" in outline or "对决" in outline:
            beats = self._build_battle_beats(base_beat_words)
        elif "发现" in outline or "真相" in outline or "揭露" in outline:
            beats = self._build_revelation_beats(base_beat_words)
        else:
            beats = self._build_default_beats(base_beat_words)

        logger.info(
            f"节拍放大器（回退）：将大纲拆分为 {len(beats)} 个节拍，"
            f"目标 {sum(b.target_words for b in beats)} 字"
        )
        return beats

    def _infer_focus_from_scene(self, scene: Any, outline: str) -> str:
        """从 Scene 推断 focus 类型"""
        goal = getattr(scene, 'goal', '') or ''
        title = getattr(scene, 'title', '') or ''
        combined = f"{title} {goal}".lower()

        # 关键词匹配
        if any(kw in combined for kw in ["战斗", "打斗", "对决", "攻击", "招式"]):
            return "action"
        if any(kw in combined for kw in ["对话", "争吵", "谈判", "质问", "对峙"]):
            return "dialogue"
        if any(kw in combined for kw in ["悬念", "谜团", "发现", "真相", "揭露"]):
            return "suspense"
        if any(kw in combined for kw in ["情绪", "内心", "回忆", "痛苦", "挣扎"]):
            return "emotion"
        if any(kw in combined for kw in ["环境", "场景", "氛围", "感官"]):
            return "sensory"

        # 默认根据大纲推断
        return self._infer_focus_from_outline(outline)

    def _infer_focus_from_outline(self, outline: str) -> str:
        """从大纲推断 focus 类型"""
        combined = outline.lower()
        if any(kw in combined for kw in ["战斗", "打斗", "对决"]):
            return "action"
        if any(kw in combined for kw in ["争吵", "对话", "谈判"]):
            return "dialogue"
        if any(kw in combined for kw in ["发现", "真相", "悬念"]):
            return "suspense"
        if any(kw in combined for kw in ["情绪", "内心", "回忆"]):
            return "emotion"
        return "sensory"

    def _generate_expansion_hints(self, focus: str, target_words: int) -> List[str]:
        """根据 focus 类型和目标字数生成扩写维度提示"""
        base_hints = self.EXPANSION_HINTS.get(focus, [])

        # 根据目标字数调整提示数量
        if target_words >= 1000:
            # 高字数节拍：给出更多扩写方向
            return base_hints[:4]
        elif target_words >= 600:
            # 中等字数：给出 2-3 个方向
            return base_hints[:3]
        else:
            # 低字数节拍：只需 1-2 个方向
            return base_hints[:2]

    def _build_conflict_beats(self, base_beat_words: int) -> List[Beat]:
        """构建冲突场景的节拍"""
        return [
            Beat(
                description="场景氛围描写：压抑的环境、紧张的气氛、人物的微表情",
                target_words=int(base_beat_words * 0.9),
                focus="sensory",
                expansion_hints=self._generate_expansion_hints("sensory", int(base_beat_words * 0.9)),
            ),
            Beat(
                description="冲突爆发：主角的质问、对方的反应、情绪的升级",
                target_words=int(base_beat_words * 1.4),
                focus="dialogue",
                expansion_hints=self._generate_expansion_hints("dialogue", int(base_beat_words * 1.4)),
            ),
            Beat(
                description="情绪细节：内心独白、回忆闪回、痛苦的挣扎",
                target_words=int(base_beat_words * 1.2),
                focus="emotion",
                expansion_hints=self._generate_expansion_hints("emotion", int(base_beat_words * 1.2)),
            ),
            Beat(
                description="冲突结果：决裂、离开、或暂时妥协（不要轻易和好）",
                target_words=int(base_beat_words * 0.9),
                focus="action",
                expansion_hints=self._generate_expansion_hints("action", int(base_beat_words * 0.9)),
            ),
        ]

    def _build_battle_beats(self, base_beat_words: int) -> List[Beat]:
        """构建战斗场景的节拍"""
        return [
            Beat(
                description="战前准备：环境描写、双方对峙、紧张的气氛",
                target_words=int(base_beat_words * 0.7),
                focus="sensory",
                expansion_hints=self._generate_expansion_hints("sensory", int(base_beat_words * 0.7)),
            ),
            Beat(
                description="第一回合：试探性攻击、展示能力、观察弱点",
                target_words=int(base_beat_words * 1.0),
                focus="action",
                expansion_hints=self._generate_expansion_hints("action", int(base_beat_words * 1.0)),
            ),
            Beat(
                description="战斗升级：全力以赴、招式碰撞、环境破坏",
                target_words=int(base_beat_words * 1.2),
                focus="action",
                expansion_hints=self._generate_expansion_hints("action", int(base_beat_words * 1.2)),
            ),
            Beat(
                description="转折点：意外发生、底牌揭露、或受伤",
                target_words=int(base_beat_words * 0.9),
                focus="emotion",
                expansion_hints=self._generate_expansion_hints("emotion", int(base_beat_words * 0.9)),
            ),
            Beat(
                description="战斗结束：胜负揭晓、战后状态、后续影响",
                target_words=int(base_beat_words * 0.6),
                focus="action",
                expansion_hints=self._generate_expansion_hints("action", int(base_beat_words * 0.6)),
            ),
        ]

    def _build_revelation_beats(self, base_beat_words: int) -> List[Beat]:
        """构建真相揭露场景的节拍"""
        return [
            Beat(
                description="线索汇聚：主角回忆之前的疑点、逐步推理",
                target_words=int(base_beat_words * 1.2),
                focus="emotion",
                expansion_hints=self._generate_expansion_hints("emotion", int(base_beat_words * 1.2)),
            ),
            Beat(
                description="真相揭露：关键证据出现、震惊的反应、世界观崩塌",
                target_words=int(base_beat_words * 1.8),
                focus="dialogue",
                expansion_hints=self._generate_expansion_hints("dialogue", int(base_beat_words * 1.8)),
            ),
            Beat(
                description="情绪余波：接受现实、决定下一步行动",
                target_words=int(base_beat_words * 1.3),
                focus="emotion",
                expansion_hints=self._generate_expansion_hints("emotion", int(base_beat_words * 1.3)),
            ),
        ]

    def _build_default_beats(self, base_beat_words: int) -> List[Beat]:
        """构建默认「起承转合」四节拍"""
        return [
            Beat(
                description="起：交代场景与人物状态，抛出本章要处理的具体麻烦或悬念（可小但须清晰）。",
                target_words=base_beat_words,
                focus="sensory",
                expansion_hints=self._generate_expansion_hints("sensory", base_beat_words),
                beat_type="setup",
            ),
            Beat(
                description="承：阻碍升级或对手施压，人物关系或信息出现新变化。",
                target_words=base_beat_words,
                focus="dialogue",
                expansion_hints=self._generate_expansion_hints("dialogue", base_beat_words),
                beat_type="progress",
            ),
            Beat(
                description="转：矛盾正面爆发或人物被迫对峙，局势进入高压状态。",
                target_words=base_beat_words,
                focus="action",
                expansion_hints=self._generate_expansion_hints("action", base_beat_words),
                beat_type="confrontation",
            ),
            Beat(
                description="合：阶段性结果或反馈落地，同时抛出下一章钩子（勿提前剧透全书谜底）。",
                target_words=base_beat_words,
                focus="suspense",
                expansion_hints=self._generate_expansion_hints("suspense", base_beat_words),
                beat_type="payoff",
            ),
            Beat(
                description="尾钩：保留一个新问题、新代价或新目标，形成明确追读牵引。",
                target_words=int(base_beat_words * 0.75),
                focus="suspense",
                expansion_hints=self._generate_expansion_hints("suspense", int(base_beat_words * 0.75)),
                beat_type="hook",
            ),
        ]

    def _resolve_max_beats(self, target_chapter_words: int) -> int:
        for policy in self.CHAPTER_BEAT_POLICY:
            if policy["min_words"] <= target_chapter_words <= policy["max_words"]:
                return min(int(policy["max_beats"]), self.MAX_BEATS)
        return self.MAX_BEATS

    def _pick_merge_index(self, beats: List[Beat], allow_force: bool = False) -> Optional[int]:
        min_sum = None
        merge_idx: Optional[int] = None
        for i in range(len(beats) - 1):
            a = beats[i]
            b = beats[i + 1]
            if a.must_keep and b.must_keep and not allow_force:
                continue
            penalty = 0
            if a.must_keep or b.must_keep:
                penalty += 2_000
            if a.beat_type in {"confrontation", "reveal"} or b.beat_type in {"confrontation", "reveal"}:
                penalty += 5_000 if not allow_force else 2_500
            if a.beat_type == "hook" and b.beat_type == "hook":
                penalty += 800
            s = a.target_words + b.target_words + penalty
            if min_sum is None or s < min_sum:
                min_sum = s
                merge_idx = i
        return merge_idx

    def _rebalance_target_words(self, beats: List[Beat], target_chapter_words: int) -> None:
        if not beats:
            return
        avg_words = max(1, int(target_chapter_words / max(len(beats), 1)))
        weights: List[int] = []
        for beat in beats:
            weight = float(self.BEAT_TYPE_WORD_WEIGHTS.get(beat.beat_type, self.BEAT_TYPE_WORD_WEIGHTS["progress"]))
            if beat.must_keep:
                weight *= 1.05
            weights.append(weight)

        total_weight = float(sum(weights) or 1.0)
        mins: List[int] = []
        maxs: List[int] = []
        assigned: List[int] = []
        for idx, beat in enumerate(beats):
            lo_ratio, hi_ratio = self.BEAT_TYPE_DYNAMIC_RATIOS.get(
                beat.beat_type,
                self.BEAT_TYPE_DYNAMIC_RATIOS["progress"],
            )
            min_words = max(1, int(avg_words * lo_ratio))
            max_words = max(min_words, int(avg_words * hi_ratio))
            target = int(round(target_chapter_words * weights[idx] / total_weight))
            mins.append(min_words)
            maxs.append(max_words)
            assigned.append(max(min_words, min(max_words, target)))

        current_total = sum(assigned)
        delta = target_chapter_words - current_total

        if delta > 0:
            room_total = sum(maxs[i] - assigned[i] for i in range(len(beats)))
            if room_total > 0:
                for i in range(len(beats)):
                    room = maxs[i] - assigned[i]
                    if room <= 0:
                        continue
                    add = min(room, int(delta * room / room_total))
                    assigned[i] += add
                delta = target_chapter_words - sum(assigned)
            while delta > 0:
                progress = False
                for i in sorted(range(len(beats)), key=lambda x: (weights[x], maxs[x] - assigned[x]), reverse=True):
                    room = maxs[i] - assigned[i]
                    if room <= 0:
                        continue
                    add = min(room, delta)
                    assigned[i] += add
                    delta -= add
                    progress = True
                    if delta == 0:
                        break
                if not progress:
                    break
        elif delta < 0:
            deficit = -delta
            reducible_total = sum(assigned[i] - mins[i] for i in range(len(beats)))
            if reducible_total > 0:
                for i in range(len(beats)):
                    reducible = assigned[i] - mins[i]
                    if reducible <= 0:
                        continue
                    cut = min(reducible, int(deficit * reducible / reducible_total))
                    assigned[i] -= cut
                deficit = sum(assigned) - target_chapter_words
            while deficit > 0:
                progress = False
                for i in sorted(range(len(beats)), key=lambda x: (assigned[x] - mins[x], -weights[x]), reverse=True):
                    reducible = assigned[i] - mins[i]
                    if reducible <= 0:
                        continue
                    cut = min(reducible, deficit)
                    assigned[i] -= cut
                    deficit -= cut
                    progress = True
                    if deficit == 0:
                        break
                if not progress:
                    break

        for idx, beat in enumerate(beats):
            beat.target_words = assigned[idx]

    def _merge_beat_types(self, left: str, right: str) -> str:
        priority = {"setup": 1, "progress": 2, "payoff": 3, "hook": 4, "confrontation": 5, "reveal": 6}
        return left if priority.get(left, 0) >= priority.get(right, 0) else right

    def _infer_beat_type(self, text: str, ext: Optional[Dict[str, Any]] = None) -> str:
        combined = f"{text or ''} {ext or {}}"
        if any(kw in combined for kw in ["觉醒", "揭示", "揭露", "真相", "记忆涌入", "规则丝线", "答案浮现", "看见本质"]):
            return "reveal"
        if any(kw in combined for kw in ["对峙", "冲突", "摊牌", "爆发", "第一鞭", "反击", "高潮", "对决", "施压", "鞭刑"]):
            return "confrontation"
        if any(kw in combined for kw in ["回报", "反馈", "结果", "余波", "代价", "后果", "落地", "回应", "接受现实"]):
            return "payoff"
        if any(kw in combined for kw in ["悬念", "钩子", "伏笔", "铺垫第二章", "留下问题"]):
            return "hook"
        if any(kw in combined for kw in ["开篇", "交代", "场景", "状态", "气氛", "承接"]):
            return "setup"
        return "progress"

    def _build_acceptance_criteria(self, intent: str, beat_type: str) -> List[str]:
        criteria = [
            "本拍必须出现至少一个可见动作或有信息的对白。",
            "本拍必须带来一条新的事实、态度或局势变化。",
        ]
        if beat_type == "confrontation":
            criteria.append("本拍必须写出谁与谁正面碰撞、如何施压、局势如何升级。")
        if beat_type == "reveal":
            criteria.append("本拍必须把新真相、新认知或新规则真正揭示出来，不能只写预感。")
        if beat_type == "payoff":
            criteria.append("本拍必须交代前一冲突带来的结果、代价或态度变化，不能只硬切下个事件。")
        if beat_type == "hook":
            criteria.append("本拍结尾必须留下明确追读牵引，不能平收。")
        if "觉醒" in (intent or "") or "真相" in (intent or ""):
            criteria.append("章纲承诺的核心变化必须真正发生，不能停在临界点前。")
        return criteria[:4]

    def _build_forbidden_drift(self, beat_type: str) -> str:
        mapping = {
            "setup": "不要把篇幅耗在纯光影、气味、材质堆叠上；场景细节必须服务行动或判断。",
            "progress": "不要只写情绪起伏而没有目标推进、阻碍升级或信息变化。",
            "confrontation": "不要只写疼痛、震撼、热流、电流等体感；必须落成对抗动作、压迫关系或局势升级。",
            "reveal": "不要只把答案含糊带过；必须明确写出被看见、被理解或被揭开的内容。",
            "payoff": "不要把结果一笔带过；前面铺的冲突必须有可见反馈、代价或态度变化。",
            "hook": "不要在本拍末尾解释完所有问题；保留新牵引，但不能空喊悬念。",
        }
        return mapping.get(beat_type, "")

    # 节拍聚焦指令：CPMS 节点 beat-focus-instructions（prompt_packages）
    # 通过 PromptRegistry 统一读取，不再在此硬编码
    from infrastructure.ai.prompt_keys import BEAT_FOCUS_INSTRUCTIONS as _BEAT_PROMPT_ID

    def build_beat_prompt(self, beat: Beat, beat_index: int, total_beats: int) -> str:
        """构建单个节拍的生成提示（指令从 CPMS beat-focus-instructions 读取）"""
        from infrastructure.ai.prompt_registry import get_prompt_registry

        registry = get_prompt_registry()

        # 聚焦指令字典
        focus_instructions = registry.get_directives_dict(self._BEAT_PROMPT_ID, "_focus_instructions")
        instruction = focus_instructions.get(beat.focus, "")

        # 感官锚点轮转
        sensory_rotation = registry.get_list_field(self._BEAT_PROMPT_ID, "_sensory_rotation")
        if not sensory_rotation:
            # 安全降级
            sensory_rotation = [
                "本节拍至少一处环境锚点：光影或空间层次。",
                "本节拍至少一处环境锚点：温度、体感或材质。",
                "本节拍至少一处环境锚点：声音或节奏。",
                "本节拍至少一处环境锚点：气味或味觉细节。",
            ]
        anchor_line = sensory_rotation[beat_index % len(sensory_rotation)]

        # 叙事义务
        obligations = registry.get_field(self._BEAT_PROMPT_ID, "_obligations", {})
        if isinstance(obligations, dict):
            obligation = obligations.get(beat.focus, obligations.get("default", "叙事义务：推进情节或深化人物。"))
        else:
            obligation = "叙事义务：推进情节或深化人物。"

        # 扩写维度提示（核心改进：告诉 LLM 怎么凑够字数）
        expansion_block = ""
        if beat.expansion_hints:
            hints_text = "\n".join(f"- {hint}" for hint in beat.expansion_hints)
            expansion_block = f"\n\n【字数扩充方向】（请参考以下方向展开细节）\n{hints_text}"

        # 使用 PromptRegistry 渲染 user 模板
        rendered = registry.render(
            self._BEAT_PROMPT_ID,
            variables={
                "beat_index": beat_index + 1,
                "total_beats": total_beats,
                "target_words": beat.target_words,
                "focus": beat.focus,
                "instruction": instruction,
                "description": beat.description,
                "anchor_line": anchor_line,
                "obligation": obligation,
            },
        )
        prompt = (rendered.user if rendered else "") or ""

        beat_card_parts = [
            f"【节拍类型】{beat.beat_type}",
            f"【建议字数】约 {beat.target_words} 字",
        ]
        if beat.acceptance_criteria:
            beat_card_parts.append(f"【本拍必须兑现】{'；'.join(beat.acceptance_criteria)}")
        if beat.forbidden_drift:
            beat_card_parts.append(f"【禁止漂移】{beat.forbidden_drift}")
        prompt = "\n".join(beat_card_parts) + "\n\n" + prompt

        # 注入扩写维度
        if expansion_block:
            # 在 "密度与可检查要求" 之后插入
            prompt = prompt.replace(
                "\n\n⚠️ 篇幅控制",
                f"{expansion_block}\n\n⚠️ 篇幅控制"
            )

        # 🔗 V2：注入节拍间过渡方式
        if beat_index > 0 and hasattr(beat, 'transition_from_prev') and beat.transition_from_prev:
            transition_block = (
                f"\n\n🔗【本节拍过渡方式】{beat.transition_from_prev}\n"
                f"→ 你的第一句话必须遵循此过渡方式与前节拍衔接"
            )
            prompt = transition_block + prompt

        # 🔗 V2：第一个节拍特殊处理——如果有前章桥段，强调章首衔接
        if beat_index == 0:
            prompt = "\n📌 这是本章第一个节拍——你的开头就是读者翻页后看到的第一段。必须与前章结尾自然衔接，不能像新故事一样重新开始。\n" + prompt

        # 最后一个节拍特殊处理：强调收尾（双重保障——conductor 也会注入更详细的收尾指令）
        if beat_index == total_beats - 1:
            prompt += "\n\n📌 这是本章最后一个节拍！必须：\n" \
                      "1. 给出完整的章节收尾——故事告一段落，读者能感知到「这一章讲完了」\n" \
                      "2. 可以抛出下一章的悬念钩子，但不要强行总结全章\n" \
                      "3. 用有画面感的方式结束——最后一个画面留在读者脑海中\n" \
                      "4. 绝对不能留下悬而未决的对话或行动"

        return prompt
