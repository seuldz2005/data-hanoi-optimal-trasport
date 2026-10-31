# data-test/temporal_100x50 — gói dữ liệu thời gian 100 xã × 50 điểm × 4 giờ

Gói dữ liệu thử nghiệm thứ hai của repo (không thay thế gói gốc 20×30 ở `data-test/`).

## Diễn giải mô hình

- **100 xã** phía ngoại Hà Nội (cũ, GADM 4.1) là **nguồn cầu** (origin), KHÔNG phải 100 cơ sở y tế tại chỗ. Mỗi xã **được phục vụ bởi** các điểm ứng viên trong 50 điểm: đồ thị tuyến hoàn toàn (mỗi xã đi tới được mọi điểm), không đặt giới hạn di chuyển giả tạo.
- **50 điểm ứng viên** = 5 cơ sở y tế có tên (trạm y tế/phòng khám/bệnh viện, loại trừ nhà thuốc, nha khoa, phòng khám tư "doctors", tên trống, đại học/cao đẳng) + 45 trường học có tên, chọn trong đa giác 100 xã bằng greedy xa nhất (tọa độ phẳng cục bộ), ID nguồn giữ nguyên. Trạng thái: `candidate`, chưa xác minh.
- Chọn cụm: mọc từ hạt Hoài Đức + Quốc Oai, mỗi bước thêm xã **tiếp giáp đa giác chính xác** gần tâm hạt nhất, loại 12 quận nội thành lịch sử (Hoàn Kiếm, Ba Đình, Đống Đa, Hai Bà Trưng, Cầu Giấy, Thanh Xuân, Tây Hồ, Hoàng Mai, Long Biên, Bắc Từ Liêm, Nam Từ Liêm, Hà Đông); kiểm chứng liên thông BFS. Kết quả: Quốc Oai 21, Hoài Đức 20, Thạch Thất 20, Chương Mỹ 20, Đan Phượng 9, Phúc Thọ 7, Thanh Oai 2, Sơn Tây 1.
- **4 giờ** dịch vụ (1..4). Lượng đến mỗi xã mỗi giờ là số nguyên thuộc `[ceil(0.2x), floor(0.3x)]` với `x = children_under_5` của xã đó, tổng 4 giờ đúng bằng `x`; lấy mẫu tuần tự có ràng buộc "phần dư khả thi" theo thứ tự giờ hoán vị ngẫu nhiên (seed cố định 20260101) để tránh lệch giờ cuối; tổng quá nhỏ bất khả thi bị loại.

## Lệnh chạy (từ gốc repo)

```bash
python data-test/temporal_100x50/prepare.py   # tạo lại dữ liệu
python data-test/temporal_100x50/check.py     # kiểm định + LP khả thi 4 giờ
python data-test/temporal_100x50/benchmarks/benchmarks.py  # benchmark tay
```

`check.py` chạy 4 LP thưa (scipy `linprog`/HiGHS, A_eq 200×5000) và ghi `solver_summary.json`; hash tái tạo trong `metadata.json` (`outputs`) bỏ qua timestamp.

## Schema tệp

| Tệp | Schema |
|---|---|
| `population.csv` | `commune_id, commune_name, children_under_5, centroid_lat, centroid_lon, data_year, source` (subset ID nguồn) |
| `facilities.csv` | `facility_id, facility_name, facility_type, latitude, longitude, capacity, capacity_source, source, site_class, vaccination_site_status, commune_id`; `capacity` luôn NaN (không có công suất thật) |
| `sites_capacity.csv` | `facility_id, capacity, capacity_source, capacity_unit` — `capacity` = tổng balanced 4 giờ mỗi điểm, `capacity_source=synthetic` |
| `distance_matrix.csv` | 100×50 haversine km, subset theo ID từ `data/processed/case1/distance_matrix.csv`, KHÔNG phải đường bộ |
| `arrivals/hour_1..4.csv` | `commune_id, arrivals` (số nguyên) |
| `capacity_by_hour.csv` | dạng dài: `facility_id, hour, capacity_balanced, capacity_surplus` (200 dòng) |
| `commune_boundaries.geojson` | ranh giới GADM 4.1 của 100 xã |
| `scenarios.json` | kịch bản baseline/surplus, `lambda_grid` = [0, 1, 5] (tuỳ chọn, không cài solver), đồ thị hoàn toàn, mô hình phục vụ |
| `metadata.json` | seed, ngày tạo, hash đầu vào/đầu ra, diễn giải chọn cụm, cảnh báo tọa độ |

Bất biến: mỗi giờ `sum(arrivals) == sum(capacity_balanced)`; `sum(capacity_surplus) == ceil(1.1*arrivals)`; tổng các giờ theo điểm == `sites_capacity.capacity` (chia bằng `hanoi_ot.capacity.largest_remainder_split`, xoay thứ tự điểm theo giờ).

## Hàng đợi: chỉ số thời gian

Trạng thái hàng đợi tại một điểm: `q(1)=0` ban đầu, với giờ `t = 1..4`:

```
q(t+1) = max(0, q(t) + arrivals_to_site(t) - capacity(t))
```

Chỉ số sau giờ 4 là **`q(5)`** — yêu cầu đầu ra là **`q(5) = 0`** (không dư người phục vụ cuối phiên). Khuyến nghị: mô phỏng theo từng giờ, theo dõi cả `q(2)..q(5)`, không chỉ tổng. Benchmark `benchmarks/benchmarks.py` minh họa: tổng công suất toàn hệ đủ mỗi giờ vẫn có thể xếp hàng cục bộ (một origin chỉ tới được điểm bị giới hạn), và ngược lại gói chính dùng đồ thị hoàn toàn nên hàng đợi có thể triệt tiêu (`[0,0,0,0]`). Công suất phục vụ dư **không được chuyển ngân** sang giờ sau; tồn kho vaccine (supply) là đại lượng **riêng**, tách khỏi công suất phục vụ.

## Benchmark tay

- Vận tải 3×2: `x=[100,120,80]`, `y=[150,150]`, `D=[[2,5],[4,1],[3,2]]` → tối ưu **530** (chứa trong `benchmarks/benchmarks.py`, khẳng định bằng LP thưa + phân bổ tay).
- Thắt cổ chai hàng đợi: công suất toàn cục ≥ lượng đến mỗi giờ, nhưng origin A chỉ tới được S1 (công suất giờ 1 là 30 < 40) → `q(2)=10`, thoát nước giờ 2, `q(5)=0`; kết quả mong đợi bất biến trong tệp.

## Cảnh báo chính (không có dữ liệu quan trắc chính thức)

- `children_under_5` là **proxy HRSL 2020** (Meta HRSL under-5 via HDX, CC-BY 4.0), không phải nhu cầu tiêm chủng thực tế; lượng đến mỗi giờ là **giả lập**.
- Khoảng cách là **haversine**, không phải đường bộ; không dữ liệu đường bị " chế".
- Ranh giới **GADM 4.1 (ranh lịch sử)** khác đơn vị hành chính Hà Nội hiện nay; tọa độ cơ sở là tâm polygon OSM, cổng trường chưa xác minh; điểm chỉ ở trạng thái **candidate**.
- Công suất là **tổng hợp** (balanced/surplus), không có công suất vận hành thật.
