"""节拍级生成后审计与局部重写闭环。

这层只负责调度：审计标准与改写标准由 CPMS prompt_packages 维护。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from application.ai.llm_output_sanitize import strip_reasoning_artifacts
from application.ai.structured_json_pipeline import structured_json_generate
from application.audit.services.anti_ai_audit import get_anti_ai_auditor
from domain.ai.services.llm_service import GenerationConfig, LLMService
from domain.ai.value_objects.prompt import Prompt
from infrastructure.ai.prompt_keys import (
    ANTI_AI_PROSE_REWRITE,
    ANTI_AI_SEGMENT_AUDIT,
    CHAPTER_COMPLETION_AUDIT,
    CHAPTER_COMPLETION_PATCH,
    PROSE_INTEGRITY_AUDIT,
)
from infrastructure.ai.prompt_registry import get_prompt_registry

logger = logging.getLogger(__name__)


class BeatCompletionPayload(BaseModel):
    beat_done: bool = True
    missing_items: List[str] = Field(default_factory=list)
    unfinished_reason: str = ""


class BeatBudgetPayload(BaseModel):
    status: str = "ok"
    note: str = ""


class BeatAntiAIPayload(BaseModel):
    rating: str = "clean"
    issues: List[str] = Field(default_factory=list)


class BeatIntegrityPayload(BaseModel):
    ok: bool = True
    issues: List[str] = Field(default_factory=list)


class BeatCombatPayload(BaseModel):
    is_combat: bool = False
    has_opening_action: bool = True
    has_real_collision: bool = True
    has_consequence: bool = True
    has_counter_action: bool = True
    environment_or_psychology_idle: bool = False
    issues: List[str] = Field(default_factory=list)


class SimpleQualityPayload(BaseModel):
    ok: bool = True
    issues: List[str] = Field(default_factory=list)


class BeatAuditPayload(BaseModel):
    passed: bool = True
    needs_rewrite: bool = False
    severity: str = "pass"
    completion: BeatCompletionPayload = Field(default_factory=BeatCompletionPayload)
    word_budget: BeatBudgetPayload = Field(default_factory=BeatBudgetPayload)
    anti_ai: BeatAntiAIPayload = Field(default_factory=BeatAntiAIPayload)
    integrity: BeatIntegrityPayload = Field(default_factory=BeatIntegrityPayload)
    combat: BeatCombatPayload = Field(default_factory=BeatCombatPayload)
    character: SimpleQualityPayload = Field(default_factory=SimpleQualityPayload)
    dialogue: SimpleQualityPayload = Field(default_factory=SimpleQualityPayload)
    pov: SimpleQualityPayload = Field(default_factory=SimpleQualityPayload)
    rewrite_brief: str = ""
    protected_facts: List[str] = Field(default_factory=list)


class ChapterWordBudgetPayload(BaseModel):
    status: str = "ok"
    note: str = ""


class ChapterOutlineCoveragePayload(BaseModel):
    covered: List[str] = Field(default_factory=list)
    missing: List[str] = Field(default_factory=list)
    distorted: List[str] = Field(default_factory=list)


class ChapterBeatCoveragePayload(BaseModel):
    done: List[str] = Field(default_factory=list)
    missing: List[str] = Field(default_factory=list)
    overexpanded: List[str] = Field(default_factory=list)


class ChapterEndingPayload(BaseModel):
    has_stage_result: bool = True
    has_next_hook: bool = True
    issues: List[str] = Field(default_factory=list)


class ChapterIntegrityPayload(BaseModel):
    ok: bool = True
    issues: List[str] = Field(default_factory=list)


class ChapterCompletionPayload(BaseModel):
    completed: bool = True
    severity: str = "pass"
    word_budget: ChapterWordBudgetPayload = Field(default_factory=ChapterWordBudgetPayload)
    outline_coverage: ChapterOutlineCoveragePayload = Field(default_factory=ChapterOutlineCoveragePayload)
    beat_coverage: ChapterBeatCoveragePayload = Field(default_factory=ChapterBeatCoveragePayload)
    ending: ChapterEndingPayload = Field(default_factory=ChapterEndingPayload)
    integrity: ChapterIntegrityPayload = Field(default_factory=ChapterIntegrityPayload)
    character: SimpleQualityPayload = Field(default_factory=SimpleQualityPayload)
    dialogue: SimpleQualityPayload = Field(default_factory=SimpleQualityPayload)
    pov: SimpleQualityPayload = Field(default_factory=SimpleQualityPayload)
    patch_mode: str = "pass"
    patch_brief: str = ""


@dataclass
class BeatAuditRewriteResult:
    content: str
    audit: Optional[BeatAuditPayload] = None
    rewritten: bool = False
    rewrite_attempts: int = 0
    warnings: List[str] = field(default_factory=list)


@dataclass
class ChapterCompletionResult:
    audit: Optional[ChapterCompletionPayload] = None
    content: str = ""
    patched: bool = False
    warnings: List[str] = field(default_factory=list)


class BeatAuditRewriteService:
    """每个节拍完成后的审计与局部重写。"""

    _SEVERE_AI_RATINGS = {"medium", "severe"}
    _SEVERE_LEVELS = {"major", "critical"}

    def __init__(self, llm_service: LLMService):
        self.llm_service = llm_service

    async def audit_and_rewrite_beat(
        self,
        *,
        outline: str,
        beat: Any,
        beat_index: int,
        total_beats: int,
        prior_draft: str,
        content: str,
        max_rewrite_attempts: int = 1,
    ) -> BeatAuditRewriteResult:
        clean_content = strip_reasoning_artifacts(content or "").strip()
        if not clean_content:
            return BeatAuditRewriteResult(
                content="",
                warnings=["节拍正文为空，跳过审计重写"],
            )

        audit = await self.audit_beat(
            outline=outline,
            beat=beat,
            beat_index=beat_index,
            total_beats=total_beats,
            prior_draft=prior_draft,
            content=clean_content,
        )
        if audit is None:
            return BeatAuditRewriteResult(
                content=clean_content,
                warnings=["节拍审计失败，保留原节拍正文"],
            )

        if not self._should_rewrite(audit):
            return BeatAuditRewriteResult(content=clean_content, audit=audit)

        current = clean_content
        attempts = 0
        for attempt in range(1, max_rewrite_attempts + 1):
            rewritten = await self.rewrite_beat(
                outline=outline,
                beat=beat,
                beat_index=beat_index,
                total_beats=total_beats,
                prior_draft=prior_draft,
                content=current,
                audit=audit,
                attempt=attempt,
            )
            if not rewritten or rewritten.strip() == current.strip():
                break
            attempts = attempt
            current = rewritten.strip()
            audit_after = await self.audit_beat(
                outline=outline,
                beat=beat,
                beat_index=beat_index,
                total_beats=total_beats,
                prior_draft=prior_draft,
                content=current,
            )
            if audit_after is not None:
                audit = audit_after
            if not self._should_rewrite(audit):
                break

        return BeatAuditRewriteResult(
            content=current,
            audit=audit,
            rewritten=attempts > 0,
            rewrite_attempts=attempts,
        )

    async def audit_beat(
        self,
        *,
        outline: str,
        beat: Any,
        beat_index: int,
        total_beats: int,
        prior_draft: str,
        content: str,
    ) -> Optional[BeatAuditPayload]:
        variables = self._beat_variables(
            outline=outline,
            beat=beat,
            beat_index=beat_index,
            total_beats=total_beats,
            prior_draft=prior_draft,
            content=content,
        )
        prompt = get_prompt_registry().render_to_prompt(ANTI_AI_SEGMENT_AUDIT, variables)
        if prompt is None:
            logger.warning("CPMS 节点缺失或渲染失败: %s", ANTI_AI_SEGMENT_AUDIT)
            return self._fallback_local_beat_audit(content, beat)

        config = GenerationConfig(max_tokens=1800, temperature=0.2, response_format={"type": "json_object"})
        payload = await structured_json_generate(
            self.llm_service,
            prompt,
            config,
            BeatAuditPayload,
            max_retries=1,
        )
        if payload is None:
            return self._fallback_local_beat_audit(content, beat)
        return payload

    async def rewrite_beat(
        self,
        *,
        outline: str,
        beat: Any,
        beat_index: int,
        total_beats: int,
        prior_draft: str,
        content: str,
        audit: BeatAuditPayload,
        attempt: int,
    ) -> Optional[str]:
        variables = self._beat_variables(
            outline=outline,
            beat=beat,
            beat_index=beat_index,
            total_beats=total_beats,
            prior_draft=prior_draft,
            content=content,
        )
        variables["audit_report"] = json.dumps(audit.model_dump(mode="json"), ensure_ascii=False)
        prompt = get_prompt_registry().render_to_prompt(ANTI_AI_PROSE_REWRITE, variables)
        if prompt is None:
            logger.warning("CPMS 节点缺失或渲染失败: %s", ANTI_AI_PROSE_REWRITE)
            return None

        target_words = int(getattr(beat, "target_words", 0) or 0)
        config = GenerationConfig(
            max_tokens=max(1024, min(4096, int(max(len(content), target_words) * 1.8))),
            temperature=0.35 if attempt <= 1 else 0.25,
        )
        try:
            result = await self.llm_service.generate(prompt, config)
        except Exception as exc:
            logger.warning("节拍局部重写失败: %s", exc)
            return None
        rewritten = strip_reasoning_artifacts(result.content or "").strip()
        return rewritten or None

    async def audit_chapter_completion(
        self,
        *,
        outline: str,
        target_words: int,
        beats: List[Any],
        content: str,
    ) -> ChapterCompletionResult:
        beats_payload = json.dumps(
            [
                {
                    "index": i + 1,
                    "target_words": int(getattr(b, "target_words", 0) or 0),
                    "focus": getattr(b, "focus", "") or "",
                    "description": getattr(b, "description", "") or getattr(b, "scene_goal", "") or "",
                }
                for i, b in enumerate(beats or [])
            ],
            ensure_ascii=False,
        )
        prompt = get_prompt_registry().render_to_prompt(
            CHAPTER_COMPLETION_AUDIT,
            {
                "outline": outline,
                "target_words": str(int(target_words or 0)),
                "beats": beats_payload,
                "content": content,
            },
        )
        if prompt is None:
            logger.warning("CPMS 节点缺失或渲染失败: %s", CHAPTER_COMPLETION_AUDIT)
            return ChapterCompletionResult(warnings=["章节完成度审计节点不可用"])

        config = GenerationConfig(max_tokens=1800, temperature=0.2, response_format={"type": "json_object"})
        payload = await structured_json_generate(
            self.llm_service,
            prompt,
            config,
            ChapterCompletionPayload,
            max_retries=1,
        )
        if payload is None:
            return ChapterCompletionResult(warnings=["章节完成度审计失败"])
        return ChapterCompletionResult(audit=payload, content=content)

    async def audit_and_patch_chapter(
        self,
        *,
        outline: str,
        target_words: int,
        beats: List[Any],
        content: str,
        max_patch_attempts: int = 1,
    ) -> ChapterCompletionResult:
        """章末完成度审计，并按 patch_mode 做有限返修。"""
        current = strip_reasoning_artifacts(content or "").strip()
        first = await self.audit_chapter_completion(
            outline=outline,
            target_words=target_words,
            beats=beats,
            content=current,
        )
        if first.audit is None:
            first.content = current
            return first

        if not self._should_patch_chapter(first.audit):
            first.content = current
            return first

        audit = first.audit
        patched = False
        warnings = list(first.warnings)
        for attempt in range(1, max_patch_attempts + 1):
            new_content = await self.patch_chapter_completion(
                outline=outline,
                target_words=target_words,
                beats=beats,
                content=current,
                audit=audit,
                attempt=attempt,
            )
            if not new_content or new_content.strip() == current.strip():
                warnings.append("章节完成度返修未产生有效变化")
                break
            current = new_content.strip()
            patched = True
            follow_up = await self.audit_chapter_completion(
                outline=outline,
                target_words=target_words,
                beats=beats,
                content=current,
            )
            if follow_up.audit is not None:
                audit = follow_up.audit
            if not self._should_patch_chapter(audit):
                break

        return ChapterCompletionResult(
            audit=audit,
            content=current,
            patched=patched,
            warnings=warnings,
        )

    async def patch_chapter_completion(
        self,
        *,
        outline: str,
        target_words: int,
        beats: List[Any],
        content: str,
        audit: ChapterCompletionPayload,
        attempt: int,
    ) -> Optional[str]:
        beats_payload = json.dumps(
            [
                {
                    "index": i + 1,
                    "target_words": int(getattr(b, "target_words", 0) or 0),
                    "focus": getattr(b, "focus", "") or "",
                    "description": getattr(b, "description", "") or getattr(b, "scene_goal", "") or "",
                }
                for i, b in enumerate(beats or [])
            ],
            ensure_ascii=False,
        )
        prompt = get_prompt_registry().render_to_prompt(
            CHAPTER_COMPLETION_PATCH,
            {
                "outline": outline,
                "target_words": str(int(target_words or 0)),
                "beats": beats_payload,
                "audit_report": json.dumps(audit.model_dump(mode="json"), ensure_ascii=False),
                "content": content,
            },
        )
        if prompt is None:
            logger.warning("CPMS 节点缺失或渲染失败: %s", CHAPTER_COMPLETION_PATCH)
            return None

        max_tokens = max(2048, min(8192, int(max(len(content), target_words) * 1.6)))
        config = GenerationConfig(max_tokens=max_tokens, temperature=0.28 if attempt <= 1 else 0.2)
        try:
            result = await self.llm_service.generate(prompt, config)
        except Exception as exc:
            logger.warning("章节完成度返修失败: %s", exc)
            return None
        patched = strip_reasoning_artifacts(result.content or "").strip()
        return patched or None

    async def audit_integrity(self, *, content: str, scope: str = "chapter") -> Optional[Dict[str, Any]]:
        prompt = get_prompt_registry().render_to_prompt(
            PROSE_INTEGRITY_AUDIT,
            {"content": content, "scope": scope},
        )
        if prompt is None:
            return None
        config = GenerationConfig(max_tokens=1200, temperature=0.1, response_format={"type": "json_object"})
        try:
            result = await self.llm_service.generate(prompt, config)
        except Exception as exc:
            logger.warning("正文完整性审计失败: %s", exc)
            return None
        raw = strip_reasoning_artifacts(result.content or "").strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def _beat_variables(
        self,
        *,
        outline: str,
        beat: Any,
        beat_index: int,
        total_beats: int,
        prior_draft: str,
        content: str,
    ) -> Dict[str, str]:
        return {
            "outline": outline or "",
            "beat_description": getattr(beat, "description", "") or getattr(beat, "scene_goal", "") or "",
            "beat_focus": getattr(beat, "focus", "") or "",
            "beat_index": str(beat_index + 1),
            "total_beats": str(total_beats),
            "target_words": str(int(getattr(beat, "target_words", 0) or 0)),
            "prior_draft": prior_draft[-2400:] if prior_draft else "",
            "content": content or "",
        }

    def _should_rewrite(self, audit: BeatAuditPayload) -> bool:
        if audit.needs_rewrite or not audit.passed:
            return True
        if audit.severity in self._SEVERE_LEVELS:
            return True
        if not audit.completion.beat_done or audit.completion.missing_items:
            return True
        if audit.word_budget.status == "too_long":
            return True
        if audit.anti_ai.rating in self._SEVERE_AI_RATINGS:
            return True
        if not audit.integrity.ok:
            return True
        if audit.combat.is_combat and (
            not audit.combat.has_real_collision
            or not audit.combat.has_consequence
            or audit.combat.environment_or_psychology_idle
        ):
            return True
        if not audit.character.ok or not audit.dialogue.ok or not audit.pov.ok:
            return True
        return False

    def _should_patch_chapter(self, audit: ChapterCompletionPayload) -> bool:
        if not audit.completed:
            return True
        if audit.patch_mode in {"append_closure", "rewrite_segment", "compress_tail"}:
            return True
        if audit.severity in self._SEVERE_LEVELS:
            return True
        if audit.outline_coverage.missing or audit.outline_coverage.distorted:
            return True
        if audit.beat_coverage.missing:
            return True
        if not audit.ending.has_stage_result:
            return True
        if not audit.integrity.ok:
            return True
        if not audit.character.ok or not audit.dialogue.ok or not audit.pov.ok:
            return True
        if audit.patch_mode == "pass" and audit.severity not in self._SEVERE_LEVELS:
            return False
        return False

    def _fallback_local_beat_audit(self, content: str, beat: Any) -> BeatAuditPayload:
        """LLM 审计不可用时的保底：用本地 cliche 扫描与粗略字数判断。"""
        target_words = int(getattr(beat, "target_words", 0) or 0)
        auditor = get_anti_ai_auditor()
        report = auditor.scan_chapter("beat", content)
        too_long = bool(target_words and len(content) > int(target_words * 1.45))
        rating = "severe" if report.metrics.overall_assessment == "严重" else (
            "medium" if report.metrics.overall_assessment == "中等" else (
                "light" if report.metrics.overall_assessment == "轻微" else "clean"
            )
        )
        issues = [
            f"{h.category}:{h.pattern}"
            for h in report.hits[:8]
        ]
        needs = too_long or rating in self._SEVERE_AI_RATINGS or report.metrics.critical_hits >= 2
        return BeatAuditPayload(
            passed=not needs,
            needs_rewrite=needs,
            severity="major" if needs else "pass",
            word_budget=BeatBudgetPayload(
                status="too_long" if too_long else "ok",
                note=f"目标 {target_words}，当前约 {len(content)} 字" if too_long else "",
            ),
            anti_ai=BeatAntiAIPayload(rating=rating, issues=issues),
            rewrite_brief="本地扫描发现 AI 味或字数超限，请压缩空泛表达并补足节拍动作结果。" if needs else "",
        )
