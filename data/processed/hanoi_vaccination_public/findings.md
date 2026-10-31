# Kết quả cào dữ liệu tiêm chủng công khai tại Hà Nội (sởi & tiêm chủng trẻ em, 2024-2026)

Ngày thu thập: **2026-11-01** (giờ Việt Nam, UTC+7). Người thực hiện: kịch bản `scripts/collect_hanoi_vaccination_public.py` (chỉ stdlib).

## 1. Mục tiêu & phạm vi

Cào **dữ liệu thật, công khai** về các lần tiêm chủng tại Hà Nội để thấy: **tiêm ở đâu** (điểm tiêm), **phân bố ở đâu nhiều** (quận/huyện/phường), và **bao nhiêu mũi đã tiêm / chỉ tiêu**. Ưu tiên sởi & tiêm chủng trẻ em giai đoạn **2024-2026**.

Không có dữ liệu cấp cá nhân từng trẻ (không thu thập, nguồn công khai cũng không công bố).

## 2. Nguồn thu thập (18 trang tải được + 1 bị chặn)

| # | Nguồn | Số trang | Ghi chú |
|---|---|---|---|
| 1 | `soyte.hanoi.gov.vn` — cổng Sở Y tế TP Hà Nội | **16** (15 bài + 1 mục tin) | Chính thức, HTTP 200, lưu html+text thô |
| 2 | `tapchicongthuong.vn` (Tạp chí Công thương, 14/10/2024) | 1 | **Báo chí bổ sung**, đánh dấu riêng `press_supplementary` |
| 3 | `baomoi.com` (trang chuyển hướng tới bài gốc trên) | 1 | **Báo chí bổ sung**, đánh dấu riêng |
| 4 | `hanoicdc.gov.vn` — CDC Hà Nội | 0 (bị chặn) | HTTP & HTTPS đều **timeout ≥ 30s** từ môi trường thu thập; nội dung đợt 3/2025 có bản sao trên soyte.hanoi.gov.vn (`soyte_dot3_ketqua_2025`) |

Toàn bộ 18 trang: URL đầy đủ, ngày lấy, HTTP 200, số byte, SHA-256 nằm trong `sources_provenance.csv` và bằng chứng thô `data/raw/hanoi_vaccination_public/<slug>.html` (+ `.txt` đã lọc). Kịch bản `--fetch` tải lại được tất cả trừ hanoicdc (chấp nhận lỗi từng nguồn, không chết giữa chừng — xem `fetch_manifest.csv`).

Chú ý cổng `hanoi.gov.vn` (thành phố) và các cổng quận/huyện (`*.hanoi.gov.vn`: caugiay, dongda, hoankiem, hadong, socson, longbien, gialam, donganh — đều HTTP 200) dùng form tìm kiếm POST .NET không gọi được bằng HTTP đơn giản nên **chưa khai thác được bài ở cấp quận**; toàn bộ số liệu cấp quận dưới đây đều trích từ cổng Sở Y tế.

## 3. Kết quả chính — TIÊM Ở ĐÂU

### 3.1. Mạng điểm tiêm (loại hình)

- **Điểm tiêm chủng cố định = trạm y tế xã/phường/thị trấn + trung tâm y tế quận/huyện** (hệ điểm tiêm thường xuyên), tiêm chiến dịch cùng hoặc khác ngày tiêm thường xuyên (Kế hoạch 261/KH-KSBT).
- Đợt 3 lần 1 (26-29/4/2025): **519 điểm tiêm = 446 trạm y tế + 73 điểm tại trường học** (nguồn `soyte_dot3_ketqua_2025`).
- Quy định vận hành điểm tiêm (Kế hoạch 261): ≤ **100 đối tượng/bàn tiêm/buổi** riêng vắc xin sởi; ≤ **50** nếu tiêm kèm vắc xin khác; ít nhất 3 cán bộ y tế được tập huấn an toàn tiêm chủng/điểm.
- **KHÔNG có tọa độ GPS trong nguồn** → các bảng dưới đây **không geocode**; liên kết với `data/processed/case1/facilities.csv` phải bằng tên + phường/xã, và 320 cơ sở ứng viên trong repo **chưa từng được xác nhận là điểm tiêm sởi**.

### 3.2. Điểm tiêm được nêu tên (13 dòng trong `vaccination_facilities.csv`)

| Điểm tiêm | Vai trò | Số liệu kèm (loại) | Ngày |
|---|---|---|---|
| TYT p. Vĩnh Tuy (q. Hai Bà Trưng) | tiêm chiến dịch sởi 6-<9 tháng | 241 trẻ diện tiêm (chỉ tiêu) | 17/2/2025 |
| TTYT q. Hai Bà Trưng | đơn vị tổ chức | ~1.000 đối tượng diện tiêm (chỉ tiêu, "gần 1000") | 17/2/2025 |
| 15 TYT phường q. Hai Bà Trưng | tiêm đồng loạt | (không có số từng trạm) | 17-28/2/2025 |
| TYT p. Quỳnh Mai; TYT p. Đồng Nhân | điểm tiêm vét | (không có số) | sau 28/2/2025 |
| TYT p. Dịch Vọng (q. Cầu Giấy) | tiêm chiến dịch | **33/75 trẻ đã tiêm (thực tế)** | 17/2-21/3/2025 |
| TYT p. Kim Liên (q. Đống Đa) | tiêm chiến dịch | **24/65 trẻ đã tiêm (thực tế)** | đến 24/3/2025 |
| Mạng điểm q. Hoàn Kiếm | tiêm chiến dịch | **88/116 trẻ đã tiêm (thực tế)** | đến 24/3/2025 |
| TYT thị trấn Kim Bài (h. Thanh Oai) | điểm tiêm (kiểm tra đảm bảo vắc-xin) | (không có số) | 2/2025 |
| TYT p. Yên Nghĩa (q. Hà Đông) | điểm tiêm thường xuyên (ảnh minh họa) | (không có số) | 16/4/2025 |
| TTYT q. Long Biên | tổ chức đợt 3 | (không có số riêng) | 26-29/4/2025 |
| 446 TYT X/P/TT toàn thành phố | đợt 3 lần 1 | 446 điểm (số điểm, không phải số trẻ) | 29/4/2025 |
| 73 điểm tại trường học | đợt 3 lần 1 (11-15 tuổi) | 73 điểm | 29/4/2025 |

Quận/huyện được CDC Hà Nội giám sát chiến dịch tuần 17-28/2/2025: **Bắc Từ Liêm, Ba Đình, Đông Anh, Hà Đông, Tây Hồ, Mê Linh, Nam Từ Liêm, Phú Xuyên, Sóc Sơn**.

## 4. Kết quả chính — CÁC ĐỢT TIÊM & SỐ MŨI THẬT (6 dòng trong `vaccination_campaign_events.csv`, 80 chỉ số trong `vaccination_administered_metrics.csv`)

| Đợt | Vắc-xin | Đối tượng | Thời gian | Diện tiêm (chỉ tiêu) | **Đã tiêm (thực tế)** |
|---|---|---|---|---|---|
| Đợt 1/2024 | sởi-rubella (MRVAC theo báo chí) | trẻ 1-5 tuổi + nhân viên y tế nguy cơ | từ 14/10/2024 | 57.777 trẻ + 2.367 NVY | **55.640 trẻ (96,3%) + 2.263 NVY (95,6%)** đến 15/11/2024 |
| Chiến dịch sởi 6-<9 tháng (Kế hoạch 261/KH-KSBT) | sởi | trẻ đủ 6 tháng - dưới 9 tháng | 17/2 → 31/3/2025 (vét tiếp) | ≥95% | bao phủ **66%** toàn thành phố (13/3/2025) |
| Đợt 3/2025 lần 1 | sởi (32.500 liều BYT cấp) | đủ 6 tháng; 6-<9 tháng; 11-15 tuổi (xã nguy cơ cao) | 26-29/4/2025 (lần 2 <15/5/2025) | 2.686 + 2.199 + 29.555 | **1.816 (67,6%) + 1.668 (75,9%) + 27.297 (92,4%); dùng hết 32.500/32.500 liều** |
| TCMR thường xuyên 9T/2025 | sởi; sởi-rubella; … | theo lịch TCMR | 1/1-30/9/2025 | kế hoạch 71,25%/67,5% | bao phủ sởi **81,5%**; sởi-rubella **85,3%**; bOPV mũi 3 chỉ 10,4% (không đạt) |
| Kế hoạch TCMR 2026-2028 (279/KH-UBND ngày 9/10/2025) | TCMR + rota từ 2026 | trẻ em + thai phụ | 2026-2028 | ≥95% (VGB sơ sinh 24h ≥90%) | (chưa có số liệu giai đoạn) |
| TCMR 7 tháng đầu 2026 | sởi mũi 1; sởi-rubella; … | trẻ diện 95.586 (<1 tuổi); 101.640 (>1 tuổi) | đến hết tháng 7/2026 | tiến độ kế hoạch 55,4-61,8% | **sởi mũi 1: 55.536 trẻ (58,1%); sởi-rubella: 58.657 (57,7%)**; tiêm bù IPV 15.464 mũi, Td 4.044 mũi, VNNB 1.942 mũi, MRVAC 509, MVVAX 259… |

*(Các dòng TCMR là tiêm chủng thường xuyên, KHÔNG phải chiến dịch — đã tách bạch trong CSV bằng `campaign_id` và `value_type`.)*

## 5. Phân bố ở đâu nhiều — chỉ xếp hạng khi CÙNG chỉ số, CÙNG mốc thời gian

### 5.1. Ca mắc sởi theo quận/huyện — lũy tích 2024 → 14/3/2025 (cùng chỉ số, cùng mốc: hợp lệ xếp hạng)

| Hạng | Quận/huyện | Số ca |
|---|---|---|
| 1 | Hoàng Mai | 221 |
| 2 | Hà Đông | 100 |
| 3 | Thanh Trì | 93 |
| 4 | Nam Từ Liêm | 90 |
| 5 | Đống Đa | 85 |
| 6 | Tây Hồ | 71 |
| 7 | Hoàn Kiếm | 66 |
| 8 | Thường Tín | 62 |
| 9 | Ba Đình | 60 |

Nguồn: `soyte_taptrung_6den9thang` (hội nghị giao ban 18/3/2025, số lũy tích 1.446 ca tại 377 xã/phường/thị trấn, 30/30 quận huyện; `soyte_rasoat_6den9thang_2025` trùng số → đã dedup về 1 dòng metric M54; bảng cấp quận giữ nguyên). **Đây là số CA BỆNH, không phải số mũi tiêm.**

Mốc khác KHÔNG gộp: 1/1-22/11/2024 (115 ca, 88/579 XPTT, 25/30 quận huyện): Hoàng Mai 19 ca, Ba Đình 9 ca, Thanh Trì 8 ca (M67-M69). Cộng dồn 2026 đến 23/10/2026: 412 ca tại 113 phường/xã mới (M57).

### 5.2. Diện tiêm & đã tiêm cấp phường trong chiến dịch sởi 2025 (cùng chiến dịch C2, nhưng mốc công bố khác nhau 17/2-24/3 → xếp theo giá trị đã ghi, kèm lưu ý mốc)

| Địa bàn | Diện tiêm (chỉ tiêu) | Đã tiêm (thực tế) | Mốc |
|---|---|---|---|
| q. Đống Đa (toàn quận) | 744 | ~ (tỷ lệ thấp, không có số mũi) | 24/3/2025 |
| q. Hai Bà Trưng (toàn quận) | ~1.000 | ~ | 17/2/2025 |
| p. Vĩnh Tuy (Hai Bà Trưng) | 241 | ~ (ngày đầu mời >30 đối tượng) | 17/2/2025 |
| p. Dịch Vọng (Cầu Giấy) | 75 | 33 | đến 21/3/2025 |
| p. Kim Liên (Đống Đa) | 65 | 24 | đến 24/3/2025 |
| q. Hoàn Kiếm (toàn quận) | 116 | 88 | đến 24/3/2025 |

**Không thể so sánh trực tiếp** diện tiêm/đã tiêm của các phường vì mốc công bố khác nhau và phạm vi (phường vs toàn quận) khác nhau — CSV đã ghi rõ từng mốc. Quận có tỷ lệ tiêm chiến dịch thấp (điểm danh, không có số % từng quận): **Đống Đa, Hai Bà Trưng, Nam Từ Liêm, Gia Lâm, Long Biên** (13/3/2025).

### 5.3. Không so sánh được (đánh dấu rõ)

- Số mũi đợt 1/2024 (55.640 trẻ 1-5 tuổi) **không thể so** với số mũi đợt 3/2025 (27.297 trẻ 11-15 tuổi): khác vắc-xin chủng loại, khác nhóm tuổi, khác năm.
- Bao phủ TCMR 9T/2025 (81,5% sởi) **không thể so** với tiến độ 7 tháng 2026 (58,1% sởi mũi 1): khác kỳ báo cáo (9T vs 7T), khác năm.
- Số ca bệnh **không phải** số mũi tiêm — mọi bảng đều tách cột `value_type`.

## 6. Số liệu "throughput" thực tế vs dung lượng tổng hợp trong repo

- **Số mũi đã tiêm thực tế có bằng chứng**: 55.640 + 2.263 (đợt 1/2024, đến 15/11/2024); 1.816 + 1.668 + 27.297 = 30.781 mũi (đợt 3 lần 1, 26-29/4/2025, dùng hết 32.500 liều); sởi mũi 1 55.536 + sởi-rubella 58.657 (7 tháng 2026, tiêm thường xuyên); cộng các mũi tiêm bù và các vắc-xin khác trong `vaccination_administered_metrics.csv`.
- **Không có bất kỳ số liệu công khai nào về công suất ngày/điểm tiêm hay số trẻ từng điểm tiêm đón mỗi buổi** (trừ quy định định mức ≤100 đối tượng/bàn/buổi — là QUY ĐỊNH, không phải sản lượng đo được). Do đó **không thể kiểm chứng hay thay thế** cột `capacity` tổng hợp trong `data/processed/case1/sites_capacity.csv` (README đã ghi rõ là tổng hợp giả định).
- Chỉ tiêu 2026 muốn giảm sởi xuống dưới 434 ca/năm; giám sát đến 11/9/2026 có 364 ca, đến 23/10/2026 cộng dồn 412 ca — cho thấy mức tiêm hiện tại chưa đạt ngưỡng miễn dịch cộng đồng để chặn dịch (đợt 3/2025 chỉ đạt 67,6-92,4% so với mục tiêu 95%).

## 7. Tên đơn vị hành chính (bảo tồn danh mục lịch sử)

- Số liệu 2024 - 6/2025 dùng danh mục **30 quận/huyện/thị xã, 579 xã/phường/thị trấn** (Hoàng Mai, Hà Đông, Thanh Trì...). Các bảng giữ nguyên tên gọi này.
- Từ 1/7/2025 Hà Nội chuyển chính quyền 2 cấp, sáp nhập còn **126 phường/xã**; số liệu từ tháng 10/2025 trở đi dùng danh mục mới ("65/126 xã", "113 phường, xã", tên như Ô Diên, Dân Hoà...). **Không đổi tên lịch sử, không gán phố/xã mới vào số liệu cũ.**

## 8. Giới hạn & khai báo trung thực

1. **hanoicdc.gov.vn không truy cập được** (timeout cả HTTP/HTTPS) → dùng bản sao cùng nội dung trên soyte.hanoi.gov.vn; chưa có bản nhắn trực tiếp từ CDC Hà Nội.
2. **Không geocode**: nguồn không có tọa độ; KHÔNG chế lat/lon. Muốn có vị trí phải nối tên + phường/xã với `facilities.csv` (chính ra là 320 cơ sở ứng viên OSM/HDX — vẫn **chưa xác nhận** là điểm tiêm).
3. **Không có số liệu cấp quận cho số mũi tiêm** (chỉ có cấp phường lẻ tẻ và cấp thành phố); phân bố "nhiều" ở trên chủ yếu dựa số ca bệnh và diện tiêm, không phải sản lượng tiêm theo quận.
4. **Số gần đúng trong nguồn** ("gần 1.700 ca", "gần 1000 đối tượng") được ghi nguyên văn kèm dấu ~.
5. **Dichbenh 2-9/10/2026** không nhắc sởi (chỉ sốt xuất huyết) — giữ làm bằng chứng tuần báo, không dùng cho bảng chỉ số sởi.
6. Bài Viện Pasteur TP.HCM tìm thấy qua bộ máy tìm kiếm là bản tin **năm 2014** (ngoài phạm vi 2024-2026) — **đã loại, không dùng**.
7. Toàn bộ số liệu là số **tổng hợp** công khai; không có dữ liệu cá nhân.

## 9. Cách tái lập

```bash
python scripts/collect_hanoi_vaccination_public.py --fetch       # tải lại 18/18 nguồn còn truy cập được + ghi manifest (hanoicdc bị chặn, bỏ qua an toàn)
python scripts/collect_hanoi_vaccination_public.py --process    # dựng lại 4 CSV UTF-8 BOM
python scripts/collect_hanoi_vaccination_public.py --self-check  # kiểm schema/URL/loại số liệu/dedup (đang ĐẠT, exit 0)
```

Tệp kết quả:
- `data/raw/hanoi_vaccination_public/` — 37 tệp: 18 bằng chứng thô `.html` + 18 `.txt` tách văn bản + `fetch_manifest.csv` (URL, thời điểm, HTTP, byte, SHA-256).
- `data/processed/hanoi_vaccination_public/` — `sources_provenance.csv` (19), `vaccination_facilities.csv` (13), `vaccination_campaign_events.csv` (6), `vaccination_administered_metrics.csv` (80) + tệp `findings.md` này.
