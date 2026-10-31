# Kết quả thu thập dữ liệu trường học Hà Nội (2026-11-01)

## Nguồn và phạm vi

- **Nguồn dữ liệu**: OpenStreetMap qua Overpass API, quan hệ hành chính
  *Thành phố Hà Nội* (relation 1903516, admin_level=4), giấy phép ODbL 1.0.
- **Truy vấn**: `amenity=school` + `amenity=kindergarten`, **đủ 3 loại hình học**
  (node, way, relation) — điểm way/relation lấy tâm polygon (`out center`).
- **URL gốc + sha256 + ngày truy xuất**: xem `data/raw/hanoi_schools_inventory/provenance.json`.
- Dữ liệu gốc OSM chốt thời điểm: `2026-10-31T20:28:05Z`; truy xuất ngày 2026-11-01.
- Cổng Sở GD&ĐT Hà Nội (hanoi.edu.vn) đã thăm dò: là trang tin tức, **không có**
  danh mục trường máy đọc được công khai → không dùng làm nguồn dữ liệu (ghi rõ hạn chế này).

## Kết quả chính

- **Tổng bản ghi sau khử trùng lặp cục bộ: 2209** (thô 2222 phần tử OSM).
- Trong đó có tên trường: 2128 bản ghi.
- Tập "geolocated candidate" (có tên + cấp học TH/tiểu học/THCS/THPT + tọa độ nguồn):
  **1332 bản ghi** → `data/processed/hanoi_schools_inventory/hanoi_schools_geolocated.csv`.

### Phân theo cấp học (phân loại theo tên trường, kèm bằng chứng tag amenity)

- `mầm non`: **660**
- `thcs`: **565**
- `tiểu học`: **553**
- `khác/chưa rõ`: **196**
- `thpt`: **167**
- `tiểu học + thcs`: **35**
- `gdtx/gdtn`: **20**
- `thcs + thpt`: **12**
- `pt dân tộc nội trú`: **1**

### Phân theo quận/huyện (tên lịch sử GADM 4.1, tọa độ lấy tâm ranh)

- ĐôngAnh: 126
- LongBiên: 122
- ChươngMỹ: 122
- HoàngMai: 115
- HàĐông: 114
- GiaLâm: 107
- BaVì: 104
- HoàiĐức: 102
- BắcTừLiêm: 101
- ThanhTrì: 99
- NamTừLiêm: 98
- CầuGiấy: 93
- ĐốngĐa: 78
- HaiBàTrưng: 77
- BaĐình: 72
- ThanhXuân: 66
- ĐanPhượng: 59
- PhúXuyên: 52
- SócSơn: 51
- ThạchThất: 48
- MỹĐức: 48
- ThườngTín: 46
- TâyHồ: 45
- HoànKiếm: 39
- PhúcThọ: 39
- QuốcOai: 37
- ỨngHòa: 36
- SơnTây: 35
- MêLinh: 33
- ThanhOai: 32
- (ngoài ranh GADM): 13

### So khớp với bộ 332 điểm case2 cũ (HOT export chỉ POINT)

- mới: 1722
- trùng điểm case2: 471
- cùng tên case2 nhưng khác vị trí: 16

- Bộ case2 cũ gồm: 237 school, 65 kindergarten, 16 university, 11 college, 3  — tức **không phải toàn bộ trường Hà Nội**, đã bỏ sót ~1300 polygon trường học OSM.
- So với các con số do nhóm cung cấp (124 THPT, 298 tiểu học, 226 THCS — chưa kiểm chứng):
  bộ sưu tầm này có 167 THPT, 588 tiểu học (cộng liên cấp TH+THCS), 612 THCS(cộng liên cấp); chưa đối chiếu bắt buộc vì phạm vi nguồn khác nhau.

## Giới hạn / tính trung thực

- Tọa độ way/relation là **tâm polygon từ nguồn**, không phải điểm do port đo độc lập;
  cột `coordinate_basis` phân biệt rõ (osm_node / osm_way_center / osm_relation_center).
- **Không geocode suy đoán**: mọi tọa độ đều từ nguồn; bản ghi không tên vẫn giữ lại
  để khỏi mất dữ liệu nhưng bị loại khỏi tập geolocated candidate.
- Phân cấp học suy ra từ **quy ước đặt tên tiếng Việt** trong tên OSM (có thể sai ở tên thiếu chuẩn).
- Quận/phường dùng **GADM 4.1 (tên lịch sử)**; ranh có thể lệch với hiện trạng sau sáp nhập.
- Khử trùng chỉ gộp **cùng tên chuẩn hóa + cách <150 m**; các chi nhánh/trùng tên khác vị trí **được giữ nguyên**.
- 13 phần tử bị đánh dấu trùng lặp gần, xem `data/raw/hanoi_schools_inventory/dedup_log.csv`.
- Chưa tích hợp vào Case1 (bản đồ/model): cần audit người trước khi dùng.

## Lệnh tái lập

```bash
python3 scripts/collect_hanoi_schools.py             # tải mới + xuất CSV
python3 scripts/collect_hanoi_schools.py --offline   # dựng lại từ JSON đã lưu
python3 scripts/collect_hanoi_schools.py --self-check
python3 tests/test_school_inventory.py               # test nhỏ (stdlib)
```