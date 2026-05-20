"""GenerationPreferences：from_dict / merge_patch 兼容性。"""
from domain.novel.value_objects.generation_preferences import GenerationPreferences


def test_missing_inline_prose_aggregation_defaults_false():
    gp = GenerationPreferences.from_dict({"phase_display_mode": True})
    assert gp.inline_prose_aggregation_enabled is False
    assert gp.outline_partition_mode == "single"


def test_outline_partition_mode_validation_defaults_single():
    assert GenerationPreferences.from_dict({"outline_partition_mode": "auto"}).outline_partition_mode == "auto"
    assert (
        GenerationPreferences.from_dict({"outline_partition_mode": "beat_sheet"}).outline_partition_mode
        == "beat_sheet"
    )
    assert GenerationPreferences.from_dict({"outline_partition_mode": "bad"}).outline_partition_mode == "single"


def test_explicit_inline_prose_aggregation_true():
    gp = GenerationPreferences.from_dict({"inline_prose_aggregation_enabled": True})
    assert gp.inline_prose_aggregation_enabled is True


def test_merge_patch_roundtrip_key():
    base = GenerationPreferences()
    patched = GenerationPreferences.merge_patch(
        base, {"inline_prose_aggregation_enabled": True, "outline_partition_mode": "auto"}
    )
    assert patched.inline_prose_aggregation_enabled is True
    assert patched.outline_partition_mode == "auto"
    assert "inline_prose_aggregation_enabled" in patched.to_dict()


def test_audit_gate_prefs_default_false_when_missing():
    gp = GenerationPreferences.from_dict({"phase_display_mode": True})
    assert gp.pause_after_each_chapter_audit is False
    assert gp.audit_pause_on_hard_fail is False
    assert gp.audit_pause_on_anti_ai_severe is False


def test_audit_gate_prefs_from_dict_merge_patch():
    gp = GenerationPreferences.from_dict(
        {
            "pause_after_each_chapter_audit": True,
            "audit_pause_on_hard_fail": True,
            "audit_pause_on_anti_ai_severe": True,
        }
    )
    assert gp.pause_after_each_chapter_audit is True
    assert gp.audit_pause_on_hard_fail is True
    assert gp.audit_pause_on_anti_ai_severe is True

    patched = GenerationPreferences.merge_patch(gp, {"pause_after_each_chapter_audit": False})
    assert patched.pause_after_each_chapter_audit is False
    assert patched.audit_pause_on_hard_fail is True
