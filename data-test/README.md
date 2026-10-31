# Case 1 thử nghiệm — Hoài Đức

**20 xã/thị trấn, 30 điểm ứng viên: 2 trạm y tế + 28 cơ sở giáo dục.**
Toàn bộ địa bàn Hoài Đức theo ranh lịch sử GADM 4.1, không phải ranh hành chính hiện tại.
ID và số trẻ được giữ nguyên từ bộ dữ liệu dự án; không tạo xã/trường giả.

## Các file

| File | Ý nghĩa |
|---|---|
| `population.csv` | 20 địa bàn: mã, tên, số trẻ dưới 5 tuổi ước tính, tọa độ tâm, nguồn và năm |
| `facilities.csv` | 30 điểm: mã, tên, loại, tọa độ, mã địa bàn; `capacity` thực tế để trống |
| `sites_capacity.csv` | Sức chứa **giả lập** nguyên: 658–659 trẻ/điểm, tổng 19.769; không có kỳ ngày/tháng |
| `distance_matrix.csv` | Ma trận **20 × 30**, khoảng cách đường thẳng Haversine (km); hàng `commune_id`, cột `facility_id` |
| `commune_boundaries.geojson` | Ranh 20 địa bàn để hiển thị GIS |
| `allocation_lp.csv` | Kết quả OT chính xác bằng LP; số trẻ từ mỗi địa bàn tới từng điểm, khoảng cách |
| `metadata.json` | Phương pháp chọn, kết quả solver, giới hạn, SHA-256 dữ liệu nguồn |
| `prepare.py` | Tái tạo bộ dữ liệu và giải LP từ dữ liệu dự án |
| `check.py` | Kiểm tra ID, ma trận, sức chứa và bảo toàn phân bổ |

## Bài toán

Tìm số trẻ `x[i,j] >= 0` để tối thiểu hóa `sum(x[i,j] * distance[i,j])`.
Tổng mỗi hàng bằng nhu cầu địa bàn; tổng mỗi cột bằng sức chứa giả lập của điểm.
Vì tổng nhu cầu bằng tổng sức chứa, tất cả các điểm đều sử dụng hết sức chứa trong kịch bản này.

- Tổng nhu cầu mô hình: **19.769 trẻ**.
- Khoảng cách trung bình tối ưu: **1,1474 km/trẻ**, một chiều đường thẳng.
- Tổng chi phí: **22.682,95 trẻ·km**.
- Nghiệm đã kiểm tra bảo toàn từng địa bàn và từng điểm; số trẻ nguyên.

## Chọn điểm

Giữ 2 trạm y tế có tên trong địa bàn (Kim Chung, Vân Canh); không lấy nhà thuốc không tên.
Trong các ứng viên còn lại, lấy điểm gần nhất với tâm từng xã/thị trấn, rồi bổ sung
điểm có độ tách không gian lớn nhất cho đủ 30. Quy tắc cố định, không lấy ngẫu nhiên.
Không khẳng định mỗi xã đều có điểm được chọn. Trường có thể đại diện bằng tâm khuôn viên, không phải cổng.

## Chạy

Từ gốc repository, dùng môi trường đã cài dependencies trong `pyproject.toml`:

```bash
python data-test/check.py
python data-test/prepare.py
python scripts/run_benchmarks.py data-test/population.csv data-test/sites_capacity.csv data-test/distance_matrix.csv --methods lp
```

`check.py` chỉ cần numpy/pandas và các CSV trong folder. `prepare.py` cần repository nguồn,
geopandas/scipy cùng package dự án; script tự thêm `src/` vào đường dẫn import.

## Không diễn giải thành thực tế vận hành

- Trẻ dưới 5 tuổi là dân số **ước tính HRSL 2020**, không phải danh sách trẻ đến hạn tiêm.
- Sức chứa **giả lập chia đều**, không phải công suất thực tế hoặc số liều đã cấp.
- Cơ sở y tế/trường là **ứng viên chưa xác nhận đủ điều kiện tiêm**.
- Khoảng cách đường thẳng, không phải đường bộ/thời gian đi lại; tâm xã không phải nhà từng trẻ.
- Danh mục OSM không đầy đủ; tập 30 điểm là kịch bản nghiên cứu, không phải đề xuất mở điểm tiêm.

Nguồn: HRSL/Meta qua HDX (CC BY 4.0); HOT/OSM và Overpass (ODbL);
GADM 4.1 (điều khoản học thuật). Xem README dự án và metadata để truy nguồn.

## Gói thời gian 100×50×4 (mới)

Xem [`temporal_100x50/`](temporal_100x50/README.md): 100 xã ngoại thành × 50 điểm ứng viên × 4 giờ,
lượng đến nguyên theo giờ, công suất dài theo giờ (baseline/surplus), benchmark tay (LP 3×2 tối ưu 530,
thắt cổ chai hàng đợi), kiểm định `check.py` và `tests/test_temporal_data.py`. Gói 20×30 ở trên vẫn giữ nguyên.
