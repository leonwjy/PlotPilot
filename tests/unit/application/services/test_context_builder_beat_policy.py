"""ContextBuilder 节拍策略测试。"""

from unittest.mock import Mock

from application.engine.services.context_builder import Beat, ContextBuilder


def _builder() -> ContextBuilder:
    mock = Mock()
    return ContextBuilder(
        bible_service=mock,
        storyline_manager=mock,
        relationship_engine=mock,
        vector_store=mock,
        novel_repository=mock,
        chapter_repository=mock,
    )


def test_resolve_max_beats_by_chapter_words():
    builder = _builder()
    assert builder._resolve_max_beats(800) == 2
    assert builder._resolve_max_beats(1200) == 3
    assert builder._resolve_max_beats(2500) == 4
    assert builder._resolve_max_beats(3200) == 5
    assert builder._resolve_max_beats(5000) == 6
    assert builder._resolve_max_beats(9000) == 7


def test_cap_and_merge_keeps_must_keep_core_nodes():
    builder = _builder()
    beats = [
        Beat(description="a", target_words=300, focus="sensory", beat_type="setup", must_keep=True),
        Beat(description="b", target_words=300, focus="dialogue", beat_type="progress", must_keep=True),
        Beat(description="c", target_words=300, focus="action", beat_type="confrontation", must_keep=True),
        Beat(description="d", target_words=300, focus="suspense", beat_type="hook", must_keep=True),
    ]

    out = builder._cap_and_merge_beats(beats, 2500)

    assert len(out) == 4
    assert all(b.must_keep for b in out)
    assert {b.beat_type for b in out} == {"setup", "progress", "confrontation", "hook"}


def test_cap_and_merge_forces_limit_when_core_nodes_exceed_budget():
    builder = _builder()
    beats = [
        Beat(description="a", target_words=300, focus="sensory", beat_type="setup", must_keep=True),
        Beat(description="b", target_words=300, focus="dialogue", beat_type="progress", must_keep=True),
        Beat(description="c", target_words=300, focus="dialogue", beat_type="progress", must_keep=True),
        Beat(description="d", target_words=300, focus="action", beat_type="confrontation", must_keep=True),
        Beat(description="e", target_words=300, focus="suspense", beat_type="hook", must_keep=True),
    ]

    out = builder._cap_and_merge_beats(beats, 2500)

    assert len(out) == 4


def test_infer_beat_type_supports_six_defined_categories():
    builder = _builder()

    assert builder._infer_beat_type("承接前章，交代刑场气氛") == "setup"
    assert builder._infer_beat_type("瑟拉芬诬陷之后，局势继续推进") == "progress"
    assert builder._infer_beat_type("伊格娜缇娅下令鞭刑，众人对峙升级") == "confrontation"
    assert builder._infer_beat_type("第一鞭落下时，埃里希听见世界真相") == "reveal"
    assert builder._infer_beat_type("众人对异变作出反馈，代价真正落地") == "payoff"
    assert builder._infer_beat_type("结尾留下新的悬念钩子") == "hook"


def test_rebalance_scales_with_large_chapter_target():
    builder = _builder()
    beats = [
        Beat(description="a", target_words=300, focus="sensory", beat_type="setup", must_keep=True),
        Beat(description="b", target_words=300, focus="dialogue", beat_type="progress", must_keep=True),
        Beat(description="c", target_words=300, focus="action", beat_type="confrontation", must_keep=True),
        Beat(description="d", target_words=300, focus="dialogue", beat_type="reveal", must_keep=True),
        Beat(description="e", target_words=300, focus="emotion", beat_type="payoff", must_keep=True),
        Beat(description="f", target_words=300, focus="dialogue", beat_type="progress", must_keep=True),
        Beat(description="g", target_words=300, focus="suspense", beat_type="hook", must_keep=True),
    ]

    builder._rebalance_target_words(beats, 10000)

    assert sum(b.target_words for b in beats) == 10000
    by_type = {b.beat_type: b.target_words for b in beats}
    assert by_type["confrontation"] > 1200
    assert by_type["reveal"] > 1200
    assert by_type["hook"] > 700
