# Hướng dẫn tạo tag scene_info cho toàn ảnh trong CVAT

Mục tiêu: mỗi ảnh/frame có một tag `scene_info` với hai thuộc tính `timeofday` (thời điểm) và `weather` (thời tiết), phục vụ dashboard N2-05B. Tag không cần bbox và tồn tại độc lập với nhãn vật thể như `GreenSM`.

Hướng dẫn minh họa bằng ba ảnh của task **Day 15**, Task #38, Job #54. Mã ID trong ảnh là ID của task đó, không sao chép sang task khác.

## 1. Mở cấu hình Labels và tab Raw

1. Mở task cần bổ sung thông tin.
2. Trong khu vực Labels, mở chế độ chỉnh sửa và chọn **Raw** như hình.
3. Nếu task thuộc project và nhãn được quản lý ở project, thực hiện chỉnh sửa Labels tại project.
4. Sao lưu nội dung Raw hiện tại và export annotation trước khi sửa task đã có nhãn.

![Tab Raw tại task Day 15](images/01_raw.png)

**Hình 1:** Raw hiển thị label `scene_info` cùng ID đã được CVAT cấp. Trong ảnh, `scene_info` đã tồn tại; không thêm một label cùng tên lần nữa.

## 2. Thêm cấu hình bằng mã Raw

### Trường hợp chưa có scene_info

Chèn object dưới đây vào mảng labels hiện tại, trước dấu `]` cuối. Thêm dấu phẩy sau object trước đó nếu cần. Giữ nguyên mọi label vật thể và ID đang có.

```json
{
  "name": "scene_info",
  "color": "#6daA9d",
  "type": "tag",
  "attributes": [
    {
      "name": "timeofday",
      "mutable": false,
      "input_type": "select",
      "default_value": "unknown",
      "values": ["unknown", "day", "night", "dawn_dusk"]
    },
    {
      "name": "weather",
      "mutable": false,
      "input_type": "select",
      "default_value": "unknown",
      "values": ["unknown", "clear", "rain", "fog", "overcast"]
    }
  ]
}
```

Đây là **một object**, không phải toàn bộ mảng labels. Chỉ khi danh sách labels trống, bao đoạn trên trong `[` và `]`. JSON không cho phép comment hoặc dấu phẩy sau phần tử cuối.

### Trường hợp đã có scene_info như hình

- Không thêm lại label và không thay toàn bộ Raw.
- Giữ nguyên `id` của label `scene_info` (ảnh minh họa có `id: 138`, nhưng task khác có ID khác).
- Kiểm tra `type` là `tag` và hai thuộc tính đã có chưa.
- Nếu thuộc tính đã tồn tại, giữ nguyên ID thuộc tính và các trường đang có; dùng Constructor để kiểm tra/chỉnh sửa sẽ dễ hơn.
- Nếu chưa có thuộc tính, bổ sung hai object thuộc tính từ đoạn mã trên vào `attributes` của label hiện tại.
- Không xóa ID của label hoặc thuộc tính hiện có; việc thay schema có thể ảnh hưởng annotation đã gán.

Nhấn **Save** để lưu cấu hình khi có thay đổi hợp lệ. Nút Save màu xám không tự chứng minh JSON sai; có thể chưa có thay đổi hoặc cần xem thông báo giao diện.

## 3. Kiểm tra bằng Constructor

Chuyển sang **Constructor**. Bạn cần thấy cả label vật thể ban đầu và `scene_info`.

![Constructor hiển thị GreenSM và scene_info](images/02_constructor.png)

**Hình 2:** `GreenSM` vẫn được giữ lại; `scene_info` xuất hiện riêng. Nhấn biểu tượng bút chì của `scene_info`, xác nhận loại Tag và hai thuộc tính Select.

| Thuộc tính | Giá trị | Ý nghĩa |
|---|---|---|
| timeofday | day | Ban ngày |
| timeofday | night | Ban đêm |
| timeofday | dawn_dusk | Bình minh/hoàng hôn, ánh sáng chuyển tiếp |
| timeofday | unknown | Không xác định được thời điểm |
| weather | clear | Trời quang, không thấy mưa/sương hay mây phủ rõ |
| weather | rain | Có bằng chứng đang mưa |
| weather | fog | Có bằng chứng sương mù |
| weather | overcast | Trời nhiều mây/mây phủ |
| weather | unknown | Không xác định được thời tiết |

Mặc định `unknown` tránh tự gán day/clear cho ảnh chưa kiểm tra. Tuy nhiên, nhóm vẫn phải rà soát từng ảnh: mặc định unknown không phải bằng chứng ảnh đã được xem.

## 4. Tạo tag trong Job

1. Mở Job, ví dụ **Job #54** trong ảnh.
2. Chuyển đến ảnh/frame cần gán.
3. Trong giao diện này, giữ chế độ **Standard** và chọn biểu tượng hình thẻ ở thanh công cụ trái, tooltip **Create a tag**.
4. Chọn label `scene_info` và xác nhận tạo tag theo hộp thoại/menu xuất hiện.
5. Kiểm tra bảng Objects bên phải có một mục **TAG scene_info**.

![Công cụ Create a tag và tag scene_info trong Objects](images/03_create_tag.png)

**Hình 3:** bên trái là công cụ Create a tag; góc trên trái ảnh có nhãn scene_info; bên phải là mục TAG scene_info. Tag đã được tạo cho frame hiện tại.

Một cách khác ở phiên bản có hỗ trợ: chọn **Tag annotation** trong menu chế độ phía trên, chọn label và nhấn `+`. Ưu tiên công cụ Create a tag như ảnh của nhóm.

## 5. Điền thời điểm và thời tiết

1. Trong Objects, chọn tag `scene_info`.
2. Mở **DETAILS** bằng mũi tên trên thẻ tag như hình 3.
3. Tìm hai trường `timeofday` và `weather`, chọn giá trị thích hợp.
4. Nếu không thấy trường, kiểm tra cấu hình thuộc tính ở Constructor rồi lưu và mở lại Job sau khi đã lưu annotation.
5. Nhấn **Save** ở góc trên trái.

Ví dụ minh họa: cảnh ngoài trời sáng có thể chọn `timeofday = day`. Bầu trời trong hình có thể phù hợp `overcast`, nhưng cần xem ảnh gốc và áp dụng guideline chung; không suy thời tiết chỉ từ độ sáng.

**Ảnh 3 chưa mở DETAILS, nên chưa chứng minh hai giá trị đã được điền.** Tạo tag và chọn thuộc tính là hai bước riêng.

## 6. Lặp lại cho toàn bộ ảnh

- Mỗi ảnh/frame gán đúng **một** scene_info theo quy ước nhóm.
- Tag ở frame hiện tại không tự chứng minh các frame còn lại đã có tag.
- Frame nào đã có tag thì chỉnh thuộc tính, không tạo bản sao.
- Lưu thường xuyên; kiểm tra lại vài frame sau khi mở lại Job.
- Nếu dùng Tag annotation, tắt tự chuyển frame trong lúc cần điền cả hai thuộc tính.

Quy tắc quan sát:

- Ảnh tối không chắc là ban đêm: có thể là đường hầm hoặc thiếu sáng.
- Đường ướt không đủ chứng minh đang mưa.
- Bầu trời không nhìn thấy thì có thể phải chọn unknown.
- Không xác định được chọn unknown; không đoán cho đủ dữ liệu.
- Nhóm dùng một bộ tên giá trị thống nhất, không trộn day/Day/ban_ngay.

## 7. Export và kiểm tra

1. Lưu annotation.
2. Export annotation theo định dạng **CVAT for images**.
3. Giải nén và mở XML.
4. Tìm `scene_info` trong phần annotation của ảnh, không chỉ phần khai báo labels.

Ví dụ cấu trúc mong đợi (minh họa, không phải dữ liệu trích từ ảnh):

```xml
<image id="0" name="frame_001.jpg" width="1920" height="1080">
  <tag label="scene_info" source="manual">
    <attribute name="timeofday">day</attribute>
    <attribute name="weather">overcast</attribute>
  </tag>
</image>
```

Dashboard đọc tag theo từng ảnh để thống kê thời điểm/thời tiết. Nhãn scene_info là metadata, không tính vào số bbox hoặc class vật thể.

## 8. Checklist bàn giao

- [ ] Giữ nguyên các label và annotation vật thể cũ.
- [ ] scene_info có type tag, không phải rectangle.
- [ ] Hai thuộc tính là Select, đúng tên và đúng bộ giá trị.
- [ ] Mỗi ảnh có một tag scene_info.
- [ ] Hai giá trị được kiểm tra và annotation được Save.
- [ ] XML chứa tag/attributes trong các image tương ứng.
- [ ] Dashboard phân biệt thiếu tag và unknown.

## 9. Lỗi thường gặp

| Hiện tượng | Kiểm tra và xử lý |
|---|---|
| JSON không lưu được | Dấu phẩy, ngoặc, chuỗi có ngoặc kép; xem thông báo lỗi |
| Không thấy scene_info trong Job | Cấu hình đã lưu chưa, đúng task/project chưa; mở lại Job sau khi lưu |
| Không có timeofday/weather | Mở DETAILS; kiểm tra attributes ở Constructor |
| Hai tag scene_info trên một ảnh | Giữ một tag đúng, xóa bản trùng rồi Save |
| Export không có giá trị | Kiểm tra đã tạo tag, điền thuộc tính, Save và chọn đúng định dạng |
| Labels có scene_info nhưng ảnh không có | Mới khai báo label, chưa gán tag cho từng ảnh |

## 10. Tài liệu tham khảo

- [CVAT: Annotation with tags](https://docs.cvat.ai/docs/manual/advanced/annotation-with-tags/)
- [CVAT: Tasks và cấu hình labels/attributes](https://docs.cvat.ai/docs/workspace/tasks-page/)
- [CVAT for images: cấu trúc export](https://docs.cvat.ai/docs/dataset_management/formats/format-cvat/)

## Cách chia sẻ tài liệu

Giữ file Markdown và thư mục `images` cạnh nhau. Khi gửi cho team, gửi gói ZIP kèm theo và giải nén trước khi mở Markdown trong VS Code hoặc trình đọc Markdown, để các ảnh minh họa hiển thị đúng.
