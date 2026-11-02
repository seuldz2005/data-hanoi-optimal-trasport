# Kết quả thu thập dữ liệu trạm y tế xã/phường Hà Nội (2026-11-02)

## Nguồn và phạm vi

- **Nguồn dữ liệu chính**: OpenStreetMap qua Overpass API (ODbL 1.0), quan hệ hành
  chính *Thành phố Hà Nội* (relation 1903516, admin_level=4).
- **Truy vấn hợp nhất 3 vế bằng chứng, mỗi vế đủ 3 loại hình học** (node + way +
  relation, điểm way/relation lấy tâm polygon `out center`):
  1) `amenity` ∈ {clinic, doctors, hospital}; 2) có tag `healthcare` bất kỳ;
  3) tên chứa `tr[ạa]m y t` (không phân biệt hoa/thường).
- **URL gốc + sha256 + ngày truy xuất**: `data/raw/hanoi_health_stations/provenance.json`.
- Dữ liệu gốc OSM chốt thời điểm: `2026-11-02T08:33:08Z`; truy xuất 2026-11-02T08:37:09Z.
- Thăm dò cổng chính thức (chỉ lưu bằng chứng, **không dùng làm nguồn dữ liệu**):
  - `probe_soyte_search_danhsach_tramyte` (https://soyte.hanoi.gov.vn/?q=danh+s%C3%A1ch+tr%E1%BA%A1m+y+t%E1%BA%BF) -> HTTP 200. cổng Sở Y tế: kết quả là bài tin tức, không có danh mục trạm y tế máy đọc được. Tiêu đề thấy: Bệnh viện Tim Hà Nội tổ chức lễ kỷ niệm 25 năm thành lập và ; Bệnh viện đa khoa Ba Vì: Đưa tiến bộ y học đến gần với người; Ra mắt mô hình “Tổ hợp chăm sóc và phục hồi chức năng cho ng.
  - `probe_soyte_search_tramyte` (https://soyte.hanoi.gov.vn/?q=tr%E1%BA%A1m+y+t%E1%BA%BF) -> HTTP 200. cổng Sở Y tế: chỉ tin tức hoạt động TYT (vd TYT phường Kiến Hưng), không danh mục. Tiêu đề thấy: Bệnh viện Tim Hà Nội tổ chức lễ kỷ niệm 25 năm thành lập và ; Bệnh viện đa khoa Ba Vì: Đưa tiến bộ y học đến gần với người; Ra mắt mô hình “Tổ hợp chăm sóc và phục hồi chức năng cho ng.
  - `probe_hanoicdc_root` (https://hanoicdc.gov.vn/) -> HTTP 200. thăm dò khả năng tiếp cận (kỳ vọng không có danh mục trạm phường/xã). Tiêu đề thấy: Tình hình dịch bệnh trên địa bàn thành phố Hà Nội từ ngày 23; Tình hình dịch bệnh trên địa bàn thành phố Hà Nội từ ngày 23; Tăng cường truyền thông dinh dưỡng, vận động hợp lý phòng bệ.
  → **Không tìm thấy danh mục trạm y tế máy đọc được** (địa chỉ từng trạm) trên
    cổng Sở Y tế / CDC; mọi bản ghi dưới đây đều bằng chứng OSM, không suy đoán.

## Kết quả chính

- **Tổng bản ghi cơ sở y tế sau khử trùng lặp cục bộ: 714** (thô 722 phần tử OSM: 413 node, 12 relation, 297 way).
- **Trạm y tế xã/phường (lớp `trạm y tế`, suy từ tên): 159 bản ghi có tên** → mở rộng so với case1 (HOT export chỉ POINT) có **19 tên chứa 'trạm y tế'** + 2 biến thể 'trạm xá' (Tram Xa Co Nhue, trạm xá).
- Tập "geolocated" (chỉ TYT có tên + tọa độ nguồn): **159 bản ghi** → `data/processed/hanoi_health_stations/hanoi_health_stations_geolocated.csv`.
- Tọa độ theo nguồn: 72 osm_node, 1 osm_relation_center, 86 osm_way_center — **100% tọa độ nguồn, 0 bản ghi address-only, không geocode suy đoán**.
- Đối chiếu case1 (19 tên “trạm y tế” + 2 tên biến thể “trạm xá”): **21 trùng điểm** (<300 m + cùng tên), 0 cùng tên khác vị trí, **138 trạm mới** không có trong case1.

### Phân loại theo bằng chứng tên/tag (không suy đoán)

- `cơ sở y tế khác`: **286**
- `bệnh viện`: **166**
- `trạm y tế (xã/phường)`: **159**
- `phòng khám`: **95**
- `trung tâm y tế (quận/huyện)`: **8**

### Trạm y tế theo quận/huyện (GADM 4.1, tên lịch sử)

- GiaLâm: 13
- ChươngMỹ: 12
- NamTừLiêm: 10
- SócSơn: 10
- HoàngMai: 10
- ĐôngAnh: 9
- BắcTừLiêm: 8
- LongBiên: 7
- HoàiĐức: 6
- PhúcThọ: 6
- MỹĐức: 6
- PhúXuyên: 6
- HaiBàTrưng: 6
- QuốcOai: 5
- MêLinh: 5
- HàĐông: 5
- CầuGiấy: 4
- ĐốngĐa: 4
- BaVì: 4
- BaĐình: 4
- ThanhXuân: 3
- ĐanPhượng: 3
- ThạchThất: 3
- ThanhTrì: 3
- (ngoài ranh GADM): 2
- TâyHồ: 2
- ThanhOai: 1
- ThườngTín: 1
- ỨngHòa: 1

### Phạm vi phủ xã/phường

- Trạm TYT có tên nằm trong **127 xã/phường GADM 4.1 riêng biệt**
  (trong tổng số **584 xã GADM 4.1 lịch sử**, tức 127/584 = 21.7%).
- **114** tên xã/phường/thị trấn khác nhau trích được từ tên trạm (`commune_in_name`, bằng chứng chữ trong tên, không phải geocode).
- **KHÔNG khẳng định mỗi xã đều có trạm**: OSM là crowdsourced, nhiều trạm chưa được
  vẽ; số trên là chốt dưới của mật độ thực, không phải độ phủ hành chính.
- Từ 2025-07-01 Hà Nội sáp nhập còn **126 phường/xã mới**; GADM 4.1 trong repo vẫn là
  584 xã lịch sử → ranh/`ward_gadm41` là TÊN CŨ, chưa có ánh xạ cũ→mới công khai máy
  đọc được ở đây (không chế tạo ánh xạ).

## Giới hạn / tính trung thực

- Tọa độ way/relation là **tâm polygon từ nguồn** (`coordinate_basis`), không phải đo độc lập.
- **Không geocode suy đoán, không lấy tâm xã**: mọi tọa độ từ hình học OSM;
  không có bản ghi address-only vì không nguồn chính thức nào cho ra bản ghi.
- Phân loại dựa trên **quy ước tên tiếng Việt** (Trạm y tế/Trạm xá) + tag OSM;
  trạm thiếu tên chuẩn có thể rơi lớp khác — mở raw JSON để kiểm chứng từng phần tử.
- Khử trùng chỉ gộp **cùng tên chuẩn hóa + cách <150 m**; các cơ sở 1/2, trùng tên khác
  vị trí **giữ nguyên**; 8 phần tử bị gộp gần, xem `dedup_log.csv`.
- Không có **sức chứa/năng lực** nào được gán (không chế tạo capacity).
- Chưa tích hợp vào Case1 (bản đồ/model): cần audit người trước khi dùng.

## Lệnh tái lập

```bash
python3 scripts/collect_hanoi_health_stations.py             # tải mới + xuất CSV
python3 scripts/collect_hanoi_health_stations.py --offline   # dựng lại từ JSON đã lưu
python3 scripts/collect_hanoi_health_stations.py --self-check
python3 tests/test_health_stations.py                        # test nhỏ (stdlib)
```