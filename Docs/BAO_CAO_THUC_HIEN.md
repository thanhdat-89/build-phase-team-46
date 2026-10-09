# Báo Cáo Thực Hiện Kỹ Thuật (N2-05B)

- **Tài liệu tham chiếu chuẩn nguồn sự thật**:
  1. `FEEDBACK/Recommended-solution_DAT/Co_so_ly_thuyet_Data_Quality_Coverage_N2-05B.md`
  2. `FEEDBACK/Recommended-solution_DAT/Coverage_Recommendation_Engine_Coding_Spec_N2-05B.md`
- **Phiên bản báo cáo**: 1.0 (Hoàn thành Phase B — Nền tảng cốt lõi)
- **Ngày thực hiện**: 09/10/2026
- **Trạng thái kiểm thử**: **114/114 tests PASS (100%)**

---

## 1. Tổng quan

- **Giai đoạn đã hoàn thành**: **Phase B — Triển khai nền tảng đúng đắn nhỏ nhất (Smallest Correct Foundation: B1, B2, B3)** sau khi hoàn tất kiểm tra đánh giá baseline ở Phase A.
- **Mục tiêu của giai đoạn**:
  1. Đảm bảo tính nhất quán của định danh thực thể (`image_key`, `object_key`) xuyên suốt giữa các dataset, không để trùng lặp hoặc xung đột ID khi phân tích nhiều đợt dữ liệu.
  2. Khắc phục các vi phạm đặc tả trong tính toán chỉ số thống kê (`dp01_inventory`, `dp03_class_image_prevalence`, `class_distribution`).
  3. Bổ sung các chỉ số chất lượng dữ liệu (Data Quality) và mô tả thuộc tính (Data Profiling) cốt lõi còn thiếu: `DP04`, `DQ02`, `DQ03`, `DQ04`, `DQ05`, `DQ06`, `DQ09`.
  4. Chuẩn hóa quy tắc xử lý mẫu số bằng 0 (Zero Denominator): khi mẫu số bằng 0, bắt buộc trả về `not_available` (giá trị `None` / `null`) kèm lý do rõ ràng, tuyệt đối không trả về `0%` gây hiểu nhầm rằng đã đo lường và đạt 0%.
  5. Xây dựng bộ kiểm thử hồi quy tập trung (`tests/test_regression_b.py`) gồm 10 ca kiểm thử then chốt theo đúng tài liệu đặc tả.
- **Những phần đã hoàn thành**:
  - Cập nhật cấu trúc [`ObjectRecord`](file:///d:/buildphase/build-phase-team-46/core/schema.py#L38) trong [`core/schema.py`](file:///d:/buildphase/build-phase-team-46/core/schema.py) với `dataset_id`, property `image_key` và property `object_key`.
  - Cập nhật parser [`parsers/cvat_images.py`](file:///d:/buildphase/build-phase-team-46/parsers/cvat_images.py) để truyền và bảo toàn `dataset_id` khi bóc tách từng bounding box `<box>`.
  - Viết lại hàm thống kê [`core/statistics.py`](file:///d:/buildphase/build-phase-team-46/core/statistics.py) với logic phân giải khóa cha thông minh `resolve_obj_image_key`, sửa lỗi đếm nhầm ảnh chưa gán nhãn, bổ sung đầy đủ bộ chỉ số `DP04`, `DQ02`–`DQ06`, `DQ09`.
  - Viết 10 ca kiểm thử hồi quy mới trong [`tests/test_regression_b.py`](file:///d:/buildphase/build-phase-team-46/tests/test_regression_b.py).
  - Toàn bộ 114 test (104 test cũ + 10 test mới) đều chạy thành công.
- **Những phần chưa thực hiện (theo kế hoạch dừng đúng điều kiện Phase B)**:
  - Chưa triển khai Coverage Engine (Phase C): cấu hình slice, engine lọc slice, bộ luật khuyến nghị R01–R12, đo lường độ bao phủ có trọng số.

---

## 2. Những vấn đề đã phát hiện trong mã nguồn cũ

Dưới đây là các khiếm khuyết được xác nhận qua quá trình audit mã nguồn so với hai tài liệu đặc tả:

### Vấn đề 1: Trùng lặp khóa định danh giữa các Dataset (Cross-dataset collision)
- **Vị trí**: [`core/schema.py`](file:///d:/buildphase/build-phase-team-46/core/schema.py) (`ObjectRecord`), [`core/statistics.py`](file:///d:/buildphase/build-phase-team-46/core/statistics.py) (`dp01_inventory`, `dp03_class_image_prevalence`).
- **Hành vi cũ**:
  `ObjectRecord` chỉ lưu trường `image_id: str` (ví dụ `"0"`), không có `dataset_id` và không có `object_key`. Khi tính toán ảnh chưa gán nhãn, `dp01_inventory` dùng tập hợp:
  ```python
  annotated_image_ids = {obj.image_id for obj in valid_objects}
  all_image_ids = {img.image_id for img in images}
  unannotated_images = len(all_image_ids - annotated_image_ids)
  ```
- **Hậu quả**: Nếu hai dataset khác nhau cùng có `image_id="0"`, hệ thống coi hai ảnh này là một. Nếu ảnh ở dataset A có bbox còn ảnh ở dataset B không có bbox, thì ảnh ở dataset B bị tính nhầm thành đã có nhãn (`unannotated_images` bị đếm thiếu).
- **Hành vi đúng theo đặc tả**: `image_key` bắt buộc là `dataset_id + image_id` và `object_key` là `dataset_id + object_id`. Các phép tính đếm tập hợp ảnh duy nhất bắt buộc phải dựa trên `image_key`.
- **Mức độ**: Lỗi xác nhận (Confirmed Defect).

### Vấn đề 2: Chỉ số DP01 thiếu số lượng tổng bounding box bóc tách ($M$)
- **Vị trí**: [`core/statistics.py:dp01_inventory`](file:///d:/buildphase/build-phase-team-46/core/statistics.py#L55)
- **Hành vi cũ**: Hàm chỉ nhận `valid_objects` ($M_{valid}$), hoàn toàn không có thông tin về tổng số bounding box đã parse ($M$ bao gồm cả box sai hình học).
- **Hành vi đúng**: Theo mục 3.1 & 5 của tài liệu Cơ sở lý thuyết, DP01 Inventory phải báo cáo đủ: $N$ (tổng ảnh), $M$ (tổng bbox đã parse), $M_{valid}$ (tổng bbox hợp lệ), số lượng class, và số ảnh chưa gán nhãn.
- **Mức độ**: Lỗi xác nhận (Confirmed Defect).

### Vấn đề 3: Báo cáo tỷ lệ 0% khi mẫu số bằng 0 (Zero Denominator Distortion)
- **Vị trí**: [`core/statistics.py:class_distribution`](file:///d:/buildphase/build-phase-team-46/core/statistics.py#L232)
- **Hành vi cũ**: Khi `total_objects == 0`, hàm trả về `"percentage": 0.0`.
- **Hành vi đúng**: Đặc tả mục 4 quy định rõ: *"Nếu mẫu số bằng 0: hiển thị N/A, không hiển thị 0%"*. Trả về 0% làm người dùng hiểu nhầm rằng tập dữ liệu đã được đo lường và đạt kết quả 0%, trong khi thực tế là không thể đo được (không có đối tượng nào).
- **Mức độ**: Lỗi xác nhận (Confirmed Defect).

### Vấn đề 4: Thiếu hoàn toàn các hàm đo lường Data Quality (DQ02–DQ05, DQ06, DQ09)
- **Vị trí**: [`core/statistics.py`](file:///d:/buildphase/build-phase-team-46/core/statistics.py)
- **Hành vi cũ**: Dù [`core/validation.py`](file:///d:/buildphase/build-phase-team-46/core/validation.py) đã có logic phân loại 4 trạng thái metadata, nhưng không có hàm độc lập nào trả về các chỉ số:
  - `DQ02` (Metadata Missing Rate)
  - `DQ03` (Unknown Metadata Rate)
  - `DQ04` (Invalid Metadata Rate)
  - `DQ05` (Known Metadata Rate)
  - `DQ06` (Invalid BBox Rate)
  - `DQ09` (Scene Tag Conflict Rate)
  Hàm `timeofday_distribution` và `weather_distribution` chỉ trả về dict đếm số lượng nguyên thô, nếu gặp giá trị invalid (như `"sunset"`) thì tạo ra key mới tùy tiện thay vì gộp vào nhóm invalid theo taxonomy.
- **Hành vi đúng**: Phải có các hàm metric chuẩn hóa trả về đúng cấu trúc đặc tả (Hợp đồng JSON mục 12: `metric_id`, `scope`, `numerator`, `denominator`, `value`, `status`, `reason`). 4 trạng thái metadata phải cộng lại bằng 100%. Bbox lỗi nhiều quy tắc hình học chỉ được tính là 1 box lỗi trong `DQ06`.
- **Mức độ**: Lỗi thiếu chức năng cam kết trong chuẩn đặc tả.

---

## 3. Những thay đổi đã thực hiện

| File | Thay đổi | Lý do | Kết quả |
|---|---|---|---|
| [`core/schema.py`](file:///d:/buildphase/build-phase-team-46/core/schema.py) | Bổ sung `dataset_id: str = "default"`, property `image_key` và property `object_key` vào [`ObjectRecord`](file:///d:/buildphase/build-phase-team-46/core/schema.py#L38). | Đảm bảo mỗi đối tượng có định danh duy nhất ổn định xuyên suốt các dataset (`dataset_id:object_id`) và liên kết được với ảnh cha (`dataset_id:image_id`). | Đối tượng không còn bị nhầm lẫn khi nạp nhiều batch dữ liệu. Vẫn tương thích ngược 100% với code cũ nếu không truyền `dataset_id`. |
| [`parsers/cvat_images.py`](file:///d:/buildphase/build-phase-team-46/parsers/cvat_images.py) | Cập nhật hàm `_parse_box` và vòng lặp trong `parse_cvat_zip` để truyền `dataset_id=dataset_id` vào từng `ObjectRecord`. | Bóc tách XML đồng bộ `dataset_id` từ cấp file/batch xuống từng bounding box. | Khi parser đọc file ZIP, tất cả đối tượng đều có `dataset_id` chính xác khớp với ảnh cha. |
| [`core/statistics.py`](file:///d:/buildphase/build-phase-team-46/core/statistics.py) | 1. Thêm helper `classify_field` và `resolve_obj_image_key`.<br>2. Sửa `dp01_inventory` nhận `all_objects` và dùng `image_key`.<br>3. Sửa `dp03_class_image_prevalence` và `class_image_distribution` dùng `image_key`.<br>4. Sửa `class_distribution` trả về `percentage: None` khi mẫu số bằng 0.<br>5. Cập nhật `timeofday_distribution` và `weather_distribution`.<br>6. Cài đặt các hàm mới: `dp04_attribute_distribution`, `dq02_metadata_missing_rate`, `dq03_unknown_metadata_rate`, `dq04_invalid_metadata_rate`, `dq05_known_metadata_rate`, `dq06_invalid_bbox_rate`, `dq09_scene_tag_conflict_rate`. | Khắc phục toàn bộ các lỗi đã phát hiện trong Phase A, bảo toàn tính toán tập hợp đa dataset, tuân thủ đúng công thức đặc tả và hợp đồng trả về JSON mục 12. | Các metric hoạt động chính xác, giải quyết triệt để lỗi va chạm ID, trả về đúng `not_available` khi $N=0$ hoặc $M=0$, bảo toàn 100% tương thích ngược với các test cũ. |
| [`tests/test_regression_b.py`](file:///d:/buildphase/build-phase-team-46/tests/test_regression_b.py) | Tạo mới bộ test hồi quy tập trung gồm 10 ca kiểm thử cho toàn bộ các yêu cầu của Phase B. | Kiểm chứng tính đúng đắn một cách định lượng và ngăn ngừa hồi quy. | 10/10 test đều vượt qua. |

---

## 4. Giải thích logic nghiệp vụ chi tiết

### 4.1 Định danh và liên kết giữa ảnh và đối tượng (`image_key`, `object_key`)
- Trong môi trường annotation thực tế, các đợt dữ liệu xuất ra từ CVAT thường tự động đánh số `image id="0"`, `id="1"`, `id="2"` hoặc số thứ tự frame `frame_000000`. Khi gom nhiều batch vào hệ thống profiling, số ID này chắc chắn bị trùng.
- Để giải quyết:
  - Cấp ảnh: `image_key = f"{dataset_id}:{image_id}"`.
  - Cấp đối tượng: `object_key = f"{dataset_id}:{object_id}"`.
  - Hàm `resolve_obj_image_key` kiểm tra: nếu `obj.image_key` nằm trong danh sách ảnh, dùng trực tiếp; nếu đối tượng được khởi tạo từ fixture cũ (chưa gán `dataset_id`), hàm tìm kiếm ngược dựa trên `image_id` trong danh sách ảnh của batch hiện tại. Nhờ đó, cả mã nguồn kiểm thử cũ lẫn luồng dữ liệu mới đều hoạt động trơn tru.

### 4.2 Bốn trạng thái Metadata loại trừ lẫn nhau (4-State Taxonomy)
Theo tài liệu lý thuyết mục 3.2, với bất kỳ trường metadata nào (ví dụ `timeofday` hay `weather`), mỗi ảnh phải rơi vào đúng 1 trong 4 trạng thái:
1. `known`: Giá trị nằm trong danh mục chuẩn (ví dụ `timeofday` thuộc `{"day", "night", "dawn_dusk"}`).
2. `unknown`: Được người gán nhãn ghi rõ là `"unknown"` (chưa xác định được khi xem ảnh). Trạng thái này không đồng nghĩa với việc ảnh bị thiếu nhãn.
3. `missing`: Không có thẻ metadata, giá trị rỗng (`""`), khoảng trắng hoặc `None`.
4. `invalid`: Có giá trị nhưng nằm ngoài danh mục chuẩn (ví dụ gán nhãn `timeofday="midnight"` hoặc gõ sai chính tả). Giá trị gốc được lưu lại để phục vụ việc rà soát.

Tổng số lượng ảnh của 4 trạng thái này luôn bằng đúng tổng số ảnh $N$:
$$\text{count}(known) + \text{count}(unknown) + \text{count}(missing) + \text{count}(invalid) = N$$
Do đó:
$$DQ02 + DQ03 + DQ04 + DQ05 = 100\% \quad (\text{khi } N > 0)$$

### 4.3 Cách tính các chỉ số Data Quality (DQ) và Data Profiling (DP)
- **DP01 (Inventory)**:
  - $N$: `total_images` (toàn bộ ảnh đã nạp, kể cả ảnh không có bbox).
  - $M$: `total_objects` (toàn bộ bbox đã parse, kể cả bbox lỗi hình học).
  - $M_{valid}$: `total_valid_objects` (bbox vượt qua mọi quy tắc hình học).
  - `annotated_image_count`: Số ảnh duy nhất có $\ge 1$ bbox hợp lệ.
  - `unannotated_image_count`: $N - \text{annotated\_image\_count}$.
- **DP02 (Class Instance Share)**:
  $$\text{Share}(c) = \frac{\text{số bbox hợp lệ của class } c}{M_{valid}}$$
  Nếu $M_{valid} = 0$, trả về `status: "not_available"`, `ratio: None`.
- **DP03 (Class Image Prevalence)**:
  $$\text{Prevalence}(c) = \frac{\text{số ảnh duy nhất chứa ít nhất một bbox hợp lệ của class } c}{N}$$
  Một ảnh có 5 người thì chỉ tính là 1 ảnh có người. Tổng tỷ lệ giữa các class có thể $> 100\%$ do một ảnh chứa nhiều class.
- **DP04 (Attribute Distribution)**:
  Báo cáo số lượng và tỷ lệ của từng giá trị thuộc tính trên tổng số ảnh $N$, đồng thời tính tỷ lệ trên tập các ảnh `known` ($\text{count}(v) / \text{total\_known}$).
- **DQ06 (Invalid BBox Rate)**:
  $$DQ06 = \frac{\text{số bbox vi phạm ít nhất một quy tắc hình học}}{M}$$
  *Quy tắc bất biến*: Một bbox dù vi phạm cùng lúc 3 lỗi (vừa tọa độ $x$ đảo ngược, vừa chiều cao bằng 0, vừa tràn biên ảnh) thì vẫn chỉ được tính là **1 bbox không hợp lệ** ở tử số.
- **DQ09 (Scene Tag Conflict Rate)**:
  $$DQ09 = \frac{\text{số ảnh có thẻ scene\_info xung đột}}{N}$$
  Ảnh có nhiều thẻ `scene_info` mang giá trị trái ngược nhau (ví dụ vừa `day` vừa `night`) sẽ bị gắn cờ xung đột và không được tự ý chọn bừa một giá trị.

### 4.4 Xử lý mẫu số bằng 0 (Zero Denominator Handling)
Tất cả các hàm metric đều tuân thủ hợp đồng:
- Khi $N = 0$ hoặc $M = 0$:
  - `value`: `None` (JSON: `null`).
  - `status`: `"not_available"`.
  - `reason`: Chuỗi lý do rõ ràng (ví dụ `"Empty dataset (N=0)"`, `"No bounding boxes (M=0)"`).
- Tuyệt đối không trả về `0.0` hay `"0%"` trong trường hợp không có dữ liệu mẫu.

---

## 5. Kết quả kiểm thử

### 5.1 Lệnh kiểm thử thực tế
Lệnh thực thi trong môi trường Python của workspace:
```powershell
uv run --with-requirements requirements.txt python -m pytest
```

### 5.2 Kết quả tổng thể
```text
============================= test session starts =============================
platform win32 -- Python 3.12.15, pytest-9.1.1, pluggy-1.6.0
rootdir: D:\buildphase\build-phase-team-46
plugins: anyio-4.15.1
collected 114 items

tests\test_parser.py ....................                                [ 17%]
tests\test_profiling.py ..................                               [ 33%]
tests\test_regression_b.py ..........                                    [ 42%]
tests\test_statistics.py .......................................         [ 76%]
tests\test_validation.py ...........................                     [100%]

============================= 114 passed in 0.88s =============================
```
- **Tổng số test**: 114 test.
- **Số lượng passed**: 114 (100%).
- **Số lượng failed**: 0.

### 5.3 Chi tiết các ca kiểm thử trong `tests/test_regression_b.py`
1. `test_01_two_datasets_same_image_id_remain_distinct`: Xác nhận hai dataset có cùng `frame_001` không bị nhập làm một; tính đúng prevalence và inventory.
2. `test_02_images_without_bounding_boxes_remain_in_inventory`: Xác nhận ảnh không nhãn vẫn tồn tại đầy đủ trong mẫu số $N$.
3. `test_03_multi_rule_violating_box_counted_once`: Xác nhận một bbox dính nhiều lỗi hình học chỉ đóng góp đúng 1 lần vào tử số của DQ06.
4. `test_04_metadata_states_remain_distinguishable`: Xác nhận 4 trạng thái known, unknown, missing, invalid tách biệt và có tổng tỷ lệ đúng 100%.
5. `test_05_scene_tag_conflicts_explicitly_represented`: Xác nhận xung đột thẻ cảnh được nhận diện và tính đúng DQ09, không tự ý chọn giá trị.
6. `test_06_zero_denominators_produce_not_available_with_reason`: Xác nhận khi $N=0$ hoặc $M=0$, các hàm đều trả về `not_available`, `value=None` kèm lý do, không trả về 0%.
7. `test_07_image_level_filters_applied_before_matching_objects`: Xác nhận bộ lọc cấp ảnh lọc trước khi xét các đối tượng bên trong.
8. `test_08_image_and_object_level_metrics_differ_appropriately`: Xác nhận 1 ảnh chứa 4 pedestrian thì image prevalence là 1 còn object count là 4.
9. `test_09_class_image_prevalence_counts_unique_images_not_instances`: Xác nhận 2 ảnh chứa 5 xe car thì class image prevalence đếm tử số là 2, không đếm 5.
10. `test_10_existing_and_extended_contract_compatibility`: Xác nhận toàn bộ hợp đồng API mở rộng tương thích hoàn toàn với luồng cũ.

---

## 6. Đối chiếu với hai tài liệu Markdown đặc tả

| ID Yêu cầu | Tên yêu cầu | Trạng thái | Bằng chứng kiểm chứng |
|---|---|---|---|
| **REQ-S01** | Stable `image_key` (`dataset_id:image_id`) | **PASS** | [`core/schema.py:ImageRecord.image_key`](file:///d:/buildphase/build-phase-team-46/core/schema.py#L31); `test_regression_b.py:test_01` |
| **REQ-S02** | Stable `object_key` (`dataset_id:object_id`) | **PASS** | [`core/schema.py:ObjectRecord.object_key`](file:///d:/buildphase/build-phase-team-46/core/schema.py#L62); [`parsers/cvat_images.py:363`](file:///d:/buildphase/build-phase-team-46/parsers/cvat_images.py#L363); `test_regression_b.py:test_01` |
| **REQ-S03** | Bảo toàn ảnh không có bbox trong inventory | **PASS** | [`core/statistics.py:dp01_inventory`](file:///d:/buildphase/build-phase-team-46/core/statistics.py#L55); `test_profiling.py:test_02`; `test_regression_b.py:test_02` |
| **REQ-S04** | Phân loại 4 trạng thái metadata (known/unknown/missing/invalid) | **PASS** | [`core/validation.py:validate_metadata_value`](file:///d:/buildphase/build-phase-team-46/core/validation.py#L218); `test_regression_b.py:test_04` |
| **REQ-S05** | Phát hiện và giữ nguyên xung đột scene_info | **PASS** | [`core/validation.py:validate_scene_tags`](file:///d:/buildphase/build-phase-team-46/core/validation.py#L285); `test_validation.py:test_19`; `test_regression_b.py:test_05` |
| **REQ-DP01** | Inventory ($N$, $M$, $M_{valid}$, classes, unannotated) | **PASS** | [`core/statistics.py:dp01_inventory`](file:///d:/buildphase/build-phase-team-46/core/statistics.py#L55); `test_regression_b.py:test_02, test_10` |
| **REQ-DP02** | Class Instance Share ($M_{valid}$ mẫu số, xử lý $M_{valid}=0$) | **PASS** | [`core/statistics.py:dp02_class_instance_share`](file:///d:/buildphase/build-phase-team-46/core/statistics.py#L129); `test_profiling.py:test_07, test_09`; `test_regression_b.py:test_06` |
| **REQ-DP03** | Class Image Prevalence (ảnh duy nhất / $N$, xử lý $N=0$) | **PASS** | [`core/statistics.py:dp03_class_image_prevalence`](file:///d:/buildphase/build-phase-team-46/core/statistics.py#L182); `test_regression_b.py:test_01, test_06, test_09` |
| **REQ-DP04** | Attribute Distribution (tỷ lệ trên $N$ & trên known, 4 trạng thái) | **PASS** | [`core/statistics.py:dp04_attribute_distribution`](file:///d:/buildphase/build-phase-team-46/core/statistics.py#L318); `test_regression_b.py:test_04, test_06` |
| **REQ-DQ02** | Metadata Missing Rate (ảnh thiếu trường $f / N$) | **PASS** | [`core/statistics.py:dq02_metadata_missing_rate`](file:///d:/buildphase/build-phase-team-46/core/statistics.py#L461); `test_regression_b.py:test_04, test_06` |
| **REQ-DQ03** | Unknown Metadata Rate (ảnh có unknown ở $f / N$) | **PASS** | [`core/statistics.py:dq03_unknown_metadata_rate`](file:///d:/buildphase/build-phase-team-46/core/statistics.py#L496); `test_regression_b.py:test_04, test_06` |
| **REQ-DQ04** | Invalid Metadata Rate (ảnh ngoài schema $f / N$) | **PASS** | [`core/statistics.py:dq04_invalid_metadata_rate`](file:///d:/buildphase/build-phase-team-46/core/statistics.py#L531); `test_regression_b.py:test_04, test_06` |
| **REQ-DQ05** | Known Metadata Rate (ảnh hợp lệ $f / N$, tổng 4 trạng thái = 100%) | **PASS** | [`core/statistics.py:dq05_known_metadata_rate`](file:///d:/buildphase/build-phase-team-46/core/statistics.py#L566); `test_regression_b.py:test_04, test_06` |
| **REQ-DQ06** | Invalid BBox Rate (đếm 1 lần per box vi phạm / $M$, $M=0 \implies N/A$) | **PASS** | [`core/statistics.py:dq06_invalid_bbox_rate`](file:///d:/buildphase/build-phase-team-46/core/statistics.py#L606); `test_regression_b.py:test_03, test_06` |
| **REQ-DQ09** | Scene Tag Conflict Rate (ảnh xung đột / $N$, $N=0 \implies N/A$) | **PASS** | [`core/statistics.py:dq09_scene_tag_conflict_rate`](file:///d:/buildphase/build-phase-team-46/core/statistics.py#L644); `test_regression_b.py:test_05, test_06` |
| **REQ-COV** | Coverage Engine & Recommendation Rules (CV01–CV06, R01–R12) | **NOT_TESTED** | Chưa triển khai (nằm trong phạm vi Phase C). |

---

## 7. Những điểm chưa hoàn thành và rủi ro

1. **Chưa triển khai Coverage Engine (Phạm vi Phase C)**:
   - Các file [`core/targets.py`](file:///d:/buildphase/build-phase-team-46/core/targets.py) và cấu trúc Slice Engine (`core/coverage_config.py`, `core/slice_engine.py`, `core/coverage_metrics.py`, `core/recommendations.py`) chưa được xây dựng.
   - Các luật khuyến nghị R01, R02, R06, R11, R12 chưa hoạt động.
2. **Dữ liệu phụ trợ tùy chọn (Auxiliary tables)**:
   - Các chỉ số yêu cầu bảng nhật ký thu thập (`collection_log`), nhóm ảnh trùng lặp (`duplicate_groups`), hoặc nhật ký kiểm duyệt (`review_log`) như DQ07, DQ08, CL01–CL05, EV01–EV06 chưa có nguồn dữ liệu đầu vào trong CVAT XML. Hiện tại hệ thống phải trả về `not_available` theo đúng tài liệu.
3. **Giao diện người dùng Streamlit**:
   - [`ui/overview.py`](file:///d:/buildphase/build-phase-team-46/ui/overview.py) hiện mới chỉ hiển thị các biểu đồ cơ bản cũ; chưa gắn kết các bảng metric chất lượng dữ liệu mới `DQ02`–`DQ06`, `DQ09`.

---

## 8. Bước tiếp theo được đề xuất

- **Bước khuyến nghị duy nhất**: **Lập kế hoạch và triển khai Phase C — Bước C1: Schema cấu hình Slice và Engine đánh giá Slice (`core/coverage_config.py` và `core/slice_engine.py`)**.
- **Lý do**:
  - Toàn bộ nền tảng dữ liệu (schema, định danh khóa, phân loại metadata, bộ chỉ số cơ sở) ở Phase B đã hoàn chỉnh và được kiểm chứng 100%.
  - Bước C1 là viên gạch đầu tiên của Coverage Engine, giúp nạp cấu hình slice định dạng JSON/YAML, kiểm tra tính hợp lệ của slice filters theo allowlist, và thực thi logic lọc cấp ảnh trước, cấp đối tượng sau (đảm bảo tính điều kiện đồng thời trên cùng một đối tượng).
- **Các file sẽ bị tác động**:
  - Tạo mới: `core/coverage_config.py`
  - Tạo mới: `core/slice_engine.py`
  - Tạo mới: `tests/test_coverage_config.py`
  - Tạo mới: `tests/test_slice_engine.py`
- **Tiêu chí nghiệm thu (Acceptance Criteria) cần đạt**:
  1. Từ chối cấu hình có slice ID trùng, `target_count <= 0`, hoặc `weight <= 0`.
  2. Báo lỗi rõ ràng khi gặp filter không nằm trong allowlist; tuyệt đối không dùng `eval`.
  3. Image slice chỉ đếm số `image_key` duy nhất; Object slice chỉ đếm số `object_key` duy nhất.
  4. Nếu image slice yêu cầu cả class và size (ví dụ: người nhỏ), phải có cùng một object thỏa mãn cả hai điều kiện, không ghép từ hai object khác nhau.
  5. 100% test mới và 114 test hiện tại đều PASS.
