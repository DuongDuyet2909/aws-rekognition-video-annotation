# Tổng quan AWS_Rekognition sau tối ưu — 17/10/2026

## Kết luận

Đã sửa trực tiếp dự án tại `.`. Phiên bản mới có pipeline nhận diện có thể tiếp tục từ cache, công cụ sửa dữ liệu cũ, xuất ảnh/video có khung nhận diện, cấu hình dữ liệu YOLO và luồng rà soát/đánh giá nhãn.

Đã sửa toàn bộ 755 file nhãn hiện có: từ 25.440 dòng xuống **12.720 dòng hợp lệ, không còn nhãn trùng**. Đã tạo 755 ảnh có khung bao và video kết quả đủ 755 frame. Toàn bộ lần sửa/kiểm tra này sử dụng dữ liệu cục bộ, **0 lời gọi API AWS mới**.

Dự án vẫn là công cụ tích hợp dịch vụ nhận diện và tạo dữ liệu gán nhãn. Nó chưa huấn luyện model YOLO, chưa theo dõi danh tính ngựa vằn và chưa có kết quả precision/recall thực tế do chưa hoàn thành rà soát nhãn chuẩn.

## Mục đích của dự án và vai trò AWS

AWS là Amazon Web Services, nền tảng điện toán đám mây của Amazon. Trong dự án, **Amazon Rekognition Image** cung cấp model nhận diện có sẵn, **Boto3** gửi/nhận yêu cầu, còn **OpenCV** đọc video và ghi ảnh/video trên máy cá nhân.

Luồng xử lý mới:

```text
Video → chọn frame theo stride → kiểm tra cache
  ├─ cache hợp lệ: tái sử dụng
  ├─ có phản hồi AWS nhưng thiếu file kết quả: dựng lại cục bộ
  └─ cần kết quả mới và còn ngân sách request:
       JPEG bytes → Rekognition DetectLabels → Zebra instances
       → lọc confidence, kiểm tra/cắt tọa độ về biên ảnh, bỏ bbox trùng
       → ghi ảnh + nhãn + metadata + phản hồi JSON
```

Các công cụ offline dùng những kết quả đã lưu để vẽ ảnh/video, xuất cấu hình YOLO và chuẩn bị mẫu kiểm tra. Code sử dụng API phân tích ảnh cho từng frame được chọn; không phải luồng Rekognition Video theo dõi bất đồng bộ. Chương trình không dùng S3 hoặc EC2 trong phiên bản này.

Mục đích học tập: xử lý video, gọi API cloud, chuyển đổi tọa độ, tạo dữ liệu gán nhãn, quản lý credential, kiểm soát request và kiểm tra chất lượng đầu ra.

## Đã sửa gì so với phiên bản trước?

| Điểm trước sửa | Trạng thái sau sửa |
|---|---|
| Mỗi bbox bị ghi hai lần | Chỉ ghi một lần; đã sửa dữ liệu cũ và sao lưu nhãn trước sửa. |
| Chỉ có ảnh gốc và TXT, chưa vẽ bbox | Có `annotated_images`, `preview.jpg` và `annotated_video.mp4`. |
| Chạy lại sẽ gọi lại AWS cho từng frame | Cache dựa trên hash video, ảnh, nhãn và cấu hình; có chế độ offline; tiếp tục phần chưa xong. |
| Mất kết quả nếu gián đoạn lúc đang ghi | Phản hồi AWS mới được ghi trước, file đầu ra ghi qua tệp tạm và thay thế; có thể dựng lại từ phản hồi đã lưu. |
| Gửi mọi frame, không có giới hạn | Mặc định stride=30, tối đa 25 lời gọi DetectLabels mới mỗi lần chạy. |
| Không xử lý lỗi dịch vụ | Timeout, standard retry tối đa 3 HTTP attempts/call; ghi lỗi theo frame, dừng khi lỗi xác thực/quyền; mã thoát báo chưa hoàn tất. |
| Chưa lọc confidence riêng từng instance | Có `--instance-confidence`; giữ mặc định 0 để tương thích dữ liệu cũ. |
| Không lưu score/phản hồi | Lưu score, nguồn, model version, cấu hình/hash và phản hồi của các request mới. Confidence cũ là null. |
| Khóa ghi trực tiếp trong source và CSV | Chuyển sang AWS shared profile; source không còn khóa; bản cũ được giữ ngoài dự án trong `.aws`. |
| Thiếu cấu hình dataset YOLO | Có thư mục labels, data.yaml, danh sách train/val, lấy mẫu theo thời gian và khoảng trống giữa hai phần. |
| Chưa có công cụ đánh giá | Có bộ mẫu rà soát và evaluator IoU/precision/recall/F1; AP/mAP khi có confidence thật. Chặn dùng mẫu chưa rà soát làm ground truth. |
| Thiếu README, requirements, tests | Đã bổ sung hướng dẫn, dependency tương thích, lệnh offline, cấu hình Terminal và 12 bài kiểm thử. |

Đổi ngưỡng confidence, region, chất lượng JPEG hoặc các cài đặt nhận diện khác yêu cầu một thư mục `--output` riêng. Nhờ đó bộ dữ liệu không bị trộn các chính sách nhận diện khác nhau trong một lần chạy dở dang.

## Kết quả kiểm tra trên dữ liệu thật

| Chỉ số | Trước | Sau |
|---|---:|---:|
| Frame video nguồn | 755 | 755 |
| Độ phân giải | 1280×720 | 1280×720 |
| FPS nguồn | Khoảng 29,97 | Giữ FPS khi dựng video |
| Thời lượng | Khoảng 25,19 giây | Khoảng 25,19 giây |
| Ảnh gốc | 755 | 755, không thay đổi |
| File annotations | 755 | 755 |
| Dòng nhãn | 25.440 | **12.720** |
| Dòng trùng | 12.720 | **0** |
| Nhãn YOLO ở output/labels | Chưa có | 755 |
| File metadata | Chưa có | 755 |
| Ảnh có khung nhận diện | Chưa có | 755 |
| Video có khung nhận diện | Chưa có | 755 frame, đọc lại được toàn bộ |
| Lời gọi AWS trong lần sửa | — | **0** |

Đã kiểm tra đọc được cả 755 ảnh gốc và 755 ảnh minh họa; không thiếu cặp ảnh/nhãn. Video đầu ra hiện dùng codec MP4V và có dung lượng khoảng 81,24 MB. Đây là video dựng lại có bbox, không phải bản nén giống video nguồn 9 MB.

**12.720 là tổng bbox trên nhiều frame, không phải số cá thể ngựa vằn.** Không suy ra số cá thể hoặc tỷ lệ nhận diện đúng từ số file và số bbox.

Đầu ra trực tiếp:

- [Video có khung nhận diện](https://github.com/DuongDuyet2909/aws-rekognition-video-annotation/releases/download/v1.0.0/annotated_video.mp4).
- [Ảnh xem trước](docs/preview.jpg).
- [Thống kê audit](reports/audit_report.json).
- [Kết quả chạy offline](reports/run_summary.json): 755/755 frame lấy từ cache, 0 API call, không lỗi.

## Thành phần mã nguồn hiện tại

| File | Vai trò |
|---|---|
| `main.py` | CLI với các lệnh repair, detect, render, audit, export-yolo, prepare-review, evaluate. Import file không tự gọi AWS. |
| `pipeline.py` | Đọc video, nhãn, cache, lưu kết quả, gọi AWS, xử lý lỗi, render và xuất YOLO. |
| `evaluation.py` | Chuẩn bị mẫu rà soát, tính IoU, ghép bbox một-một và các metric có căn cứ. |
| `tests/test_pipeline.py` | 12 bài kiểm thử bằng video ngắn tổng hợp và client AWS giả lập. |
| `requirements.txt` | Boto3/Botocore 1.43.114, OpenCV 5.0.0.93, NumPy 2.2.6. |
| `README.md` | Hướng dẫn cài, chạy, các tham số, output và giới hạn. |
| `run_offline.cmd` | Chạy xác minh cache và dựng video trong terminal, không gọi AWS. |
| `.vscode/settings.json` | Gợi ý interpreter .venv và cấu hình Code Runner dùng Terminal khi mở riêng folder dự án. |
| `.gitignore` | Loại credential, cache, video và đầu ra khỏi nội dung Git. |
| `credentials.py` | Chỉ còn thông báo hướng dẫn dùng profile, không còn giá trị khóa. |

`zebras.mp4`, ảnh gốc và nội dung bbox được giữ nguyên ngoài việc loại các dòng trùng khỏi nhãn.

## Môi trường và khóa AWS

Đã chuẩn bị môi trường riêng: `%USERPROFILE%\.aws-rekognition-venv` với Python 3.11. Kiểm tra `pip check` trả **No broken requirements found**. OpenCV 5 cần NumPy 2; không trộn môi trường này với môi trường TensorFlow của dự án Pneumonia dùng NumPy 1.

Khóa hiện có đã chuyển sang profile **aws-rekognition-tutorial** trong cơ chế shared credentials chuẩn của AWS. Các profile khác được giữ nguyên. Các file khóa cũ được chuyển vào thư mục sao lưu riêng dưới `%USERPROFILE%\.aws`, không còn trong source. Không in khóa ra terminal/báo cáo. Đã kiểm tra Boto3 đọc được profile cục bộ; **chưa gửi request thật để kiểm chứng quyền/trạng thái khóa trên AWS**.

## Cách chạy trên máy hiện tại

Trong PowerShell, chuyển tới thư mục dự án rồi chạy:

```powershell
& "$env:USERPROFILE\.aws-rekognition-venv\Scripts\python.exe" -X utf8 main.py audit
```

Chạy lại dữ liệu có sẵn và dựng video bằng một lệnh:

```powershell
.\run_offline.cmd
```

Chế độ offline có thể viết tắt thành:

```powershell
python -X utf8 main.py detect --offline --stride 1 --max-api-calls 0
python -X utf8 main.py render
```

Ở các ví dụ dùng `python`, cần kích hoạt/chọn đúng môi trường dự án hoặc thay bằng đường dẫn interpreter ở trên.

Khi chủ động muốn xử lý video mới qua AWS:

```powershell
python -X utf8 main.py detect --profile aws-rekognition-tutorial --video another_video.mp4 --output output_new --stride 30 --max-api-calls 25
```

Một lượt 755 frame ở stride=30 chọn 26 ảnh, ít hơn khoảng 96,56% ứng viên request so với gửi cả 755 ảnh. Đây là tính toán số ảnh được chọn trên dữ liệu chưa có cache, không phải số tiền tiết kiệm đã đo. Giới hạn 25 là số lời gọi DetectLabels mới ở cấp chương trình; mỗi lời gọi có thể retry tới 3 HTTP attempts. Khi hết giới hạn, lệnh báo chưa hoàn tất và có thể chạy tiếp. `--refresh` bỏ qua cache có chủ đích, vẫn chịu ngân sách này.

## Dữ liệu YOLO và rà soát thủ công

Đã xuất với `--every 5 --validation-fraction 0.2 --gap 30`:

- 151 frame được chọn theo bước 5.
- 114 ảnh train, 31 ảnh validation.
- 6 frame mẫu giữa hai phần bị loại để tạo khoảng cách 30 frame nguồn.
- Có `output/data.yaml`, `output/splits/train.txt`, `output/splits/val.txt`.
- Ảnh dùng chung thư mục gốc, không sao chép thêm toàn bộ dataset. Nhãn đặt ở output/labels tương ứng với output/images.

Đây vẫn là dữ liệu gán nhãn tự động từ cùng một video. Chia theo thời gian và để khoảng cách chỉ giảm tình trạng frame sát nhau nằm ở hai tập; **không bảo đảm độc lập theo cảnh hoặc cá thể**. Không dùng kết quả validation đó để khẳng định khả năng tổng quát sang video khác. Các đường dẫn danh sách ảnh được sinh tuyệt đối; cần chạy lại export nếu chuyển vị trí dự án.

Đã tạo `output/review/` gồm **26 ảnh và nhãn gợi ý**, lấy một ảnh mỗi 30 frame. Tất cả đang có trạng thái `pending` trong `review.csv`. Người rà soát cần sửa bbox thiếu/sai/bị đặt lệch bằng công cụ annotation hỗ trợ YOLO, rồi ghi `status=reviewed` và tên người rà soát.

```powershell
python -X utf8 main.py evaluate --ground-truth output/review --iou 0.5
```

Lệnh trên hiện sẽ từ chối chạy metric vì các mẫu chưa được xác nhận. Đây là kiểm soát đã được thử trên bộ dữ liệu thật, giúp tránh lấy chính nhãn AWS làm ground truth rồi báo accuracy sai lệch.

Sau khi có nhãn chuẩn, evaluator tính TP/FP/FN, precision, recall, F1 và IoU trung bình của các cặp ghép. Với kết quả AWS mới có score thật cho từng bbox, công cụ có thể tính AP50 và mAP50:95 bằng nội suy 101 điểm cho một lớp; không phải toàn bộ giao thức COCO với crowd/area categories. Với dữ liệu cũ, AP/mAP để null vì confidence không được lưu từ trước. Không thể khôi phục confidence thật từ các dòng tọa độ TXT.

## Kiểm thử và bằng chứng

12 bài kiểm thử đã đạt trong môi trường sạch, bao gồm:

- Lọc nhãn/instance, loại bbox trùng và từ chối confidence không hợp lệ.
- IoU và ghép một-một, không tính cùng một ground-truth bbox thành nhiều true positive.
- Không tạo AP từ confidence không biết.
- Ngân sách API, tiếp tục từ cache mà không gọi lại, chế độ offline không tạo client AWS.
- Khôi phục file từ phản hồi JSON đã lưu khi ghi đầu ra bị gián đoạn.
- Chặn dùng chung output cho hai chính sách nhận diện khác nhau.
- Dừng khi gặp lỗi quyền truy cập giả lập.
- Sao lưu/sửa nhãn, dựng video đủ frame, giữ FPS.
- Chia tập với khoảng cách thời gian và chặn đánh giá khi nhãn chưa rà soát.

Các bài test API dùng client giả lập, không dùng tài khoản thật. Kết quả metric trên dữ liệu tổng hợp trong test không phải chất lượng model ngựa vằn.

Bằng chứng kiểm tra cục bộ nằm trong `reports/verification_after.json`, các kết quả GitHub Actions. Báo cáo audit/repair/render/dataset nằm trong output của dự án. Bản mã và báo cáo trước tối ưu giữ ở `AWS_Rekognition_review/before_optimization`; nhãn gốc giữ dưới `output/backups` dạng ZIP.

## Những giới hạn còn cần dữ liệu hoặc mục tiêu riêng

- Cần người xác nhận 26 mẫu để có metric trên dữ liệu thật; không thể tự xác nhận mọi nhãn của model là đúng.
- Không có confidence và raw AWS response của các lượt chạy cũ; chỉ các request mới có thể lưu đầy đủ chúng.
- Chưa có tracking để đếm cá thể duy nhất; số bbox không được diễn giải là số động vật.
- Chưa huấn luyện detector mới; bộ YOLO được chuẩn bị để dùng sau khi kiểm tra chất lượng nhãn và xác định cách chia tập phù hợp.
- Chưa kiểm thử gọi AWS thật sau khi chuyển credential; phần network/retry/error đã được kiểm tra bằng test không phát sinh API call.

## Tài liệu chính thức

- [AWS cloud computing](https://aws.amazon.com/what-is-cloud-computing/).
- [DetectLabels](https://docs.aws.amazon.com/rekognition/latest/APIReference/API_DetectLabels.html).
- [BoundingBox](https://docs.aws.amazon.com/rekognition/latest/APIReference/API_BoundingBox.html).
- [Boto3 credentials](https://docs.aws.amazon.com/boto3/latest/guide/credentials.html).
- [Boto3 retries](https://docs.aws.amazon.com/boto3/latest/guide/retries.html).
- [Amazon Rekognition pricing](https://aws.amazon.com/rekognition/pricing/).


## Bản đăng GitHub

Mã nguồn được ghi công theo [tutorial gốc](https://github.com/computervisioneng/object-detection-aws-rekognition-tutorial). Toàn bộ video và output được cung cấp trong GitHub Release v1.0.0; README hướng dẫn tải, kiểm tra checksum và khôi phục. Đã bổ sung bốn kiểm thử trình khôi phục archive, nâng tổng số kiểm thử lên 16. Không có credential trong bản công khai.
