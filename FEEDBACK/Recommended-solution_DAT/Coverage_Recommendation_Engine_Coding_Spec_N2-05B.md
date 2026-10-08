# N2-05B: Coverage Measurement & Recommendation Engine

Đặc tả triển khai cho AI coding - v1.0, 08/10/2026.

## 1. Mục tiêu và phạm vi

Xây module đo coverage và đề xuất hành động cho Data Lead trên website đọc CVAT Images XML. Tách thiếu dữ liệu thật, thiếu annotation/metadata, ít nguồn độc lập và hiệu quả thu thập thấp. Không tự sửa/xóa nhãn. Không kết luận model tốt hoặc nhãn sai chỉ từ phân bố.

MVP: Python, Pandas, Streamlit, Plotly; module nghiệp vụ không phụ thuộc UI. Bản này là đặc tả thiết kế, chưa phải code đã kiểm chứng.

## 2. Đầu vào và hợp đồng dữ liệu

| Bảng | Trường | Ghi chú |
|---|---|---|
| images | image_key, image_path, timeofday, weather, metadata_status, source_id | image_key duy nhất; source_id tùy chọn |
| objects | object_key, image_key, class_name, area_ratio, valid_geometry | Một bbox một dòng; area_ratio chỉ có khi geometry hợp lệ |
| sources | source_id, source_kind, scene_id/video_id | Tùy chọn; cần để đo nguồn độc lập |
| collection_log | candidate_id, batch_id, accepted, rejection_reason, image_key, effort_hours, cost | Tùy chọn; không suy từ XML |
| duplicate_groups | image_key, group_id, confirmed | Tùy chọn; không suy ảnh gần trùng từ tên file |
| review_log | image_key, review_status, metadata_verified, label_verified | Tùy chọn; unknown không chứng minh đã review |

metadata_status được tính riêng từng trường: known/unknown/missing/invalid/conflict. Không ép tất cả thành unknown. Giữ nguyên giá trị gốc và báo xung đột.

Chỉ đo những bản ghi thực có trong export. Nếu XML không liệt kê mọi ảnh của task, báo giới hạn inventory và không tuyên bố tổng ảnh toàn task.

## 3. Slice configuration

```json
{
  "definition_version": "1.0",
  "config_version": "1",
  "metadata_policy": {
    "missing_warning_rate": 0.05,
    "unknown_warning_rate": 0.10
  },
  "slices": [
    {
      "id": "person_night_rain",
      "name": "Người đi bộ ban đêm trời mưa",
      "unit": "image",
      "filters": {
        "contains_class": "person",
        "timeofday": "night",
        "weather": "rain"
      },
      "target_count": 50,
      "weight": 3,
      "min_independent_sources": 3,
      "enabled": true,
      "feasibility": "confirmed",
      "target_reason": "Ví dụ cấu hình; Lead phải duyệt"
    },
    {
      "id": "small_person_night",
      "name": "BBox người đi bộ nhỏ ban đêm",
      "unit": "object",
      "filters": {
        "class_name": "person",
        "timeofday": "night",
        "area_ratio_max": 0.01
      },
      "target_count": 100,
      "weight": 2,
      "enabled": true,
      "feasibility": "unverified",
      "target_reason": "Ví dụ cấu hình; chưa phải chuẩn"
    }
  ]
}
```

Validate: id duy nhất; unit thuộc image/object; target_count nguyên >0; weight hữu hạn >0; ngưỡng tỷ lệ trong [0,1]; filters thuộc allowlist; không dùng eval để chạy biểu thức. Không silently bỏ qua filter chưa hỗ trợ. Thiếu class trong schema phải cảnh báo cấu hình/nguồn trước khi coi là thiếu mẫu thật.

Bbox size là kích thước trên ảnh, không phải khoảng cách. Ngưỡng size là nội bộ, không gọi là chuẩn COCO.

## 4. Semantics của bộ lọc

- Image slice: AND các điều kiện metadata ảnh với điều kiện tồn tại object phù hợp; đếm image_key duy nhất.
- Object slice: AND class, geometry/size và metadata của ảnh chứa object; đếm object_key duy nhất.
- Nếu image slice dùng class + size, tồn tại **cùng một object** thỏa class và size; không ghép person lớn với car nhỏ để kết luận small person.
- Ảnh không bbox vẫn nằm trong inventory; chưa đủ bằng chứng gọi là background.
- Metadata thiếu/conflict không được xem là không thỏa một cách chắc chắn. Trả số known match và số đơn vị chưa xác định được điều kiện.
- Giữ required-field availability cho từng slice. Không dùng tỷ lệ thiếu weather để chặn slice chỉ cần class.
- Class annotation có thể bị sót; support dựa trên nhãn đã ghi nhận, không phải ground truth mặc định.

## 5. Metric definitions

Với tập slice enabled, khả thi và cấu hình hợp lệ S:

```text
support_s = số đơn vị đã ghi nhận thỏa slice
 gap_s = max(0, target_count_s - support_s)
attainment_s = min(support_s / target_count_s, 1)
priority_s = weight_s * (1 - attainment_s)
coverage = sum(support_s >= target_count_s) / |S|
weighted_coverage = sum(weight_s * (support_s >= target_count_s)) / sum(weight_s)
weighted_attainment = sum(weight_s * attainment_s) / sum(weight_s)
coverage_gain = coverage_after - coverage_before
```

Khoảng thiếu là **observed gap** theo annotation. Khi metadata chưa đủ, đánh dấu provisional: có thể một phần gap nằm trong ảnh chưa xác định. Không tự suy rộng tỷ lệ sang ảnh thiếu metadata.

Nếu unknown/thiếu tồn tại, coverage tổng báo observed/provisional; công bố số slice unresolved và số bị loại khỏi S. Không tuyên bố đạt quality gate toàn bộ nếu còn slice bắt buộc chưa đánh giá được. Khi S rỗng: N/A.

| Metric | Numerator/denominator | Dữ liệu cần |
|---|---|---|
| Support | số image/object phù hợp | CVAT + metadata |
| Gap, Attainment | support so target | Cấu hình |
| Independent Source Support | số nguồn độc lập có mẫu phù hợp | source_id đã xác nhận |
| Redundancy Rate | số ảnh dư ngoài một đại diện/group / số ảnh xét | duplicate groups đã xác nhận |
| Acceptance Rate | candidate accepted / candidate có quyết định cuối | collection_log |
| Useful Slice Yield | candidate accepted có image thuộc ít nhất một slice ưu tiên / candidate có quyết định cuối | Log + mapping ảnh |
| Collection Efficiency | candidate hữu ích duy nhất / giờ hoặc chi phí | Log effort/cost |

Không tính chi phí/thời gian bằng cách cộng trường batch lặp trên mỗi ảnh: chuẩn hóa effort/cost một lần theo event/batch. Log chưa có quyết định báo pending; không biến pending thành rejected. Nếu chưa mapping đủ accepted candidates, Useful Yield là N/A/provisional và ghi rõ availability.

Coverage Gain chỉ tính khi slice definitions, unit, target, weight và scope tương thích; nếu đổi cấu hình, recompute cả before/after bằng cấu hình chung hoặc từ chối so sánh.

Nguồn “độc lập” cần quy ước project: một video có thể có nhiều scene nhưng không mặc định độc lập hoàn toàn. Không tự coi filename là source_id.

## 6. Ma trận luật khuyến nghị

Ngưỡng trong config là ví dụ cần Lead duyệt, không chuẩn chung.

| Rule ID | Điều kiện | Khuyến nghị | Đo lại |
|---|---|---|---|
| R01 ZERO_SUPPORT | support=0, target>0 | Kiểm tra metadata, schema/class và tính khả thi; thiếu thật mới thu thập chuyên biệt | Support, gap |
| R02 BELOW_TARGET | 0<support<target | Review mẫu; bổ sung slice thiếu theo ưu tiên | Attainment, coverage |
| R03 LOW_SOURCE_DIVERSITY | support>=target và nguồn có sẵn, số nguồn<minimum | Bổ sung video/cảnh/địa điểm/camera phù hợp; không chỉ thêm frame cùng nguồn | Source support |
| R04 REDUNDANCY_HIGH | redundancy xác nhận vượt ngưỡng | Review nhóm trùng; chọn đại diện, giảm lấy frame dày | Redundancy, useful support |
| R05 JOINT_GAP | joint slice thiếu, các marginal configured đạt mục tiêu | Tìm và thu thập đúng tổ hợp; không tiếp tục chỉ bổ sung từng biến riêng | Joint support/gap |
| R06 METADATA_INSUFFICIENT | missing/unknown/invalid/conflict ở trường cần cho slice vượt policy | Bổ sung tags/CSV hoặc review; không kết luận thiếu ảnh thật | Availability và support |
| R07 LOW_USEFUL_YIELD | useful yield thấp với log đầy đủ, đủ số candidate | Đổi nguồn/truy vấn/khung giờ; thử lô nhỏ trước mở rộng | Useful yield |
| R08 LOW_ACCEPTANCE | acceptance thấp với đủ candidate có quyết định | Xem rejection_reason; sửa quy trình đầu vào theo lý do phổ biến | Acceptance theo lý do |
| R09 LOW_EFFICIENCY | efficiency dưới mục tiêu, log effort/cost hợp lệ | Xác định công đoạn tốn chi phí; so nguồn khác trên lô thử | Efficiency |
| R10 LOW_COVERAGE_GAIN | batch thêm đủ mẫu theo policy nhưng gain thấp | Xem attainment: có thể đang gần ngưỡng; nếu mẫu vào slice đủ rồi, chuyển ngân sách | Gain + attainment |
| R11 CRITICAL_RARE_GAP | support<target và weight>=critical_weight | Ưu tiên thu thập chuyên biệt; ghi giới hạn nếu chưa đạt | Weighted coverage |
| R12 TARGETS_MET | slice bắt buộc đạt target, không unresolved/blocker | Chuyển review/bàn giao; vẫn kiểm tra chất lượng và đa dạng nguồn | Audited quality |

R05 cần marginal_slice_ids cấu hình rõ, không tự bịa mục tiêu marginal. R10 cần min_added_samples và min_gain cấu hình, snapshot tương thích. R03/R04/R07-R10 không có đầu vào thì trả skipped/not_available cùng lý do, không đưa lời khuyên như đã đo.

## 7. Thứ tự xử lý và triage

1. Input/config/schema blockers: báo lỗi và yêu cầu sửa.
2. Metadata unresolved: ưu tiên xác minh; giảm mức chắc chắn của lời khuyên thu thập.
3. Xác minh coverage gap và annotation status.
4. Diversity/redundancy: tránh lấy thêm dữ liệu lặp.
5. Thu thập có mục tiêu; tối ưu yield/cost nếu có log.
6. Review và bàn giao.

Không coi mọi rule là blocker. Low coverage là planning warning; invalid schema có thể là blocker theo policy. R11 có thể đồng thời R01/R02: gom thành một recommendation cho slice, giữ nhiều reason_codes. Không phát đồng thời “bàn giao” và “còn blocker”.

Severity và priority khác nhau: blocker > review_required > planning > info. Priority formula chỉ xếp gap trong cùng nhóm; chưa bao gồm chi phí, accuracy hoặc uncertainty. Phải ghi lý do weight/target.

## 8. Recommendation output

```json
{
  "recommendation_id": "datasetA_person_night_rain_v1",
  "slice_id": "person_night_rain",
  "rule_ids": ["R02", "R11"],
  "category": "collection_gap",
  "severity": "planning",
  "evidence_status": "observed_annotation",
  "support": 10,
  "target": 50,
  "gap": 40,
  "attainment": 0.2,
  "priority": 2.4,
  "unit": "image",
  "title": "Ưu tiên kiểm tra và bổ sung người đi bộ ban đêm trời mưa",
  "actions": [
    "Kiểm tra metadata và kho ảnh hiện có",
    "Nếu xác nhận thiếu, thu thập đúng tổ hợp từ nguồn đa dạng"
  ],
  "remeasure": ["support", "gap", "independent_source_support"],
  "limitations": ["Support dựa trên annotation, có thể còn nhãn sót"],
  "affected_image_keys": [],
  "config_version": "1",
  "dataset_version": "export_2026_10_08"
}
```

Nếu zero support, affected_image_keys có thể rỗng; không dựng ảnh giả. Với metadata rule, xuất ảnh cần bổ sung. Với collection gap, xuất ảnh hiện có và điều kiện tìm mẫu mới riêng. Link CVAT chỉ sinh khi mapping task/job/frame được xác nhận; thiếu mapping thì xuất image_path.

## 9. Giao diện và export

- Tab Coverage: support, target, gap, attainment, weight, priority, metadata availability, source support, status.
- Cho chọn slice, sửa target/weight; tăng config_version và tính lại.
- Tổng quan hiển thị observed coverage, weighted coverage/attainment, unresolved slices.
- Panel Actions: vấn đề → bằng chứng → bước xác minh → hành động → chỉ số đo lại.
- Nhãn rõ: thiếu metadata / thiếu mẫu đã ghi nhận / ít nguồn / chưa đủ đầu vào đo.
- Export metrics.csv, recommendations.csv, affected_images.csv, config.json; mỗi output có dataset/config version và unit.
- Không cộng gap từng slice thành “tổng ảnh cần lấy”. Có thể cho biết một ảnh mới thỏa nhiều slice nếu đã đo mapping, chưa giải bài toán tối ưu set cover trong MVP.

## 10. Module và API đề xuất

```text
core/coverage_config.py     # validate config
core/slice_engine.py        # apply filters, unknown availability
core/coverage_metrics.py    # support/gap/attainment/coverage
core/collection_metrics.py  # optional logs
core/recommendations.py     # deterministic rules and dedup
core/coverage_export.py
ui/coverage.py
ui/recommendations.py
tests/test_coverage.py
tests/test_recommendations.py
```

```python
validate_config(config) -> ValidationResult
measure_slices(images, objects, config, sources=None) -> SliceResults
measure_collection(logs, slice_results, effort=None) -> CollectionResults
compare_snapshots(before, after, config) -> ComparisonResult
recommend(slice_results, collection_results, config) -> list[Recommendation]
```

Sử dụng rule engine xác định bằng Python, không cần LLM trong MVP. Có thể dùng template sinh lời khuyên; AI coding không được thay công thức bằng suy luận ngôn ngữ. Tách message tiếng Việt khỏi logic.

## 11. Test fixtures và acceptance criteria

1. Một ảnh có ba person thỏa slice: image support=1; object support=3.
2. Ảnh có person lớn và car nhỏ: không được tính small-person image slice.
3. support=10, target=50, weight=3: gap=40, attainment=0.2, priority=2.4.
4. support>target: gap=0, attainment=1, priority=0.
5. Metadata cần thiết missing: unresolved count tăng; không khẳng định thiếu thật.
6. Không source_id: diversity=N/A; không kích hoạt LOW_SOURCE_DIVERSITY.
7. Unknown không tính là day/night; trạng thái tách missing.
8. Class không có trong label schema: cảnh báo cấu hình/nguồn.
9. Hai slice overlap: không cộng gap; useful yield đếm mỗi candidate một lần.
10. Đổi target/config giữa snapshots: không tự so gain cũ/mới.
11. Effort batch lặp trên ảnh: chỉ tính một lần theo event/batch.
12. Không collection log: yield/acceptance/efficiency N/A.
13. R01/R11 cùng slice: một card, hai reasons.
14. Bbox invalid: không dùng area_ratio sai cho size slice; công bố excluded.
15. S rỗng, denominator=0, cost/hours=0: N/A, không chia 0.
16. Tất cả target đạt nhưng metadata blocker còn: không phát TARGETS_MET bàn giao toàn bộ.

Các phép đếm fixture khớp hoàn toàn đáp án; recommendation tái lập với cùng dataset và config; bộ lọc không bỏ qua điều kiện; không biến N/A thành 0. Thử file thật của ít nhất hai team trước bàn giao.

## 12. Trình tự coding

1. Chốt schema từ parser hiện có, normalize IDs và metadata.
2. Validate slice config, viết fixtures độc lập.
3. Slice engine + coverage metrics và tests.
4. Rules R01/R02/R06/R11/R12 trước; triển khai R05 khi có marginal config.
5. UI, export và liên kết ảnh.
6. Thêm diversity/redundancy/log-based rules khi có dữ liệu.
7. Pilot, chỉnh ngưỡng có version; báo giới hạn.

## 13. Cơ sở tham khảo

- Coverage theo tổ hợp thuộc tính: Lin et al., PVLDB 2020. https://www.vldb.org/pvldb/vol13/p2229-lin.pdf
- Chất lượng/tính đại diện theo bối cảnh: NIST AI RMF Measure. https://airc.nist.gov/airmf-resources/playbook/measure/
- Schema validation, drift/skew: https://tensorflow.github.io/tfx/guide/tfdv/
- Tài liệu nguồn và quy trình thu thập: https://arxiv.org/abs/1803.09010

Ma trận, metric vận hành và priority score ở đây là thiết kế vận dụng của dự án, không phải ngưỡng phổ quát được các nguồn quy định.
