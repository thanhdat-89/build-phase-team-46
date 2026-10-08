# N2-05B — Đề xuất nâng cấp Data Distribution Review & Suggestion

## 1. Mục tiêu

Bản demo hiện tại cho phép Data Lead upload dataset CVAT và nhanh chóng xem
phân bố dữ liệu thông qua dashboard.

Pipeline hiện tại:

CVAT XML/ZIP
→ Parse
→ Validation
→ Data Profiling
→ Streamlit Dashboard

Dashboard hiện đã thống kê các thông tin chính:
- Tổng số image/object/class
- Class distribution
- Class-image distribution
- Time of Day
- Weather

### Mục tiêu nâng cấp

Mở rộng từ:

> "Dataset đang phân bố như thế nào?"

thành:

> "Phân bố hiện tại có dấu hiệu lệch hoặc đáng chú ý không,
> và Data Lead nên kiểm tra gì?"

Tính năng này nhằm hỗ trợ Data Lead khoanh vùng dữ liệu cần review,
không tự động kết luận annotation là đúng hoặc sai.

---

## 2. Phạm vi

Tập trung vào 5 nhóm phân bố:

1. Class
2. Bounding box size
3. Occlusion
4. Weather
5. Time of Day

Không nằm trong phạm vi của tính năng này:
- Coverage
- Recommendation Engine tổng quát
- Database
- Backend/API
- Authentication
- Tự động sửa annotation
- Tự động kết luận dataset lỗi

---

## 3. Pipeline đề xuất

CVAT Dataset
    ↓
Parse
    ↓
Validation
    ↓
Data Profiling
    ↓
Distribution Metrics
    ↓
Distribution Rules
    ↓
Review Signals
    ↓
Dashboard
    ↓
Data Lead Review

---

## 4. Distribution Metrics

### 4.1 Class distribution

Tính:

- class_object_count
- class_object_ratio
- class_image_count
- class_image_ratio
- min/max class ratio
- dominant class
- rare class

Ví dụ:

| Class | Object | Ratio |
|---|---:|---:|
| Car | 820 | 82% |
| Truck | 120 | 12% |
| Bus | 40 | 4% |
| Motorcycle | 20 | 2% |

Metric chỉ mô tả phân bố.
Không tự động kết luận class có tỷ lệ thấp là lỗi.

---

### 4.2 Bounding box size distribution

Từ bbox hợp lệ tính:

- bbox_width
- bbox_height
- bbox_area
- area_ratio

Descriptive statistics:

- min
- P25
- median
- P75
- max

Có thể phân nhóm kích thước để Data Lead dễ quan sát.

Ví dụ:

| Area ratio | Image/Object count | Ratio |
|---|---:|---:|
| 0–1% | ... | ... |
| 1–5% | ... | ... |
| 5–15% | ... | ... |
| 15–30% | ... | ... |
| >30% | ... | ... |

Lưu ý:
bbox nhỏ không được tự động diễn giải là object ở xa.

---

### 4.3 Occlusion distribution

Tính:

- occluded_count
- non_occluded_count
- occlusion_rate
- occlusion_rate_by_class

Ví dụ:

Car:
- occluded: 30%
- non-occluded: 70%

Kết quả là distribution signal,
không phải kết luận annotation sai.

---

### 4.4 Weather distribution

Tính:

- image count
- image ratio
- distribution theo weather

Các nhóm:

- clear
- rain
- fog
- overcast
- unknown
- missing

Ví dụ:

clear = 92.9%
rain = 7.1%

Dashboard có thể tạo review signal nếu rule/reference cho phép.

---

### 4.5 Time of Day distribution

Tính:

- image count
- image ratio
- distribution

Các nhóm:

- day
- night
- dawn_dusk
- unknown
- missing

Ví dụ:

day = 92.9%
night = 7.1%

---

## 5. Distribution Rule

### Nguyên tắc

Không hard-code threshold trực tiếp trong statistics.py.

Tách thành:

statistics
→ tính metric

rules/config
→ đánh giá metric

suggestions
→ chuyển kết quả thành review suggestion

Ví dụ:

class_object_ratio = 0.03

statistics.py:
    trả về ratio = 0.03

rules:
    đánh giá ratio theo cấu hình

suggestions:
    tạo review signal tương ứng

---

## 6. Review Signal

Review signal có 3 mức:

- Normal
- Review
- Strong Review

Không sử dụng các từ:
- Error
- Wrong annotation
- Incorrect dataset

vì distribution anomaly không đồng nghĩa annotation error.

Ví dụ:

### Review

> Rain chiếm 7.1% số image.
> Data Lead nên kiểm tra mức độ đại diện của điều kiện mưa
> nếu scenario yêu cầu.

### Strong Review

> Một class có tỷ lệ rất thấp so với reference/configuration.
> Nên ưu tiên kiểm tra các image thuộc class này.

---

## 7. Reference / Baseline

Một distribution chỉ có thể được gọi là "lệch"
một cách có cơ sở khi có baseline/reference hoặc rule đã được thống nhất.

Ví dụ:

Current:
night = 7%

Reference:
night = 30%

Difference:
-23 percentage points

→ Review signal

Không được mặc định:

> night < 10% = thiếu

nếu chưa có cơ sở cho threshold này.

### Reference cần có

- reference_id
- reference_version
- source
- reason

---

## 8. Review Suggestion

Suggestion phải giúp Data Lead biết:

1. Phân bố nào đang đáng chú ý?
2. Độ lệch nằm ở đâu?
3. Nhóm dữ liệu nào cần kiểm tra?
4. Vì sao hệ thống đưa ra signal?

Ví dụ:

> 🟡 Review — Weather: Rain
>
> Rain chiếm 7.1% dataset, thấp hơn reference 20%.
> Nên kiểm tra mức độ đại diện của các scenario mưa.

---

## 9. Dashboard đề xuất

Dashboard hiện tại:

Dataset Summary
Class Distribution
Time of Day
Weather

Nâng cấp thêm:

### Distribution Review

| Dimension | Category | Current | Reference | Delta | Status |
|---|---|---:|---:|---:|---|
| Class | Motorcycle | 2% | 10% | -8pp | Review |
| Weather | Rain | 7% | 20% | -13pp | Review |
| Time | Night | 7% | 25% | -18pp | Strong Review |

Bên dưới:

### Review Suggestions

- 🟡 Rain đang có tỷ lệ thấp...
- 🟡 Night đang có tỷ lệ thấp...
- 🔴 Motorcycle có dấu hiệu thiếu đại diện...

---

## 10. KPI

Tính năng cần hướng tới hai chỉ số trong yêu cầu project:

### KPI 1 — Detection

Số class/thuộc tính có dấu hiệu lệch được phát hiện.

Ví dụ:

- Class: 2
- Weather: 1
- Time of Day: 1

Tổng review signals: 4

Không tính mọi category là anomaly.

### KPI 2 — Time Saved

So sánh thời gian trả lời một câu hỏi thống kê:

Manual:
- export dữ liệu
- filter
- group
- count
- tính ratio

Dashboard:
- upload dataset
- xem metric/suggestion

Mục tiêu là giảm thời gian trả lời câu hỏi thống kê.

---

## 11. Ví dụ câu hỏi Data Lead

Dashboard cần hỗ trợ nhanh các câu hỏi như:

- Dataset có những class nào và tỷ lệ từng class?
- Class nào chiếm tỷ lệ thấp?
- Một class xuất hiện trong bao nhiêu image?
- Bbox đang tập trung ở kích thước nào?
- Tỷ lệ object bị occlusion là bao nhiêu?
- Dataset có đủ dữ liệu rain/fog/night không?
- Phân bố hiện tại lệch bao nhiêu so với baseline?

---

## 12. Các điểm cần nhóm review trước khi code

### Question 1
Nhóm nào được coi là "lệch"?

Class?
BBox?
Occlusion?
Weather?
Time?

### Question 2
Threshold lấy từ đâu?

- Business rule?
- Scenario requirement?
- Reference dataset?
- Historical dataset?

### Question 3
Nếu không có reference thì dashboard chỉ nên:
- thống kê
- hay vẫn đưa review signal dựa trên rule?

### Question 4
Review signal cần hiển thị đến mức:
- dataset level
- category level
- hay image level?

### Question 5
Data Lead cần click từ signal về:
- category
- image ID
- hay danh sách image cần review trên CVAT?

---

## 13. Nguyên tắc triển khai

Sau khi nhóm thống nhất requirement:

1. Chốt metric
2. Chốt definition
3. Chốt threshold/reference
4. Chốt status
5. Chốt suggestion text
6. Viết test
7. Implement
8. Tích hợp dashboard
9. Test với dataset thật

Không implement threshold trước khi nhóm thống nhất definition.

---

## 14. Expected outcome

Sau nâng cấp, dashboard không chỉ trả lời:

> "Dataset đang phân bố như thế nào?"

mà có thể hỗ trợ:

> "Phân bố nào đang đáng chú ý,
> mức độ lệch là bao nhiêu,
> và Data Lead nên kiểm tra phần nào?"