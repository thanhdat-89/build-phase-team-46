# N2-05B - Dashboard phân bố class và thuộc tính dữ liệu
### Nguyen Thanh Dat - 2A202602151

#### Công việc đã hoàn thành

- Phân tích và lựa chọn đề tài N2-05B: Dashboard phân bố class và thuộc tính dữ liệu, định hướng công cụ dùng chung cho nhiều team annotation.
- Xác định pain point, đối tượng sử dụng, mục tiêu và phạm vi phiên bản đầu của dự án.
- Xây dựng pipeline: upload file CVAT → kiểm tra đầu vào → đọc và chuẩn hóa nhãn → thống kê → hiển thị dashboard → xuất báo cáo.
- Hoàn thiện kế hoạch triển khai 3 tuần và đề xuất phân công nhiệm vụ cho nhóm 5 người; đóng gói kế hoạch thành PDF.
- Xây dựng tài liệu giải pháp kỹ thuật bằng Markdown: kiến trúc Python–Streamlit–Pandas–Plotly, cấu trúc dữ liệu Images/Objects, các module xử lý, bộ lọc và phương án kiểm thử.
- Đề xuất cơ chế bổ sung metadata thời điểm và thời tiết bằng tags CVAT hoặc CSV, phân biệt dữ liệu thiếu với giá trị unknown.
- Thực hiện tạo label scene_info và thử gán tag cho toàn ảnh trên CVAT; chuẩn bị cấu hình Raw cho hai thuộc tính timeofday và weather.
- Biên soạn hướng dẫn tạo và sử dụng tag scene_info bằng Markdown, kèm mã Raw, ba ảnh minh họa và hướng dẫn kiểm tra dữ liệu khi export.
### Nguyen Van Tien

#### Công việc đã hoàn thành

**1. Thiết lập môi trường và cấu trúc project**
- Thiết lập môi trường Python cho project bằng virtual environment (`.venv`).
- Kiểm tra môi trường Python và Git.
- Khởi tạo cấu trúc project theo thiết kế kỹ thuật:
  - `core/`
  - `parsers/`
  - `ui/`
  - `tests/`
  - `app.py`
  - `requirements.txt`
  - `README.md`
- Tạo `.gitignore` cho environment, cache, log và các file không cần thiết.
- Cài đặt và kiểm tra các thư viện:
  - Streamlit
  - Pandas
  - Plotly
  - defusedxml
  - pytest

**2. Xây dựng schema dữ liệu**
- Xây dựng `ImageRecord` và `ObjectRecord` trong `core/schema.py`.
- Chuẩn hóa thông tin image và object theo schema của project.
- Hỗ trợ metadata `timeofday`, `weather`, `metadata_source`.
- Hỗ trợ thông tin bounding box, `occluded` và `attributes`.

**3. Xây dựng tầng thống kê**
- Implement các thống kê cơ bản trong `core/statistics.py`:
  - Tổng số image.
  - Tổng số object.
  - Tổng số class.
  - Số image có annotation / không có annotation.
  - Phân bố class theo object count và image count.
  - Phân bố `timeofday`.
  - Phân bố `weather`.
- Phân biệt `unknown` và `missing`.
- Xử lý trường hợp dataset rỗng và tránh lỗi chia cho 0.
- Viết và chạy unit tests cho statistics.

**4. Xây dựng CVAT Images XML/ZIP parser**
- Implement parser `parsers/cvat_images.py`.
- Hỗ trợ input CVAT Images ZIP chứa `annotations.xml`.
- Đọc XML trực tiếp từ ZIP bằng `defusedxml`.
- Parse:
  - Image information.
  - Bounding box.
  - Class name.
  - `occluded`.
  - `scene_info`.
  - `timeofday`.
  - `weather`.
- Tạo `object_id` deterministic khi XML không có object ID.
- Hỗ trợ image không có bounding box.
- Ghi nhận và bỏ qua các shape chưa được hỗ trợ thay vì xử lý sai.
- Bổ sung validation và các exception cho ZIP/XML không hợp lệ.

**5. Kiểm thử parser với dataset thực tế**
- Kiểm tra dataset CVAT thực tế:
  - 42 images.
  - 47 bounding boxes.
  - 1 class: `GreenSM`.
  - 38 images có object.
  - 4 images không có object.
  - 39 images `day`, 3 images `night`.
  - 39 images `clear`, 3 images `rain`.
  - Kích thước image: 640x640.
- Xác nhận `scene_info` không bị tính nhầm thành object.
- Xác nhận bounding box và object ID được parse đúng.
- Tổng cộng **59 tests passed** cho parser và statistics.

**6. Xây dựng Streamlit demo**
- Implement luồng upload dataset ZIP trong `ui/upload.py`.
- Dataset được xử lý trong session và file ZIP tạm được xóa sau khi parse.
- Kết nối parser với Streamlit app.
- Implement trang overview trong `ui/overview.py`.
- Hiển thị:
  - Tổng số images.
  - Tổng số objects.
  - Tổng số classes.
  - Annotated / unannotated images.
  - Phân bố class.
  - Phân bố time of day.
  - Phân bố weather.
  - Phân bố class theo object count và image count.
- Sử dụng Plotly để trực quan hóa các thống kê.

**7. Docker hóa ứng dụng**
- Tạo `Dockerfile` phục vụ deployment.
- Sử dụng `python:3.11-slim`.
- Cài đặt dependencies từ `requirements.txt`.
- Cấu hình Streamlit chạy ở:
  - `0.0.0.0`
  - Port lấy từ biến môi trường `PORT`.
  - Headless mode.
- Không hard-code port production.

**8. Deploy demo lên Render Free**
- Push Dockerfile lên branch `NguyenVanTien`.
- Commit deployment:
  - `1e9c9bf chore: add Dockerfile for Render deployment`
- Tạo Render Web Service từ GitHub repository.
- Sử dụng Docker runtime.
- Deploy từ branch `NguyenVanTien`.
- Sử dụng Render Free instance.
- Deployment hoàn tất thành công.
- Trạng thái service: **Deploy succeeded | Live**.
- Demo hiện có thể truy cập online để team kiểm thử.

#### Kết quả đạt được

- Hoàn thành vertical slice đầu tiên từ:
  `CVAT ZIP → Parser → Normalized data → Statistics → Streamlit Dashboard → Docker → Render`.
- Parser và statistics đã được kiểm thử với test fixtures và dataset CVAT thực tế.
- Demo đã được deploy thành công trên Render Free để phục vụ kiểm thử và review trong team.