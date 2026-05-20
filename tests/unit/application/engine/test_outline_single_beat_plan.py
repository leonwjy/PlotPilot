import pytest

from application.engine.dag.plan.outline_beat_planner import build_chapter_execution_plan_async


class _FakeLLM:
    async def stream_generate(self, prompt, config):
        yield (
            '{"atoms":[{"id":"b1","intent":"整章执行任务：写清目标、阻碍、行动、转折、兑现/代价与新期待。","weight":1}]}'
        )


@pytest.mark.asyncio
async def test_single_partition_mode_returns_one_atom_even_for_numbered_outline():
    plan = await build_chapter_execution_plan_async(
        "1. 反派嘲讽主角\n2. 主角被迫应战\n3. 主角破局并留下下一敌人信息",
        target_chapter_words=3000,
        partition_mode="single",
        llm_service=_FakeLLM(),
    )

    assert plan.provenance["mode"] == "single_beat_cpms"
    assert plan.provenance["partition_mode"] == "single"
    assert len(plan.atoms) == 1
    assert plan.atoms[0].id == "b1"
    assert plan.atoms[0].weight == 1.0
    assert "整章执行任务" in plan.atoms[0].intent


@pytest.mark.asyncio
async def test_auto_partition_mode_keeps_structured_outline_behavior():
    plan = await build_chapter_execution_plan_async(
        "1. 反派嘲讽主角\n2. 主角被迫应战\n3. 主角破局并留下下一敌人信息",
        target_chapter_words=3000,
        partition_mode="auto",
        use_llm=False,
    )

    assert plan.provenance["mode"] == "structured_outline"
    assert plan.provenance["partition_mode"] == "auto"
    assert len(plan.atoms) == 3
