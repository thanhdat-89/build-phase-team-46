# N2-05B Baseline Audit Report: Step 01

- **Audit Date**: 2026-10-09
- **Repository**: `thanhdat-89/build-phase-team-46`
- **Current Branch**: `main`
- **Current Commit**: `ede65aa` (Create metric_sugg.md)
- **Source Specifications**:
  1. `FEEDBACK/Recommended-solution_DAT/Co_so_ly_thuyet_Data_Quality_Coverage_N2-05B.md` (v1.0)
  2. `FEEDBACK/Recommended-solution_DAT/Coverage_Recommendation_Engine_Coding_Spec_N2-05B.md` (v1.0)

---

## 1. Repository Inspection & Baseline Environment

### 1.1 Git Working-Tree Status
- Branch: `main` (up to date with `origin/main`)
- Working tree: Clean application source code; uncommitted changes are limited to local Python bytecode cache files (`*.pyc`).

### 1.2 Existing Project Structure
```text
build-phase-team-46/
├── .gitignore
├── app.py                      # Main Streamlit UI entry point
├── daily_report.md
├── Dockerfile
├── requirements.txt            # streamlit, pandas, plotly, defusedxml, pytest
├── core/
│   ├── __init__.py
│   ├── schema.py               # ImageRecord, ObjectRecord
│   ├── validation.py           # BBox geometric validation, 4-state metadata, scene tag conflict
│   ├── statistics.py           # dp01_inventory, dp02_class_instance_share, dp03_class_image_prevalence, class_distribution, timeofday/weather_distribution
│   ├── metadata_merge.py       # EMPTY (0 bytes)
│   └── targets.py              # EMPTY (0 bytes)
├── parsers/
│   ├── cvat_images.py          # CVAT 1.1 XML / ZIP parser using defusedxml
│   └── metadata_csv.py         # EMPTY (0 bytes)
├── ui/
│   ├── upload.py               # Streamlit file upload & ZIP extraction helper
│   ├── overview.py             # Streamlit overview dashboard tab
│   ├── analysis.py             # EMPTY (0 bytes)
│   └── reports.py              # EMPTY (0 bytes)
├── tests/
│   ├── test_parser.py          # 20 tests for CVAT parser
│   ├── test_validation.py      # 27 tests for geometry, metadata taxonomy, scene tags
│   ├── test_statistics.py      # 39 tests for legacy & base statistics functions
│   └── test_profiling.py       # 18 tests for DP01, DP02, DP03
├── Docs/
│   ├── Giai_phap_ky_thuat_N2-05B_CVAT_Dashboard.md
│   ├── Ke_hoach_N2-05B_CVAT_Dashboard.pdf
│   └── METRIC_CATALOG.md
└── FEEDBACK/
    └── Recommended-solution_DAT/
        ├── Co_so_ly_thuyet_Data_Quality_Coverage_N2-05B.md
        └── Coverage_Recommendation_Engine_Coding_Spec_N2-05B.md
```

### 1.3 Dependencies and Entry Points
- **Runtime dependencies**: Python 3.12+, `streamlit`, `pandas`, `plotly`, `defusedxml`, `pytest`.
- **Application entry point**: `app.py` (`streamlit run app.py`).
- **Test execution command**:
  - `pytest` alone fails on the system shell because pytest is not installed in the global Windows environment path.
  - `uv run --with-requirements requirements.txt python -m pytest` executes properly and passes **104/104 tests in 0.94s**.

---

## 2. Baseline Test Execution Results

| Command | Status | Output Summary |
|---|---|---|
| `pytest` | **FAILED** | Shell error: `pytest : The term 'pytest' is not recognized` |
| `uv run pytest` | **FAILED** | Collection error: `ModuleNotFoundError: No module named 'parsers'` (PYTHONPATH not set to root) |
| `uv run --with-requirements requirements.txt python -m pytest` | **PASSED** | **104 passed in 0.94s** (`test_parser.py`: 20, `test_profiling.py`: 18, `test_statistics.py`: 39, `test_validation.py`: 27) |

All 104 existing unit tests pass under the project's Python runtime when executed with module discovery (`python -m pytest`).

---

## 3. Requirement-by-Requirement Mapping to Specifications

Classifications:
- **PASS**: Implemented and verified against specifications.
- **PARTIAL**: Partially implemented or missing essential specification behavior.
- **FAIL**: Contradicts the specification or is demonstrably incorrect.
- **NOT_TESTED**: Unimplemented or insufficient implementation to verify.

---

### Group 1: Data Model, Identifiers, and Schema (Specs Sec 3.1, 3.2; Spec 2 Sec 2)

#### REQ-S01: Stable `image_key` Generation (`dataset_id:image_id`)
- **Classification**: **PASS**
- **Location**: `core/schema.py:ImageRecord.image_key`
- **Observed Behavior**: Property returns `f"{self.dataset_id}:{self.image_id}"`.
- **Expected Behavior**: Stable composite key combining dataset ID and image ID.

#### REQ-S02: Stable `object_key` Generation and Image-to-Object Relationships
- **Classification**: **FAIL**
- **Location**: `core/schema.py:ObjectRecord`, `parsers/cvat_images.py:_parse_box`
- **Observed Behavior**: `ObjectRecord` does not contain `dataset_id`, has no `object_key` property or field, and only references local `image_id`. It cannot form a stable cross-dataset identifier `dataset_id:object_id`.
- **Expected Behavior**: Stable `object_key` generation using `dataset_id + object_id` (or deterministic parser ID). `ObjectRecord` must reliably link to its parent image across datasets.
- **Corrective Action**: Add `dataset_id` (and/or `object_key` property and `image_key`) to `ObjectRecord`. Ensure parser passes `dataset_id` when constructing `ObjectRecord`.
- **Regression Test Needed**: Yes (two datasets sharing identical `image_id` and `object_id` must maintain distinct identities and correct relationships).

#### REQ-S03: Preservation of Unannotated Images in Inventory
- **Classification**: **PASS**
- **Location**: `parsers/cvat_images.py:parse_cvat_zip`, `core/statistics.py:dp01_inventory`
- **Observed Behavior**: `<image>` elements without `<box>` children are parsed into `images` list. `dp01_inventory` counts all images in `images` as `N`. Verified by `test_profiling.py:test_02_images_without_annotations`.

#### REQ-S04: 4-State Metadata Classification (`known`, `unknown`, `missing`, `invalid`)
- **Classification**: **PARTIAL**
- **Location**: `core/validation.py:validate_metadata_value`, `core/schema.py:ImageRecord`
- **Observed Behavior**: `validate_metadata_value` correctly categorizes values into 4 mutually exclusive states. However, `ImageRecord` only stores raw strings or `None` in `timeofday` and `weather`, without attaching validation states or structured metadata status.
- **Expected Behavior**: Data contract requires `metadata_status` distinct per field (`known`, `unknown`, `missing`, `invalid`, `conflict`).
- **Corrective Action**: Provide structured metadata validation storage or accessor methods on `ImageRecord` or metadata evaluation helpers.
- **Regression Test Needed**: Yes.

#### REQ-S05: Scene-Tag Conflict Representation and Original Value Preservation
- **Classification**: **PASS**
- **Location**: `core/validation.py:validate_scene_tags`, `parsers/cvat_images.py:340-354`
- **Observed Behavior**: Conflicting `scene_info` tags are detected; neither is silently selected (conflicting fields set to `None`), `has_scene_conflict=True` is set, and raw tags are preserved in `scene_tags`. Verified by `test_validation.py:test_19_conflicting_tags_detected`.

---

### Group 2: Data Quality Metrics (DQ01 - DQ09)

#### REQ-DQ01: Schema Validity Rate
- **Classification**: **NOT_TESTED**
- **Location**: `core/statistics.py`
- **Observed Behavior**: Metric function not implemented.
- **Expected Behavior**: Records passing all applicable rules / records checked; calculated separately for images, objects, tags.
- **Corrective Action**: Implement `dq01_schema_validity_rate` in Phase B or C according to spec contract.
- **Regression Test Needed**: Yes.

#### REQ-DQ02: Metadata Missing Rate(f)
- **Classification**: **FAIL**
- **Location**: `core/statistics.py:timeofday_distribution`, `weather_distribution`
- **Observed Behavior**: Only raw count of `missing` is returned in a dict. No metric function computing `missing / N` with JSON contract, nor N/A handling for $N=0$.
- **Expected Behavior**: $DQ02(f) = \text{missing}(f) / N$. Return `null` / `not_available` with reason if $N=0$.
- **Corrective Action**: Implement `dq02_metadata_missing_rate(images, field_name)` returning structured metric dict.
- **Regression Test Needed**: Yes.

#### REQ-DQ03: Unknown Metadata Rate(f)
- **Classification**: **FAIL**
- **Location**: `core/statistics.py`
- **Observed Behavior**: Metric function not implemented.
- **Expected Behavior**: $DQ03(f) = \text{unknown}(f) / N$. Must be distinct from missing and invalid. Return `null` / `not_available` if $N=0$.
- **Corrective Action**: Implement `dq03_unknown_metadata_rate(images, field_name)`.
- **Regression Test Needed**: Yes.

#### REQ-DQ04: Invalid Metadata Rate(f)
- **Classification**: **FAIL**
- **Location**: `core/statistics.py`
- **Observed Behavior**: `timeofday_distribution` and `weather_distribution` blindly count unrecognized values as arbitrary dict keys, rather than computing invalid metadata rate.
- **Expected Behavior**: $DQ04(f) = \text{invalid}(f) / N$. Original invalid values preserved for audit.
- **Corrective Action**: Implement `dq04_invalid_metadata_rate(images, field_name)`.
- **Regression Test Needed**: Yes.

#### REQ-DQ05: Known Metadata Rate(f)
- **Classification**: **FAIL**
- **Location**: `core/statistics.py`
- **Observed Behavior**: Metric function not implemented. The 4 states are not guaranteed to sum to 100% in reporting.
- **Expected Behavior**: $DQ05(f) = \text{known}(f) / N$. DQ02 + DQ03 + DQ04 + DQ05 = 100% when $N > 0$.
- **Corrective Action**: Implement `dq05_known_metadata_rate(images, field_name)`.
- **Regression Test Needed**: Yes.

#### REQ-DQ06: Invalid Bounding Box Rate
- **Classification**: **PARTIAL**
- **Location**: `core/validation.py:validate_bbox`, `parsers/cvat_images.py`
- **Observed Behavior**: Geometric validation correctly checks finite numbers, positive dimensions, and image boundaries. Boxes violating multiple rules are correctly appended once to `invalid_objects`. However, no standalone metric function `dq06_invalid_bbox_rate(objects, invalid_objects)` exists to compute $\text{invalid} / M$, and no handling for $M=0 \implies N/A$ is exposed as a metric.
- **Expected Behavior**: $DQ06 = \text{invalid\_boxes} / M$. One box failing multiple rules counts as 1. If $M=0$, return `null` / `not_available`.
- **Corrective Action**: Add `dq06_invalid_bbox_rate(total_objects, invalid_objects)`.
- **Regression Test Needed**: Yes.

#### REQ-DQ07 & REQ-DQ08: Duplicate Record Rate & Audited Error Rate
- **Classification**: **NOT_TESTED**
- **Location**: `core/statistics.py`
- **Observed Behavior**: Not implemented. (Requires duplicate groups / reviewer log).
- **Expected Behavior**: Report N/A when inputs are unavailable.
- **Corrective Action**: Defer or provide explicit N/A contract when auxiliary tables are absent.
- **Regression Test Needed**: No (Phase C / optional).

#### REQ-DQ09: Scene Tag Conflict Rate
- **Classification**: **PARTIAL**
- **Location**: `core/validation.py`, `core/schema.py:ImageRecord.has_scene_conflict`
- **Observed Behavior**: Conflicts are detected during parsing, but no metric function computes $\text{conflicting\_images} / N$.
- **Expected Behavior**: $DQ09 = \text{conflicting\_images} / N$. If $N=0$, return `not_available`.
- **Corrective Action**: Implement `dq09_scene_tag_conflict_rate(images)`.
- **Regression Test Needed**: Yes.

---

### Group 3: Data Profiling Metrics (DP01 - DP07)

#### REQ-DP01: Inventory ($N, M, M_{valid}$, classes, unannotated images)
- **Classification**: **FAIL**
- **Location**: `core/statistics.py:dp01_inventory`
- **Observed Behavior**:
  1. `dp01_inventory` only accepts `valid_objects` ($M_{valid}$), omitting $M$ (total parsed objects including invalid).
  2. Uses `{obj.image_id for obj in valid_objects}` and `{img.image_id for img in images}`, which collides image IDs across datasets if images from multiple datasets are passed.
- **Expected Behavior**:
  Report $N$ (all unique images), $M$ (all parsed boxes), $M_{valid}$ (valid boxes), unique classes, and unannotated image count. Must use `image_key` (or dataset-qualified ID) to prevent cross-dataset collisions.
- **Corrective Action**:
  Update `dp01_inventory` to accept both `all_objects` ($M$) and `valid_objects` ($M_{valid}$), or accept `images` and `valid_objects` plus `invalid_objects`, and use `image_key` for unique image counting.
- **Regression Test Needed**: Yes (multi-dataset inventory with identical local image IDs).

#### REQ-DP02: Class Instance Share
- **Classification**: **PASS**
- **Location**: `core/statistics.py:dp02_class_instance_share`
- **Observed Behavior**: Calculates $\text{count} / M_{valid}$. When $M_{valid} = 0$, returns `ratio: None`, `status: "not_available"`. Verified by `test_profiling.py:test_07_class_ratio_uses_m_valid_denominator` and `test_09_m_valid_zero`.

#### REQ-DP03: Class Image Prevalence
- **Classification**: **PARTIAL**
- **Location**: `core/statistics.py:dp03_class_image_prevalence`
- **Observed Behavior**: Counts unique images per class divided by $N$. Correctly handles $N=0 \implies N/A$. However, groups by `obj.image_id` instead of `obj.image_key` (or qualified image ID), causing collision when datasets share image IDs.
- **Expected Behavior**: Unique images counted using globally stable `image_key`.
- **Corrective Action**: Use `image_key` for unique image set tracking.
- **Regression Test Needed**: Yes.

#### REQ-DP04: Attribute Distribution
- **Classification**: **FAIL**
- **Location**: `core/statistics.py:timeofday_distribution`, `weather_distribution`
- **Observed Behavior**: Only raw counts are returned. No proportions over $N$, no proportions over known, and no integration with 4-state validation.
- **Expected Behavior**: Proportions of each attribute value over $N$ and over known, handling $N=0 \implies N/A$.
- **Corrective Action**: Implement `dp04_attribute_distribution(images, field_name)`.
- **Regression Test Needed**: Yes.

#### REQ-DP05: Relative BBox Area
- **Classification**: **NOT_TESTED**
- **Location**: `core/statistics.py`
- **Observed Behavior**: Not implemented.
- **Expected Behavior**: $\text{area\_ratio} = \frac{(x_{max} - x_{min})(y_{max} - y_{min})}{\text{width} \times \text{height}}$, only for valid bounding boxes.
- **Corrective Action**: Implement in Phase B or C.

#### REQ-DP06 & REQ-DP07: Occlusion Rate & Attribute Availability
- **Classification**: **NOT_TESTED**
- **Location**: `core/statistics.py`
- **Observed Behavior**: Not implemented.

---

### Group 4: Coverage Engine & Recommendations (CV01 - CV06, R01 - R12)

#### REQ-COV01: Coverage Configuration Schema & Validation
- **Classification**: **NOT_TESTED**
- **Location**: `core/coverage_config.py` (file does not exist)
- **Observed Behavior**: Unimplemented.
- **Expected Behavior**: Validate unique slice IDs, unit in `{image, object}`, positive integer target counts, finite positive weights, filter allowlist, no `eval`.

#### REQ-COV02: Slice Evaluation Engine
- **Classification**: **NOT_TESTED**
- **Location**: `core/slice_engine.py` (file does not exist)
- **Observed Behavior**: Unimplemented.
- **Expected Behavior**: Evaluate image and object slices; enforce joint condition on the same object for image slices; track known matches and unresolved metadata units.

#### REQ-COV03: Coverage Metrics Calculation (CV01 - CV05)
- **Classification**: **NOT_TESTED**
- **Location**: `core/coverage_metrics.py` (file does not exist)
- **Observed Behavior**: Unimplemented.
- **Expected Behavior**:
  - $gap_s = \max(0, \tau_s - n_s)$
  - $attainment_s = \min(n_s / \tau_s, 1)$
  - $priority_s = w_s \cdot (1 - attainment_s)$
  - $coverage = \sum [n_s \ge \tau_s] / |S|$
  - $weighted\_coverage = \sum w_s [n_s \ge \tau_s] / \sum w_s$
  - $weighted\_attainment = \sum w_s \cdot attainment_s / \sum w_s$

#### REQ-COV04: Recommendation Engine (Rules R01 - R12)
- **Classification**: **NOT_TESTED**
- **Location**: `core/recommendations.py` (file does not exist)
- **Observed Behavior**: Unimplemented.
- **Expected Behavior**: Deterministic rule execution in specified triage order: R01, R02, R06, R11, R12 first. Deduplicate multiple reasons into single card per slice.

---

## 4. Summary of Failures & Partials Requiring Corrective Action (Phase B Scope)

| Item | Requirement | File & Function | Observed Behavior | Expected Behavior | Corrective Action | Regression Test |
|---|---|---|---|---|---|---|
| **1** | B1: Stable cross-dataset `object_key` & image linking | `core/schema.py:ObjectRecord`, `parsers/cvat_images.py:_parse_box` | `ObjectRecord` lacks `dataset_id`, `object_key`, and links only by local `image_id`. | Stable identifier `dataset_id + object_id` (or parser-stable ID); unambiguous link to `image_key`. | Add `dataset_id` to `ObjectRecord`; parser populates it; add `object_key` and `image_key` properties. | Yes |
| **2** | B1 & B2: Cross-dataset image ID collision in inventory | `core/statistics.py:dp01_inventory` | Uses `{img.image_id}` and `{obj.image_id}` to compute unannotated images. If two datasets share `image_id="0"`, counts collide. | Images across datasets must remain distinct using `image_key`. | Use `img.image_key` and `obj.image_key` in `dp01_inventory`. | Yes |
| **3** | B2: DP01 Inventory missing total parsed objects ($M$) | `core/statistics.py:dp01_inventory` | Accepts only `valid_objects` ($M_{valid}$), omitting $M$. | DP01 specification requires $N$, $M$, $M_{valid}$, class count, unannotated images. | Support passing both total objects ($M$) and valid objects ($M_{valid}$). | Yes |
| **4** | B2: DP03 Cross-dataset image collision | `core/statistics.py:dp03_class_image_prevalence` | Uses `obj.image_id` to set of image IDs. | Distinct image prevalence across datasets requires `image_key`. | Use `obj.image_key` (or qualified ID). | Yes |
| **5** | B2: DP04 Attribute Distribution incomplete | `core/statistics.py:timeofday_distribution`, `weather_distribution` | Only returns raw count dicts; ignores 4-state taxonomy and rates over $N$ and known. | Proportions over $N$ and known; 4 states sum to 100%; $N=0 \implies N/A$. | Add structured `dp04_attribute_distribution` with 4-state taxonomy and rates. | Yes |
| **6** | B2: DQ02-DQ05 Metadata Rates missing | `core/statistics.py` | No functions to compute missing, unknown, invalid, and known rates. | $DQ02$-$DQ05$ computed over $N$, sum to 100%, handle $N=0 \implies N/A$. | Implement `dq02_metadata_missing_rate`, `dq03_unknown_metadata_rate`, `dq04_invalid_metadata_rate`, `dq05_known_metadata_rate`. | Yes |
| **7** | B2: DQ06 Invalid BBox Rate missing | `core/statistics.py` / `core/validation.py` | BBoxes validated during parse, but no metric computes $\text{invalid} / M$ with $M=0 \implies N/A$. | $DQ06 = \text{invalid} / M$; multiple violations per box count once; $M=0 \implies N/A$. | Implement `dq06_invalid_bbox_rate(total_objects, invalid_objects)`. | Yes |
| **8** | B2: DQ09 Scene Tag Conflict Rate missing | `core/statistics.py` / `core/validation.py` | Conflict flagged on image, but no rate metric computed over $N$. | $DQ09 = \text{conflicts} / N$; $N=0 \implies N/A$. | Implement `dq09_scene_tag_conflict_rate(images)`. | Yes |
| **9** | B2: Zero denominator reporting 0% in legacy metric | `core/statistics.py:class_distribution` | Returns `0.0` percentage when `total_objects == 0`. | Zero denominator must yield `None` / `not_available`, never `0%`. | Return `None` for percentage when denominator is zero. | Yes |

---

## 5. Proposed Implementation Order

In accordance with the workflow constraints:

1. **Phase B (Foundational Corrections Only)**:
   - **B1**: Schema and identifier consistency (`ObjectRecord.dataset_id`, `object_key`, `image_key` linking, multi-dataset safety).
   - **B2**: Correct existing metrics and add missing core quality/profiling metrics (DP01 with $M$ and $M_{valid}$, DP03 image_key safety, DP04 attribute rates, DQ02-DQ05 4-state rates, DQ06 invalid box rate with multi-rule deduplication, DQ09 conflict rate, zero denominator $N/A$ enforcement).
   - **B3**: Focused regression test suite in `tests/test_regression_b.py` covering all 10 explicit test cases required in Phase B.
   - Run full test suite and verify 100% pass before proceeding.

2. **Phase C (Coverage Engine Planning & Implementation)**:
   - Slice configuration validation (`core/coverage_config.py`).
   - Slice evaluation engine (`core/slice_engine.py`).
   - Coverage metrics calculation (`core/coverage_metrics.py`).
   - Deterministic recommendation engine (`core/recommendations.py`: R01, R02, R06, R11, R12).
   - UI and export integration.
