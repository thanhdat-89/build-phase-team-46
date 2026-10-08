# Cơ sở lý thuyết: Data Quality & Coverage

## Bộ chỉ số đo lường cho N2-05B - CVAT Data Profiling & Anomaly Detection

- Phiên bản: 1.0 - 08/10/2026.
- Đối tượng: Data Label Lead, Data Lead, reviewer và nhóm phát triển.
- Đầu vào MVP: CVAT for Images 1.1 XML, bbox 2D, tags; CSV metadata bổ sung nếu cần.
- Mục đích: mô tả dữ liệu, đánh giá độ đầy đủ và độ bao phủ, phát hiện dấu hiệu bất thường để ưu tiên review trên CVAT.

> Công cụ hỗ trợ phát hiện vấn đề và ưu tiên kiểm tra. Phân bố khác biệt không tự chứng minh nhãn sai; coverage đạt mục tiêu không tự chứng minh model tốt.

## 1. Pain point và quyết định cần hỗ trợ

| Pain point | Quyết định | Chỉ số liên quan |
|---|---|---|
| Thiếu cái nhìn toàn bộ dataset | Dataset hiện có gì? | Inventory, class distribution |
| Không đủ ngân sách review tất cả | Kiểm tra vùng nào trước? | Alert precision, review yield, Recall@Budget |
| Thiếu tình huống quan trọng | Thu thập thêm gì? | Slice support, coverage, gap |
| Metadata thiếu/không thống nhất | Có thể tin thống kê không? | Missing, unknown, schema validity |
| Nhiều frame nhưng ít cảnh độc lập | Số lượng có phản ánh độ đa dạng? | Source diversity, redundancy |
| Phân bố thay đổi giữa các batch | Do dữ liệu mới hay lỗi nhãn? | Distribution difference, drift |
| Thiếu bằng chứng bàn giao | Batch đạt điều kiện nào? | Quality gates và báo cáo phiên bản |

## 2. Cơ sở lý thuyết

### 2.1. Chất lượng phụ thuộc mục đích sử dụng

NIST AI RMF nhấn mạnh đánh giá tính đại diện và rủi ro trong bối cảnh sử dụng, dùng đánh giá phân tách theo nhóm và đặt ngưỡng phù hợp miền [1]. Vì vậy, dữ liệu cân bằng class không mặc nhiên tốt hơn dữ liệu phản ánh tần suất thực tế. Kế hoạch huấn luyện có thể chủ động lấy nhiều ca hiếm, trong khi bộ đánh giá cần có mục tiêu lấy mẫu riêng.

Khung áp dụng trong tài liệu kết hợp: validity, completeness, consistency, accuracy, uniqueness, representativeness và traceability. Đây là khung vận dụng cho N2-05B, không phải một tiêu chuẩn được chứng nhận.

### 2.2. Documentation và provenance

Datasheets for Datasets đề xuất mô tả động cơ, thành phần, quy trình thu thập và cách sử dụng dataset [2]. Dashboard cần kèm nguồn, phiên bản, phạm vi hỗ trợ và các giới hạn để Lead diễn giải số liệu đúng.

### 2.3. Coverage theo tổ hợp thuộc tính

Nghiên cứu coverage phân tích các vùng có ít mẫu theo tổ hợp thuộc tính, thay vì chỉ xem từng biến riêng [3]. Ví dụ có nhiều ảnh đêm và nhiều người đi bộ nhưng ít người đi bộ ban đêm.

Ứng dụng: chọn tập slice có ý nghĩa với dự án; đặt số mẫu yêu cầu cho từng slice. Không tạo mọi tổ hợp rồi coi các tổ hợp bất khả thi là khoảng thiếu.

### 2.4. Validation, drift và skew

TensorFlow Data Validation kiểm tra dữ liệu theo schema, so sánh phân bố giữa đợt dữ liệu và giữa training/serving [4,5]. N2-05B vận dụng phương pháp, không bắt buộc sử dụng thư viện TFDV.

- Schema violation: vi phạm quy tắc cấu trúc hoặc giá trị.
- Coverage gap: chưa đạt kế hoạch thu thập.
- Distribution shift: khác tham chiếu; thay đổi theo thời gian có thể gọi là drift.
- Suspected annotation issue: dấu hiệu cần người review nội dung.

### 2.5. Lấy mẫu và độ bất định

Tỷ lệ lỗi trên mẫu review cần cách chọn mẫu phù hợp và khoảng tin cậy, ví dụ Wilson [6]. Frame liên tiếp không độc lập: khi suy rộng, lấy mẫu theo scene/video hoặc tính độ bất định theo cụm. Thống kê toàn bộ file là mô tả dataset hiện tại; không cần khoảng tin cậy chỉ để đếm chính dataset đó.

Data Cascades mô tả vấn đề dữ liệu tích lũy và gây tác động downstream [7], củng cố vai trò kiểm tra trước bàn giao. Không chuyển kết quả nghiên cứu thành tỷ lệ lỗi giả định cho dataset của nhóm.

## 3. Quy ước dữ liệu và mẫu số

### 3.1. Đơn vị

- `N`: số ảnh duy nhất trong dataset đã import, gồm ảnh không có bbox.
- `M`: số bbox đã parse, gồm bbox không hợp lệ được giữ để báo lỗi.
- `M_valid`: bbox hợp lệ theo các quy tắc hình học đã cấu hình.
- `image_key`: dataset_id + image_id; giữ image_path để truy xuất.
- `object_key`: dataset_id + object_id, hoặc ID nội bộ do parser tạo có tính ổn định.
- Một bbox trên một frame là một instance annotation, không mặc nhiên là một vật thể vật lý duy nhất qua video.

### 3.2. Metadata

Phân biệt:

1. `known`: có giá trị hợp lệ và xác định.
2. `unknown`: giá trị unknown được ghi rõ.
3. `missing`: không có trường, null hoặc chuỗi rỗng.
4. `invalid`: có giá trị nhưng không thuộc schema.

Mặc định unknown không chứng minh ảnh đã được review. Nếu đo tiến độ, bổ sung `review_status` riêng. `scene_info` là tag metadata, không tính vào class vật thể.

Đối với mỗi trường, bốn nhóm trạng thái phải loại trừ nhau và tổng bằng N. Nhiều tag scene_info xung đột phải được báo; không âm thầm chọn một giá trị.

### 3.3. Chính sách lọc

- Bộ lọc cấp ảnh chọn ảnh trước, rồi lấy bbox trong các ảnh đó.
- Khi lọc class, ghi rõ đang đếm tất cả ảnh hay chỉ ảnh chứa class.
- Ảnh không bbox gọi là “ảnh không có nhãn vật thể”; chỉ gọi background nếu đã được xác nhận.
- Mọi tỷ lệ công bố numerator, denominator, đơn vị và số bản ghi bị loại.

## 4. Data Quality: bộ chỉ số

| ID | Chỉ số | Định nghĩa/công thức | Điều kiện và diễn giải |
|---|---|---|---|
| DQ01 | Schema Validity Rate | bản ghi vượt tất cả quy tắc áp dụng / bản ghi kiểm tra | Tính riêng Images, Objects, Tags; không gộp mẫu số khác loại |
| DQ02 | Metadata Missing Rate(f) | ảnh thiếu trường f / N | f có thể là weather, timeofday |
| DQ03 | Unknown Rate(f) | ảnh có unknown ở f / N | Tách với missing và invalid |
| DQ04 | Invalid Metadata Rate(f) | ảnh có giá trị ngoài schema / N | Giữ giá trị gốc để review |
| DQ05 | Known Metadata Rate(f) | ảnh có giá trị hợp lệ, xác định / N | Bốn trạng thái tổng bằng 100% |
| DQ06 | BBox Invalid Rate | bbox vi phạm ít nhất một quy tắc hình học / M | Một bbox lỗi nhiều quy tắc chỉ đếm một lần trong tỷ lệ tổng |
| DQ07 | Duplicate Record Rate | (số bản ghi - số bản ghi duy nhất theo khóa/quy tắc) / số bản ghi | Công bố khóa; tọa độ giống nhau chỉ là nghi trùng nếu chưa xác nhận |
| DQ08 | Audited Error Rate | đơn vị xác nhận lỗi / đơn vị review | Tách ảnh và object; cần reviewer/reference |
| DQ09 | Scene Tag Conflict Rate | ảnh có scene_info xung đột / N | Tag dư giống hệt và tag xung đột báo riêng |

Nếu mẫu số bằng 0: hiển thị N/A, không hiển thị 0%. BBox validity gồm số hữu hạn, x_max > x_min, y_max > y_min, kích thước ảnh > 0 và tọa độ theo chính sách phạm vi. Dung sai biên phải được công bố.

Accuracy về nội dung (class đúng, box bám đối tượng, thời tiết đúng) không thể suy ra chỉ từ XML. Không dùng DQ01 thay thế DQ08.

## 5. Data Profiling: mô tả phân bố

| ID | Chỉ số | Công thức/quy tắc |
|---|---|---|
| DP01 | Inventory | N, M, M_valid, số class, số ảnh không bbox |
| DP02 | Class Instance Share(c) | bbox class c / M; công bố có gồm bbox lỗi hay không |
| DP03 | Class Image Prevalence(c) | ảnh chứa ít nhất một bbox class c / N |
| DP04 | Attribute Distribution(f,v) | ảnh giá trị v / N; kèm tỷ lệ trên known nếu cần |
| DP05 | Relative BBox Area | area_ratio = (x_max-x_min)(y_max-y_min)/(width×height), chỉ bbox hợp lệ |
| DP06 | Occlusion Rate(c) | object class c có occluded=true / object class c có giá trị occluded hợp lệ |
| DP07 | Attribute Availability | object có thông tin thuộc tính / object trong phạm vi |

Tổng DP03 giữa các class có thể vượt 100% vì ảnh chứa nhiều class. Ngưỡng small/medium/large theo area_ratio là ngưỡng nội bộ; không gọi là COCO small/medium/large nếu không dùng đúng định nghĩa benchmark đó. Bbox nhỏ không chứng minh vật thể ở xa.

## 6. Coverage: độ bao phủ

### 6.1. Định nghĩa slice

Một slice là điều kiện rõ ràng trên ảnh hoặc object. Ví dụ:

- Image slice: ảnh night + rain + có person, đếm mỗi ảnh một lần.
- Object slice: bbox person + small + ảnh night, đếm bbox.

Giữ cấp ảnh/object riêng khi tổng hợp. Danh sách S gồm các slice quan trọng đã chốt; có trọng số w_s > 0 và target_count tau_s > 0.

### 6.2. Công thức

```text
n_s = số đơn vị thuộc slice s
Gap_s = max(0, tau_s - n_s)
Attainment_s = min(n_s / tau_s, 1)
Coverage = sum(1[n_s >= tau_s]) / |S|
WeightedCoverage = sum(w_s * 1[n_s >= tau_s]) / sum(w_s)
WeightedAttainment = sum(w_s * Attainment_s) / sum(w_s)
```

| ID | Chỉ số | Mục đích |
|---|---|---|
| CV01 | Slice Support n_s | Số mẫu của tình huống |
| CV02 | Coverage đạt ngưỡng | Tỷ lệ slice đạt kế hoạch |
| CV03 | Weighted Coverage | Ưu tiên tình huống quan trọng |
| CV04 | Gap | Số đơn vị còn thiếu từng slice |
| CV05 | Attainment | Mức tiến gần target, tránh chỉ báo đạt/chưa đạt |
| CV06 | Independent Source Support | Số scene/video/camera/nguồn độc lập của slice |

**Giới hạn:** slice có thể chồng nhau; không cộng gap thành tổng ảnh cần lấy. Một ảnh có thể cải thiện nhiều slice. Nhiều ảnh liên tiếp không tương đương nhiều nguồn độc lập. Không gọi coverage là coverage ngoài thực tế khi chưa định nghĩa miền mục tiêu.

### 6.3. Quyết định đủ dữ liệu

Target_count cần lý do: yêu cầu sản phẩm, ca rủi ro, ngân sách, kinh nghiệm hoặc learning curve/evaluation. Không có quy tắc phổ quát “30/50 ảnh là đủ”. Đạt target là đạt kế hoạch, chưa phải đảm bảo độ chính xác model.

## 7. Representativeness và Anomaly Detection

### 7.1. Tham chiếu bắt buộc

Chọn: kế hoạch lấy mẫu, batch đã duyệt, hoặc dữ liệu miền triển khai. Lưu reference_id, phiên bản, nguồn và lý do. Kế hoạch lấy mẫu là chuẩn quy trình, không mặc nhiên là phân bố tự nhiên.

### 7.2. Chênh lệch phân bố

Với cùng bins/categories và cùng mẫu số:

```text
Delta_s = p_s - q_s
Delta_percentage_points = 100 * Delta_s
D_inf(P,Q) = max_s(abs(p_s-q_s))
```

D_inf cho đặc trưng phân loại được dùng trong TFDV [4,5]. Khi so sánh các vector xác suất, phải có cùng support và tổng bằng 1. Vector tỷ lệ ảnh chứa nhiều class là prevalence đa nhãn, không phải phân bố chuẩn hóa; chênh lệch từng class vẫn dùng được nhưng không áp dụng divergence như phân bố đa lớp.

MVP dùng D_inf hoặc chênh lệch từng nhóm. Các metric Jensen-Shannon/kiểm định thống kê để giai đoạn sau, với giả định và cách binning công bố rõ.

### 7.3. BBox outlier

Quy tắc IQR đề xuất theo từng class và nguồn có thể so sánh:

```text
IQR = Q3 - Q1
lower = Q1 - k * IQR
upper = Q3 + k * IQR
flag = area_ratio < lower OR area_ratio > upper
```

k=1.5 là giá trị khởi đầu để thử, không phải chuẩn chất lượng dự án. Tắt hoặc cảnh báo thiếu support nếu nhóm quá nhỏ; xử lý IQR=0 bằng chính sách riêng. Outlier có thể là ca hiếm hợp lệ, không tự sửa/xóa.

### 7.4. Quy tắc cảnh báo

| Loại | Ví dụ | Hành động |
|---|---|---|
| Vi phạm schema | class ngoài schema, bbox không hợp lệ | Kiểm tra và sửa dữ liệu |
| Thiếu metadata | thiếu timeofday | Gán bổ sung hoặc cung cấp CSV |
| Coverage gap | slice dưới target_count | Thu thập hoặc annotation bổ sung |
| Distribution shift | batch khác tham chiếu | Xem nguồn, cảnh, kế hoạch lấy mẫu và nhãn |
| Outlier | bbox rất nhỏ so với cùng class | Review nội dung ảnh |

Mỗi alert chứa rule_id, metric, observed, threshold/reference, scope, affected_image_keys, lý do, trạng thái review. Không quy kết annotator kém chỉ từ phân bố khác biệt.

## 8. Đo quy trình thu thập dữ liệu

| ID | Chỉ số | Công thức | Đầu vào bổ sung |
|---|---|---|---|
| CL01 | Acceptance Rate | mẫu đạt tiêu chí / mẫu thu thập | Log mẫu nhận/loại |
| CL02 | Useful Slice Yield | mẫu đạt tiêu chí thuộc ít nhất một slice ưu tiên / mẫu thu thập | Deduplicate numerator |
| CL03 | Coverage Gain | coverage sau - coverage trước | Cùng slice, target, trọng số |
| CL04 | Collection Efficiency | số mẫu hữu ích / giờ hoặc chi phí | Log thời gian/chi phí |
| CL05 | Redundancy Rate | mẫu dư theo quy tắc duplicate / mẫu thu thập | Hash/ảnh/embedding nếu gần trùng |

CVAT XML không đủ cho các chỉ số nguồn độc lập, ảnh gần trùng hay chi phí. Giữ các chỉ số là N/A khi thiếu đầu vào, không đoán.

## 9. Đo hiệu quả công cụ

| ID | Chỉ số | Công thức |
|---|---|---|
| EV01 | Alert Precision | alert được xác nhận đúng / alert được review |
| EV02 | Alert Recall | vấn đề phát hiện / tổng vấn đề trong bộ kiểm chứng |
| EV03 | Time Saved | 1 - T_website / T_baseline |
| EV04 | Review Yield | đơn vị có lỗi xác nhận / đơn vị review |
| EV05 | Recall@Budget | lỗi tìm được trong ngân sách / tổng lỗi bộ kiểm chứng |
| EV06 | Statistical Count Accuracy | số phép đếm khớp đáp án / số phép đếm kiểm tra |

Định nghĩa “đúng” riêng từng loại alert. Gap đúng về kế hoạch không đồng nghĩa annotation sai. EV02/EV05 cần bộ kiểm chứng được review đầy đủ hoặc có reference đáng tin. Chưa biết toàn bộ lỗi thì chưa tính recall toàn dataset.

Thí nghiệm: cùng dataset, cùng câu hỏi và ngân sách; so website với thống kê thủ công hoặc review ngẫu nhiên. Đổi thứ tự thử nghiệm/cân bằng người dùng để giảm hiệu ứng nhớ. Lưu phiên bản tool và dữ liệu.

## 10. Bộ chỉ số MVP và quality gates

### 10.1. Ưu tiên triển khai

1. DP01-DP04: inventory, class và phân bố metadata.
2. DQ02-DQ06, DQ09: thiếu/unknown/invalid và geometry/tag conflicts.
3. DP05-DP07: kích thước và che khuất.
4. CV01-CV05: support, coverage, gap và attainment.
5. D_inf và chênh lệch với tham chiếu, nếu có.
6. Alert queue với lý do và ảnh liên quan.
7. EV01, EV03, EV06 trong pilot; recall khi có bộ kiểm chứng.

### 10.2. Ví dụ cấu hình, không phải ngưỡng chuẩn

```yaml
version: 1
metadata:
  timeofday: [day, night, dawn_dusk, unknown]
  weather: [clear, rain, fog, overcast, unknown]
policies:
  missing_metadata_warning_rate: 0.05
  max_bbox_invalid_rate: 0.0
  distribution_d_inf_warning: 0.10
  unknown_is_known: false
slices:
  - id: person_night_rain
    unit: image
    filters:
      contains_class: person
      timeofday: night
      weather: rain
    target_count: 50
    weight: 3
  - id: person_night
    unit: image
    filters:
      contains_class: person
      timeofday: night
    target_count: 100
    weight: 2
```

Các con số là ví dụ khởi đầu. Lead phải duyệt và ghi lý do. Schema/geometry có thể là blocker; gap/drift thường là cảnh báo cần quyết định, không mặc nhiên chặn bàn giao.

Không gom mọi metric thành một “Data Quality Score” nếu chưa có mô hình trọng số và kiểm chứng. Báo cáo từng chiều rõ ràng để tránh một chiều tốt che lấp lỗi nghiêm trọng ở chiều khác.

## 11. Ví dụ diễn giải

Ví dụ giả định: 1.000 ảnh; 40 ảnh night; 100 ảnh thiếu timeofday; 20 ảnh unknown.

- Night trên tổng ảnh = 40/1.000 = 4%.
- Known timeofday = 880 ảnh nếu phần còn lại đều hợp lệ.
- Night trên known = 40/880 ≈ 4,55%.
- Không khẳng định 96% ảnh là day: phải tách dawn_dusk, missing, unknown.
- Slice person × night × rain có 12 ảnh, target 50: gap 38, attainment 24%.
- Hai slice nêu trong YAML chồng nhau; không cộng gap để kết luận tổng ảnh cần thu thập.
- Nếu night tăng từ 4% lên 15%: chênh 11 điểm phần trăm; kiểm tra kế hoạch thu thập trước khi gọi là lỗi.

## 12. Hợp đồng đầu ra cho lập trình

Mỗi metric trả về:

```json
{
  "metric_id": "DQ02",
  "scope": "dataset",
  "field": "timeofday",
  "unit": "image",
  "numerator": 100,
  "denominator": 1000,
  "value": 0.10,
  "status": "warning",
  "excluded_count": 0,
  "definition_version": "1.0",
  "config_version": "1",
  "reference_id": null
}
```

Nếu denominator=0 hoặc dữ liệu chưa đủ: value=null, status=not_available và reason rõ ràng. Lưu affected_image_keys trong bảng alert riêng. Link CVAT cần mapping task/job/frame xác nhận được; nếu không có, xuất tên ảnh để người dùng tra, không tạo link giả.

## 13. Checklist kiểm chứng

- [ ] Mẫu số và đơn vị xuất hiện trên biểu đồ/báo cáo.
- [ ] Tổng ảnh gồm ảnh không bbox; tag không tính thành object.
- [ ] Known/unknown/missing/invalid tổng bằng N.
- [ ] Bbox sai bị báo và không làm sai thống kê kích thước.
- [ ] Tập nhỏ được đếm độc lập bằng tay.
- [ ] Lọc kết hợp khớp đáp án.
- [ ] Các slice, trọng số và target có phiên bản.
- [ ] Mọi shift alert có tham chiếu và lý do.
- [ ] Không suy annotation accuracy chỉ từ XML.
- [ ] Thử ít nhất hai team; báo cáo giới hạn và kết quả thực tế.

## 14. Nguồn tham khảo

[1] NIST. AI RMF Playbook - Measure. Cơ sở: representativeness, contextual thresholds, disaggregated evaluation.
https://airc.nist.gov/airmf-resources/playbook/measure/

[2] Gebru, T. et al. Datasheets for Datasets. arXiv:1803.09010; CACM, 2021. Cơ sở: documentation, composition, collection process, intended use.
https://arxiv.org/abs/1803.09010

[3] Lin, Y., Guan, Y., Asudeh, A., Jagadish, H. V. Identifying Insufficient Data Coverage in Databases with Multiple Relations. PVLDB 13(11), 2229-2242, 2020. Cơ sở: coverage theo tổ hợp thuộc tính và insufficient support.
https://www.vldb.org/pvldb/vol13/p2229-lin.pdf

[4] TensorFlow. TensorFlow Data Validation guide. Cơ sở: schema validation, training-serving skew, drift và khoảng cách phân bố.
https://tensorflow.github.io/tfx/guide/tfdv/

[5] TensorFlow. Data Validation tutorial. Cơ sở: L-infinity cho categorical drift và threshold theo miền.
https://www.tensorflow.org/tfx/tutorials/data_validation/tfdv_basic

[6] NIST/SEMATECH. Confidence intervals for proportions. Cơ sở: khoảng tin cậy Wilson; áp dụng khi suy tỷ lệ từ mẫu phù hợp.
https://itl.nist.gov/div898/handbook/prc/section2/prc241.htm

[7] Sambasivan, N. et al. Everyone wants to do the model work, not the data work: Data Cascades in High-Stakes AI. CHI, 2021. Cơ sở: tác động downstream của vấn đề dữ liệu.
https://research.google/pubs/everyone-wants-to-do-the-model-work-not-the-data-work-data-cascades-in-high-stakes-ai/

Các metric, ID, công thức coverage trọng số và ngưỡng ví dụ là thiết kế vận dụng của N2-05B; không tuyên bố tất cả được quy định nguyên văn bởi các nguồn. Tài liệu và ngưỡng cần được cập nhật khi miền dữ liệu hoặc phạm vi sản phẩm thay đổi.
