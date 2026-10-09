"""Deterministic unit tests for Phase 3 Recommendation Engine.

Verifies acceptance criteria and rules R01, R02, R06, R11, and R12 strictly from:
- FEEDBACK/Recommended-solution_DAT/Coverage_Recommendation_Engine_Coding_Spec_N2-05B.md §6, §7, §8, §10, §11
- FEEDBACK/Recommended-solution_DAT/Co_so_ly_thuyet_Data_Quality_Coverage_N2-05B.md §6, §7, §12
"""

from __future__ import annotations

import pytest

from core.coverage_config import CoverageConfig, MetadataPolicy, SliceDefinition
from core.recommendations import (
    Recommendation,
    RecommendationEngine,
    SkippedRuleResult,
    get_skipped_rules,
    recommend,
)
from core.schema import ImageRecord, ObjectRecord
from core.slice_engine import SliceEvaluationResult


# ---------------------------------------------------------------------------
# Test Fixture Helpers
# ---------------------------------------------------------------------------

def _slice(
    slice_id: str = "s1",
    name: str = "Slice 1",
    unit: str = "image",
    filters: dict | None = None,
    target_count: int = 50,
    weight: float = 1.0,
    feasibility: str = "confirmed",
    enabled: bool = True,
    target_reason: str = "Sample target reason",
) -> SliceDefinition:
    return SliceDefinition(
        id=slice_id,
        name=name,
        unit=unit,
        filters=filters or {"contains_class": "person"},
        target_count=target_count,
        weight=weight,
        feasibility=feasibility,
        enabled=enabled,
        target_reason=target_reason,
    )


def _eval_result(
    slice_id: str = "s1",
    slice_name: str = "Slice 1",
    unit: str = "image",
    support: int = 10,
    target_count: int = 50,
    weight: float = 1.0,
    matched_keys: list[str] | None = None,
    unresolved_count: int = 0,
    unresolved_keys: list[str] | None = None,
    source_support: int | None = None,
    source_support_status: str = "not_available",
    metadata_availability: dict[str, float] | None = None,
) -> SliceEvaluationResult:
    gap = max(0, target_count - support)
    attainment = min(support / target_count, 1.0) if target_count > 0 else 1.0
    priority = weight * (1.0 - attainment)
    return SliceEvaluationResult(
        slice_id=slice_id,
        slice_name=slice_name,
        unit=unit,
        support=support,
        target_count=target_count,
        weight=weight,
        gap=gap,
        attainment=attainment,
        priority=priority,
        matched_keys=matched_keys or [f"ds1:img_{i}" for i in range(support)],
        unresolved_count=unresolved_count,
        unresolved_keys=unresolved_keys or [f"ds1:unres_{i}" for i in range(unresolved_count)],
        source_support=source_support,
        source_support_status=source_support_status,
        metadata_availability=metadata_availability or {},
    )


def _img(
    img_id: str = "img1",
    dataset_id: str = "ds1",
    timeofday: str | None = "day",
    weather: str | None = "clear",
    has_scene_conflict: bool = False,
    scene_tags: list | None = None,
) -> ImageRecord:
    return ImageRecord(
        dataset_id=dataset_id,
        image_id=img_id,
        image_path=f"/path/{img_id}.jpg",
        width=1920,
        height=1080,
        timeofday=timeofday,
        weather=weather,
        has_scene_conflict=has_scene_conflict,
        scene_tags=scene_tags or [],
    )


# ===========================================================================
# 1. R01 ZERO_SUPPORT & R02 BELOW_TARGET Tests
# ===========================================================================

class TestRuleR01AndR02:
    """Verifies triggering conditions and boundary behaviors for R01 and R02."""

    def test_r01_triggers_when_support_is_zero_and_target_positive(self):
        """R01 ZERO_SUPPORT triggers when support=0 and target>0."""
        s = _slice(slice_id="zero_slice", target_count=30, weight=1.0)
        res = _eval_result(slice_id="zero_slice", support=0, target_count=30, weight=1.0)
        cfg = CoverageConfig(slices=[s])

        recs = recommend({s.id: res}, cfg)
        assert len(recs) == 1
        rec = recs[0]
        assert rec.slice_id == "zero_slice"
        assert "R01" in rec.rule_ids
        assert rec.category == "collection_gap"
        assert rec.severity == "planning"
        assert rec.support == 0
        assert rec.target == 30
        assert rec.gap == 30
        assert rec.attainment == 0.0
        assert rec.priority == 1.0
        assert rec.affected_image_keys == []  # No fake images created for zero support
        assert "support" in rec.remeasure
        assert "gap" in rec.remeasure

    def test_r01_boundary_support_one_does_not_trigger_r01(self):
        """Boundary: support=1 is above zero, does not trigger R01 (triggers R02 instead)."""
        s = _slice(slice_id="one_slice", target_count=30)
        res = _eval_result(slice_id="one_slice", support=1, target_count=30)
        cfg = CoverageConfig(slices=[s])

        recs = recommend({s.id: res}, cfg)
        assert len(recs) == 1
        assert "R01" not in recs[0].rule_ids
        assert "R02" in recs[0].rule_ids

    def test_r02_triggers_when_support_above_zero_and_below_target(self):
        """R02 BELOW_TARGET triggers when 0 < support < target."""
        s = _slice(slice_id="below_slice", target_count=50, weight=2.0)
        res = _eval_result(slice_id="below_slice", support=20, target_count=50, weight=2.0)
        cfg = CoverageConfig(slices=[s])

        recs = recommend({s.id: res}, cfg)
        assert len(recs) == 1
        rec = recs[0]
        assert rec.slice_id == "below_slice"
        assert "R02" in rec.rule_ids
        assert rec.category == "collection_gap"
        assert rec.severity == "planning"
        assert rec.support == 20
        assert rec.target == 50
        assert rec.gap == 30
        assert pytest.approx(rec.attainment, 1e-4) == 0.4
        assert pytest.approx(rec.priority, 1e-4) == 1.2
        assert "attainment" in rec.remeasure
        assert "coverage" in rec.remeasure

    def test_r02_boundary_support_equals_target_does_not_trigger_r02(self):
        """Boundary: support == target reaches target, does not trigger R02."""
        s = _slice(slice_id="target_met_slice", target_count=50)
        res = _eval_result(slice_id="target_met_slice", support=50, target_count=50)
        cfg = CoverageConfig(slices=[s])

        recs = recommend({s.id: res}, cfg)
        # Should not have R02
        assert not any("R02" in r.rule_ids for r in recs)

    def test_r02_boundary_support_exceeds_target_does_not_trigger_r02(self):
        """Boundary: support > target does not trigger R02."""
        s = _slice(slice_id="over_target_slice", target_count=50)
        res = _eval_result(slice_id="over_target_slice", support=60, target_count=50)
        cfg = CoverageConfig(slices=[s])

        recs = recommend({s.id: res}, cfg)
        assert not any("R02" in r.rule_ids for r in recs)


# ===========================================================================
# 2. R06 METADATA_INSUFFICIENT Tests
# ===========================================================================

class TestRuleR06MetadataInsufficient:
    """Verifies R06 triggering against policy thresholds, handling of unresolved metadata."""

    def test_r06_triggers_when_metadata_availability_exceeds_policy(self):
        """R06 triggers when field unavailable rate exceeds metadata policy warning rate."""
        # Slice requires weather
        s = _slice(
            slice_id="rain_slice",
            filters={"contains_class": "person", "weather": "rain"},
            target_count=50,
        )
        # availability is 0.90 => unavail_rate = 0.10 > missing_warning_rate (0.05)
        res = _eval_result(
            slice_id="rain_slice",
            support=10,
            target_count=50,
            unresolved_count=5,
            unresolved_keys=["ds1:img_unres_1", "ds1:img_unres_2"],
            metadata_availability={"weather": 0.90},
        )
        cfg = CoverageConfig(
            metadata_policy=MetadataPolicy(missing_warning_rate=0.05, unknown_warning_rate=0.10),
            slices=[s],
        )

        recs = recommend({s.id: res}, cfg)
        assert len(recs) == 1
        rec = recs[0]
        assert "R06" in rec.rule_ids
        assert rec.severity == "review_required"
        assert rec.category == "metadata_quality"
        assert "availability" in rec.remeasure
        assert "support" in rec.remeasure
        # Affected keys contain unresolved image keys for inspection
        assert "ds1:img_unres_1" in rec.affected_image_keys
        assert "ds1:img_unres_2" in rec.affected_image_keys
        # Limitations state that missing metadata is not proof of genuine lack of data
        assert any("không được xem là chứng minh thiếu dữ liệu thật" in lim for lim in rec.limitations)

    def test_r06_boundary_availability_within_threshold_does_not_trigger(self):
        """Boundary: unavailable rate at or below policy threshold does not trigger R06."""
        s = _slice(
            slice_id="rain_slice",
            filters={"contains_class": "person", "weather": "rain"},
            target_count=50,
        )
        # availability is 0.98 => unavail_rate = 0.02 <= missing_warning_rate (0.05)
        res = _eval_result(
            slice_id="rain_slice",
            support=10,
            target_count=50,
            unresolved_count=0,
            metadata_availability={"weather": 0.98},
        )
        cfg = CoverageConfig(
            metadata_policy=MetadataPolicy(missing_warning_rate=0.05, unknown_warning_rate=0.10),
            slices=[s],
        )

        recs = recommend({s.id: res}, cfg)
        assert not any("R06" in r.rule_ids for r in recs)

    def test_r06_does_not_trigger_for_slice_without_metadata_filters(self):
        """Slice requiring only class is not triggered by R06 even if metadata in dataset has issues."""
        s = _slice(
            slice_id="class_only_slice",
            filters={"contains_class": "person"},  # No weather or timeofday filter
            target_count=50,
        )
        res = _eval_result(
            slice_id="class_only_slice",
            support=10,
            target_count=50,
            metadata_availability={},  # No metadata evaluated for this slice
        )
        cfg = CoverageConfig(slices=[s])

        recs = recommend({s.id: res}, cfg)
        assert not any("R06" in r.rule_ids for r in recs)

    def test_r06_with_detailed_images_detects_missing_and_conflicts(self):
        """R06 accurately detects missing and conflicting metadata when image records are supplied."""
        s = _slice(
            slice_id="night_slice",
            filters={"timeofday": "night"},
            target_count=20,
        )
        res = _eval_result(slice_id="night_slice", support=5, target_count=20)
        # 10 images: 2 missing timeofday => 20% > 5% threshold
        images = [
            _img(f"img_{i}", timeofday="night") for i in range(8)
        ] + [
            _img("img_bad_1", timeofday=None),
            _img("img_bad_2", timeofday=""),
        ]
        cfg = CoverageConfig(
            metadata_policy=MetadataPolicy(missing_warning_rate=0.05),
            slices=[s],
        )

        recs = recommend({s.id: res}, cfg, images=images)
        assert any("R06" in r.rule_ids for r in recs)


# ===========================================================================
# 3. R11 CRITICAL_RARE_GAP Tests
# ===========================================================================

class TestRuleR11CriticalRareGap:
    """Verifies R11 thresholding, merging with R01/R02, and severity/priority distinction."""

    def test_r11_triggers_when_support_below_target_and_weight_meets_critical(self):
        """R11 triggers when support < target and weight >= critical_weight."""
        s = _slice(
            slice_id="rare_slice",
            name="Rare High Weight Slice",
            target_count=50,
            weight=3.0,
        )
        # support = 10 < 50, weight = 3.0 >= critical_weight (3.0)
        res = _eval_result(
            slice_id="rare_slice",
            slice_name="Rare High Weight Slice",
            support=10,
            target_count=50,
            weight=3.0,
        )
        cfg = CoverageConfig(slices=[s])

        recs = recommend({s.id: res}, cfg, critical_weight=3.0)
        assert len(recs) == 1
        rec = recs[0]
        # Combines R02 and R11
        assert "R02" in rec.rule_ids
        assert "R11" in rec.rule_ids
        assert rec.severity == "planning"
        assert pytest.approx(rec.priority, 1e-4) == 2.4
        assert "weighted_coverage" in rec.remeasure

    def test_r11_combined_with_r01_zero_support(self):
        """R11 combined with R01 when support is zero and weight is critical."""
        s = _slice(
            slice_id="critical_zero_slice",
            target_count=20,
            weight=4.0,
        )
        res = _eval_result(
            slice_id="critical_zero_slice",
            support=0,
            target_count=20,
            weight=4.0,
        )
        cfg = CoverageConfig(slices=[s])

        recs = recommend({s.id: res}, cfg, critical_weight=3.0)
        assert len(recs) == 1
        rec = recs[0]
        assert "R01" in rec.rule_ids
        assert "R11" in rec.rule_ids
        assert rec.priority == 4.0

    def test_r11_boundary_weight_below_critical_does_not_trigger_r11(self):
        """Boundary: weight < critical_weight triggers only R02, not R11."""
        s = _slice(slice_id="normal_slice", target_count=50, weight=2.5)
        res = _eval_result(slice_id="normal_slice", support=10, target_count=50, weight=2.5)
        cfg = CoverageConfig(slices=[s])

        recs = recommend({s.id: res}, cfg, critical_weight=3.0)
        assert len(recs) == 1
        assert "R02" in recs[0].rule_ids
        assert "R11" not in recs[0].rule_ids

    def test_r11_does_not_trigger_when_target_is_met(self):
        """Even with high weight, R11 does not trigger if support meets target."""
        s = _slice(slice_id="met_critical_slice", target_count=50, weight=5.0)
        res = _eval_result(slice_id="met_critical_slice", support=50, target_count=50, weight=5.0)
        cfg = CoverageConfig(slices=[s])

        recs = recommend({s.id: res}, cfg, critical_weight=3.0)
        assert not any("R11" in r.rule_ids for r in recs)


# ===========================================================================
# 4. R12 TARGETS_MET Tests & Mandatory Blockers
# ===========================================================================

class TestRuleR12TargetsMetAndBlockers:
    """Verifies R12 handoff recommendations, blocker prevention, and unresolved metadata."""

    def test_r12_triggers_when_required_slice_meets_target_without_blockers(self):
        """R12 triggers for required slice meeting target with zero unresolved metadata."""
        s = _slice(
            slice_id="met_slice",
            target_count=30,
            feasibility="confirmed",
            enabled=True,
        )
        res = _eval_result(
            slice_id="met_slice",
            support=30,
            target_count=30,
            unresolved_count=0,
        )
        cfg = CoverageConfig(slices=[s])

        recs = recommend({s.id: res}, cfg)
        assert len(recs) == 1
        rec = recs[0]
        assert "R12" in rec.rule_ids
        assert rec.category == "review_handoff"
        assert rec.severity == "info"
        assert rec.evidence_status == "audited_quality"
        assert "audited_quality" in rec.remeasure

    def test_r12_withheld_when_slice_has_unresolved_metadata(self):
        """Criterion 16: R12 is withheld if the slice has unresolved metadata count > 0."""
        s = _slice(
            slice_id="met_but_unresolved_slice",
            target_count=30,
            feasibility="confirmed",
            enabled=True,
        )
        # support = 30 >= target, but unresolved_count = 2
        res = _eval_result(
            slice_id="met_but_unresolved_slice",
            support=30,
            target_count=30,
            unresolved_count=2,
        )
        cfg = CoverageConfig(slices=[s])

        recs = recommend({s.id: res}, cfg)
        assert not any("R12" in r.rule_ids for r in recs)

    def test_r12_withheld_when_mandatory_blocker_remains(self):
        """Specification §7: Never emit handoff recommendation while mandatory blockers remain."""
        s = _slice(slice_id="ready_slice", target_count=10, feasibility="confirmed")
        res = _eval_result(slice_id="ready_slice", support=10, target_count=10, unresolved_count=0)
        cfg = CoverageConfig(slices=[s])

        # Mandatory blocker passed (e.g., schema validation error or critical blocker)
        recs = recommend(
            {s.id: res},
            cfg,
            mandatory_blockers=["SCHEMA_ERROR: invalid tags"],
        )
        # R12 must be withheld!
        assert not any("R12" in r.rule_ids for r in recs)

    def test_r12_withheld_when_another_required_slice_has_unresolved_metadata(self):
        """If any required slice has unresolved metadata, handoff signoff is withheld."""
        s1 = _slice(slice_id="s1", target_count=10, feasibility="confirmed")
        s2 = _slice(slice_id="s2", target_count=10, feasibility="confirmed")

        res1 = _eval_result(slice_id="s1", support=10, target_count=10, unresolved_count=0)
        res2 = _eval_result(slice_id="s2", support=10, target_count=10, unresolved_count=3)  # blocker!

        cfg = CoverageConfig(slices=[s1, s2])
        recs = recommend({s1.id: res1, s2.id: res2}, cfg)

        # Neither slice should have R12 because unresolved metadata blocker exists
        assert not any("R12" in r.rule_ids for r in recs)

    def test_r12_does_not_apply_to_infeasible_or_unverified_slices(self):
        """R12 applies only to required (confirmed) slices, not unverified or infeasible slices."""
        s_unverified = _slice(slice_id="unv", target_count=10, feasibility="unverified")
        res = _eval_result(slice_id="unv", support=10, target_count=10, unresolved_count=0)
        cfg = CoverageConfig(slices=[s_unverified])

        recs = recommend({s_unverified.id: res}, cfg)
        assert not any("R12" in r.rule_ids for r in recs)


# ===========================================================================
# 5. Deduplication and Merging Tests
# ===========================================================================

class TestDeduplicationAndMerging:
    """Verifies that multiple rules for the same slice merge into exactly one recommendation."""

    def test_deduplication_r02_and_r11_merged(self):
        """Spec §8 example: R02 and R11 merge into 1 recommendation with both rule_ids preserved."""
        s = _slice(slice_id="person_night_rain", target_count=50, weight=3.0)
        res = _eval_result(
            slice_id="person_night_rain",
            slice_name="Người đi bộ ban đêm trời mưa",
            support=10,
            target_count=50,
            weight=3.0,
        )
        cfg = CoverageConfig(slices=[s])

        recs = recommend({s.id: res}, cfg, critical_weight=3.0)
        assert len(recs) == 1
        rec = recs[0]
        assert rec.slice_id == "person_night_rain"
        assert rec.rule_ids == ["R02", "R11"]
        assert rec.category == "collection_gap"
        assert rec.severity == "planning"
        assert rec.support == 10
        assert rec.target == 50
        assert rec.gap == 40
        assert pytest.approx(rec.attainment, 1e-4) == 0.2
        assert pytest.approx(rec.priority, 1e-4) == 2.4

    def test_deduplication_r02_r06_r11_merged_with_severity_escalation(self):
        """When R02 (planning), R11 (planning), and R06 (review_required) trigger, merged severity is review_required."""
        s = _slice(
            slice_id="multi_trigger_slice",
            filters={"timeofday": "night"},
            target_count=50,
            weight=3.0,
        )
        # support = 10, target = 50, weight = 3.0 -> triggers R02 and R11
        # metadata_availability = 0.80 -> triggers R06
        res = _eval_result(
            slice_id="multi_trigger_slice",
            support=10,
            target_count=50,
            weight=3.0,
            unresolved_count=5,
            metadata_availability={"timeofday": 0.80},
        )
        cfg = CoverageConfig(
            metadata_policy=MetadataPolicy(missing_warning_rate=0.05),
            slices=[s],
        )

        recs = recommend({s.id: res}, cfg, critical_weight=3.0)
        assert len(recs) == 1
        rec = recs[0]
        assert sorted(rec.rule_ids) == ["R02", "R06", "R11"]
        # Review required > planning
        assert rec.severity == "review_required"
        assert rec.category == "metadata_quality"

    def test_one_recommendation_per_slice_guarantee(self):
        """Guarantees strictly 1 recommendation per slice across a diverse configuration."""
        slices = [
            _slice(f"slice_{i}", target_count=50, weight=float(i + 1))
            for i in range(5)
        ]
        results = {
            s.id: _eval_result(s.id, support=i * 10, target_count=50, weight=s.weight)
            for i, s in enumerate(slices)
        }
        cfg = CoverageConfig(slices=slices)

        recs = recommend(results, cfg)
        slice_ids_in_recs = [r.slice_id for r in recs]
        assert len(slice_ids_in_recs) == len(set(slice_ids_in_recs))


# ===========================================================================
# 6. Missing Inputs and Unavailable Evidence Tests
# ===========================================================================

class TestMissingInputsAndUnavailableEvidence:
    """Verifies that missing inputs return explicit skipped results and never fabricate evidence."""

    def test_get_skipped_rules_returns_explicit_reasons(self):
        """Skipped rules R03, R04, R07-R10 return explicit not_available results with reasons."""
        s = _slice("s1")
        res = _eval_result("s1", source_support_status="not_available")
        cfg = CoverageConfig(slices=[s])

        skipped = get_skipped_rules({s.id: res}, cfg, collection_results=None)
        skipped_ids = {sk.rule_id for sk in skipped}

        assert "R03" in skipped_ids
        assert "R04" in skipped_ids
        assert "R07" in skipped_ids
        assert "R08" in skipped_ids
        assert "R09" in skipped_ids
        assert "R10" in skipped_ids

        for sk in skipped:
            assert sk.status == "not_available"
            assert len(sk.reason) > 0

    def test_never_fabricate_source_diversity_recommendation(self):
        """When source data is unavailable, never emit unsupported source diversity recommendation."""
        s = _slice("s1", target_count=10)
        res = _eval_result("s1", support=10, target_count=10, source_support_status="not_available")
        cfg = CoverageConfig(slices=[s])

        recs = recommend({s.id: res}, cfg)
        assert not any("R03" in r.rule_ids for r in recs)

    def test_include_skipped_in_recommend_output(self):
        """recommend(..., include_skipped=True) includes skipped rules marked clearly as not_available."""
        s = _slice("s1")
        res = _eval_result("s1")
        cfg = CoverageConfig(slices=[s])

        recs = recommend({s.id: res}, cfg, include_skipped=True)
        skipped_recs = [r for r in recs if r.status == "not_available"]
        assert len(skipped_recs) > 0
        assert any("R03" in r.rule_ids for r in skipped_recs)
        assert all(r.skip_reason is not None for r in skipped_recs)


# ===========================================================================
# 7. Determinism and Output Contract Tests
# ===========================================================================

class TestDeterminismAndOutputContract:
    """Verifies output stability, specification §8 contract compliance, and triage ordering."""

    def test_deterministic_identical_outputs_for_identical_inputs(self):
        """Identical inputs produce identical recommendation order and attributes."""
        slices = [
            _slice("s_b", target_count=50, weight=2.0),
            _slice("s_a", target_count=50, weight=3.0),
            _slice("s_c", target_count=50, weight=1.0),
        ]
        results = {
            "s_b": _eval_result("s_b", support=10, target_count=50, weight=2.0),
            "s_a": _eval_result("s_a", support=10, target_count=50, weight=3.0),
            "s_c": _eval_result("s_c", support=10, target_count=50, weight=1.0),
        }
        cfg = CoverageConfig(slices=slices)

        run1 = [r.to_dict() for r in recommend(results, cfg)]
        run2 = [r.to_dict() for r in recommend(results, cfg)]

        assert run1 == run2

    def test_specification_section_8_schema_conformance(self):
        """Output dictionary strictly matches all required fields of Specification §8."""
        s = _slice(
            "person_night_rain",
            name="Người đi bộ ban đêm trời mưa",
            target_count=50,
            weight=3.0,
            target_reason="Lead approved sample",
        )
        res = _eval_result(
            "person_night_rain",
            slice_name="Người đi bộ ban đêm trời mưa",
            support=10,
            target_count=50,
            weight=3.0,
        )
        cfg = CoverageConfig(config_version="1", slices=[s])

        recs = recommend(
            {s.id: res},
            cfg,
            dataset_id="datasetA",
            dataset_version="export_2026_10_08",
        )
        assert len(recs) == 1
        d = recs[0].to_dict()

        expected_fields = [
            "recommendation_id",
            "slice_id",
            "rule_ids",
            "category",
            "severity",
            "evidence_status",
            "support",
            "target",
            "gap",
            "attainment",
            "priority",
            "unit",
            "title",
            "actions",
            "remeasure",
            "limitations",
            "affected_image_keys",
            "config_version",
            "dataset_version",
        ]
        for f in expected_fields:
            assert f in d, f"Missing required specification §8 field: {f}"

        assert d["recommendation_id"] == "datasetA_person_night_rain_v1"
        assert d["config_version"] == "1"
        assert d["dataset_version"] == "export_2026_10_08"

    def test_severity_priority_distinction_and_sorting(self):
        """Severity groups strictly take precedence over numerical priority in triage ordering.

        blocker > review_required > planning > info
        Within the same severity group, highest numerical priority comes first.
        """
        # Slice 1: planning severity, high priority (priority = 3.0 * (1 - 0) = 3.0)
        s1 = _slice("s1_planning_high_priority", target_count=50, weight=3.0)
        res1 = _eval_result("s1_planning_high_priority", support=0, target_count=50, weight=3.0)

        # Slice 2: review_required severity (R06), lower priority (priority = 1.0 * (1 - 0.5) = 0.5)
        s2 = _slice(
            "s2_review_required_low_priority",
            filters={"timeofday": "night"},
            target_count=50,
            weight=1.0,
        )
        res2 = _eval_result(
            "s2_review_required_low_priority",
            support=25,
            target_count=50,
            weight=1.0,
            unresolved_count=5,
            metadata_availability={"timeofday": 0.80},
        )

        cfg = CoverageConfig(
            metadata_policy=MetadataPolicy(missing_warning_rate=0.05),
            slices=[s1, s2],
        )

        recs = recommend({s1.id: res1, s2.id: res2}, cfg)
        assert len(recs) == 2

        # s2 (review_required) must appear before s1 (planning), even though s1 has higher numerical priority!
        assert recs[0].slice_id == "s2_review_required_low_priority"
        assert recs[0].severity == "review_required"
        assert recs[1].slice_id == "s1_planning_high_priority"
        assert recs[1].severity == "planning"

    def test_flexible_recommend_signature_support(self):
        """recommend() function accepts both (slice_results, config) and (slice_results, collection_results, config)."""
        s = _slice("s1", target_count=10)
        res = _eval_result("s1", support=5, target_count=10)
        cfg = CoverageConfig(slices=[s])

        # Two-arg call
        r1 = recommend({s.id: res}, cfg)
        # Three-arg call with collection_results=None
        r2 = recommend({s.id: res}, None, cfg)
        # Keyword-arg call
        r3 = recommend(slice_results={s.id: res}, config=cfg)

        assert len(r1) == len(r2) == len(r3) == 1
        assert r1[0].slice_id == r2[0].slice_id == r3[0].slice_id
