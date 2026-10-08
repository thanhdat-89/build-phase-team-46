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

### Nguyen Van Tien - 2A202602056

#### Công việc đã hoàn thành

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
- Tạo file `.gitignore` để loại bỏ các file môi trường, cache, log và các file không cần thiết khỏi Git.
- Khai báo và cài đặt các thư viện cần thiết cho project:
  - Streamlit
  - Pandas
  - Plotly
  - defusedxml
  - pytest
- Kiểm tra và xác nhận các thư viện đã được cài đặt thành công.
