#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Thu thập dữ liệu tiêm chủng công khai của Hà Nội (sởi/tiem chủng trẻ em, 2024-2026).

Nguồn chính thức: Sở Y tế TP Hà Nội (soyte.hanni.gov.vn -> soyte.hanoi.gov.vn),
cổng thông tin TP (hanoi.gov.vn), CDC Hà Nội (hanoicdc.gov.vn - bị chặn, xem ghi chú).
Nguồn báo chí bổ sung: đánh dấu riêng "press_supplementary".

Chỉ dùng stdlib. Ghi đè/dữ liệu chỉ trong:
  data/raw/hanoi_vaccination_public/       (bằng chứng thô html + text)
  data/processed/hanoi_vaccination_public/ (CSV UTF-8 BOM)

Cách dùng (chạy từ gốc repo):
  python scripts/collect_hanoi_vaccination_public.py --fetch      # tải lại nguồn (mạng bị chặn bỏ qua, không chết)
  python scripts/collect_hanoi_vaccination_public.py --process   # dựng lại CSV từ bảng ghi có kiểm chứng
  python scripts/collect_hanoi_vaccination_public.py --self-check # kiểm tra schema/URL/số liệu/dedup
  python scripts/collect_hanoi_vaccination_public.py             # process + self-check

Mô hình dữ liệu: BẢNG GHI (records) dưới đây được trích TAY từ bằng chứng thô (file .txt
cùng slug trong data/raw), mỗi dòng kèm quote nguyên văn + source_slug; --fetch đảm bảo
bằng chứng thô tái tạo được từ các URL đã ghi. Không có dữ liệu cá nhân từng trẻ.
Không suy ra số mũi tiêm từ danh sách cơ sở y tế chung chung; không chế tọa độ.
"""

import argparse
import csv
import hashlib
import html.parser
import io
import os
import re
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(ROOT, "data", "raw", "hanoi_vaccination_public")
PROC_DIR = os.path.join(ROOT, "data", "processed", "hanoi_vaccination_public")

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
FETCH_TIMEOUT_S = 25
RETRIEVAL_DATE = "2026-11-01"  # ngày lấy số liệu đợt đầu (UTC+7)

# ---------------------------------------------------------------------------
# NGUỒN (tất cả đã tải thật, HTTP 200, bằng chứng nằm ở data/raw/.../<slug>.html)
# ---------------------------------------------------------------------------
SOURCES = [
    # slug, url, tiêu đề, nhà xuất bản, ngày đăng bài, loại, dùng để trích gì
    dict(slug="soyte_tiemchung_index",
         url="https://soyte.hanoi.gov.vn/tiem-chung",
         title="Tiêm chủng - Trang TTĐT Sở Y tế Thành phố Hà Nội (mục tin)",
         publisher="Sở Y tế TP Hà Nội",
         published="", category="official",
         used_for="Định vị mục tin Tiêm chủng của cổng Sở Y tế"),
    dict(slug="soyte_kehoach261_2025_6thang_9thang",
         url="https://soyte.hanoi.gov.vn/y-te-du-phong-65152/dam-bao-95-tre-tu-du-6-thang-den-duoi-9-thang-tuoi-duoc-tiem-1-mui-vac-xin-phong-benh-soi-2849250212123921585.htm",
         title="Đảm bảo 95% trẻ từ đủ 6 tháng đến dưới 9 tháng tuổi được tiêm 1 mũi vắc xin phòng bệnh sởi",
         publisher="Sở Y tế TP Hà Nội (tác giả Duy Tuân)", published="2025-02-12",
         category="official",
         used_for="Kế hoạch 261/KH-KSBT: mục tiêu 95%, phạm vi 30 quận huyện, quy trình điểm tiêm, TYT Kim Bài"),
    dict(slug="soyte_quanhuyen_trienkhai_6thang9thang",
         url="https://soyte.hanoi.gov.vn/y-te-du-phong-65152/cac-quan-huyen-trien-khai-tot-chien-dich-tiem-chung-vac-xin-phong-benh-soi-cho-nguoi-dan-2849250217102310774.htm",
         title="Các quận, huyện triển khai tốt chiến dịch tiêm chủng vắc xin phòng bệnh sởi cho người dân",
         publisher="Sở Y tế TP Hà Nội", published="2025-02-18", category="official",
         used_for="Sởi cộng dồn 2025 đến 14/2: 441 ca/30 quận huyện; danh sách quận giám sát tuần tới"),
    dict(slug="soyte_lanhdao_kiemtra_6thang9thang",
         url="https://soyte.hanoi.gov.vn/hoat-dong-cua-lanh-dao-so/lanh-dao-so-y-te-kiem-tra-cong-tac-tiem-vac-xin-phong-benh-soi-cho-tre-tu-6-thang-den-duoi-9-thang-tuoi-2849250217171831854.htm",
         title="Lãnh đạo Sở Y tế kiểm tra công tác tiêm vắc xin phòng bệnh sởi cho trẻ từ 6 tháng đến dưới 9 tháng tuổi",
         publisher="Sở Y tế TP Hà Nội (tác giả Thắng Đạt)", published="2025-02-18",
         category="official",
         used_for="TYT phường Vĩnh Tuy 241 đối tượng; TTYT Hai Bà Trưng ~1000 đối tượng, 15 TYT, 2 điểm vét"),
    dict(slug="soyte_taptrung_6den9thang",
         url="https://soyte.hanoi.gov.vn/y-te-du-phong-65152/can-tap-trung-trien-khai-quyet-liet-chien-dich-tiem-vac-xin-soi-cho-tre-tu-6-den-duoi-9-thang-tuoi-2849250321123235088.htm",
         title="Cần tập trung, triển khai quyết liệt chiến dịch tiêm vắc xin sởi cho trẻ từ 6 đến dưới 9 tháng tuổi",
         publisher="Sở Y tế TP Hà Nội (tác giả Thắng Đạt)", published="2025-03-21",
         category="official",
         used_for="Lũy tích sởi 2024->14/3/2025 = 1446 ca; 9 quận huyện dẫn đầu; tỷ lệ tiêm chiến dịch 66% (13/3)"),
    dict(slug="soyte_rasoat_6den9thang_2025",
         url="https://soyte.hanoi.gov.vn/y-te-du-phong-65152/cac-dia-phuong-tiep-tuc-ra-soat-trien-khai-tiem-vac-xin-phong-benh-soi-cho-tre-tu-6-den-duoi-9-thang-tuoi-2849250320153838482.htm",
         title="Các địa phương tiếp tục rà soát, triển khai tiêm vắc xin phòng bệnh sởi cho trẻ từ 6 đến dưới 9 tháng tuổi",
         publisher="Sở Y tế TP Hà Nội (tác giả Mai Trang)", published="2025-03-21",
         category="official",
         used_for="TYT phường Dịch Vọng: 75 trẻ diện tiêm, 33 trẻ đã tiêm từ 17/2"),
    dict(slug="soyte_kiemtra_dongda_hoankiem_2025",
         url="https://soyte.hanoi.gov.vn/hoat-dong-cua-lanh-dao-so/cac-dia-phuong-tiep-tuc-day-manh-tuyen-truyen-chien-dich-tiem-vac-xin-soi-cho-nguoi-dan-2849250324224617082.htm",
         title="Các địa phương tiếp tục đẩy mạnh tuyên truyền chiến dịch tiêm vắc xin sởi cho người dân",
         publisher="Sở Y tế TP Hà Nội (tác giả Duy Tuân)", published="2025-03-25",
         category="official",
         used_for="TYT Kim Liên 65/24 trẻ; quận Đống Đa 744 trẻ; quận Hoàn Kiếm 116/88 trẻ"),
    dict(slug="soyte_tiemvet_thang4_2025",
         url="https://soyte.hanoi.gov.vn/y-te-du-phong-65152/tiep-tuc-trien-khai-tiem-vet-vac-xin-phong-soi-trong-dau-thang-4-2025-2849250403104616127.htm",
         title="Tiếp tục triển khai tiêm vét vắc xin phòng sởi trong đầu tháng 4/2025",
         publisher="Sở Y tế TP Hà Nội (tác giả Nhã Khanh)", published="2025-04-03",
         category="official",
         used_for="Bối cảnh quốc gia 54 tỉnh thành, 682.000 mũi toàn quốc đến 31/3/2025 (không riêng Hà Nội)"),
    dict(slug="soyte_tangcuong_soi_tcm_2025",
         url="https://soyte.hanoi.gov.vn/y-te-du-phong-65152/tiep-tuc-tang-cuong-cong-tac-phong-chong-benh-soi-va-tay-chan-mieng-2849250416172309551.htm",
         title="Tiếp tục tăng cường công tác phòng, chống bệnh sởi và tay chân miệng",
         publisher="Sở Y tế TP Hà Nội (tác giả Diệu Linh)", published="2025-04-17",
         category="official",
         used_for="Công văn 147/SYT-NVY: ~1.700 ca sởi đến 13/4/2025; TYT Yên Nghĩa (Hà Đông)"),
    dict(slug="soyte_dot3_den15tuoi_2025",
         url="https://soyte.hanoi.gov.vn/y-te-du-phong-65152/ha-noi-tiep-tuc-to-chuc-chien-dich-tiem-vac-xin-soi-dot-3-cho-tre-den-15-tuoi-2849250426093529369.htm",
         title="Hà Nội tiếp tục tổ chức chiến dịch tiêm vắc xin sởi đợt 3 cho trẻ đến 15 tuổi",
         publisher="Sở Y tế TP Hà Nội (tác giả Duy Tuân)", published="2025-04-26",
         category="official",
         used_for="Kế hoạch đợt 3/2025: đối tượng, tiến độ lần 1 <30/4, lần 2 <15/5/2025"),
    dict(slug="soyte_dot3_ketqua_2025",
         url="https://soyte.hanoi.gov.vn/y-te-du-phong-65152/ha-noi-trien-khai-hieu-qua-chien-dich-tiem-chung-vac-xin-soi-dot-3-nam-2025-2849250505210417539.htm",
         title="Hà Nội triển khai hiệu quả chiến dịch tiêm chủng vắc xin sởi đợt 3 năm 2025",
         publisher="Sở Y tế TP Hà Nội (tác giả Duy Tuân)", published="2025-05-06",
         category="official",
         used_for="KẾT QUẢ đợt 3 lần 1 (26-29/4/2025): 519 điểm (446 TYT + 73 trường), số mũi theo nhóm tuổi, 32.500 liều"),
    dict(slug="soyte_chudong_phongchong_dich_soi_2024",
         url="https://soyte.hanoi.gov.vn/y-te-du-phong-65152/ha-noi-chu-dong-trien-khai-cac-bien-phap-phong-chong-dich-soi-2849241203111442756.htm",
         title="Hà Nội: Chủ động triển khai các biện pháp phòng chống dịch sởi",
         publisher="Sở Y tế TP Hà Nội", published="2024-12-03", category="official",
         used_for="Chiến dịch sởi-rubella từ 14/10/2024 trẻ 1-5 tuổi + NVY; diện 57.777 trẻ; tiêm 55.640 (96,3%) đến 15/11/2024; sởi 2024"),
    dict(slug="soyte_tcmr_2026_2028",
         url="https://soyte.hanoi.gov.vn/y-te-du-phong-65152/nang-cao-ty-le-tiem-chung-vac-xin-trong-chuong-trinh-tiem-chung-mo-rong-2849251111153555661.htm",
         title="Nâng cao tỷ lệ tiêm chủng vắc xin trong chương trình tiêm chủng mở rộng",
         publisher="Sở Y tế TP Hà Nội (tác giả Hạnh Ngân)", published="2025-11-12",
         category="official",
         used_for="Bao phủ TCMR 9 tháng 2025 theo từng vắc xin; Kế hoạch 279/KH-UBND TCMR 2026-2028"),
    dict(slug="soyte_chitieu_2026",
         url="https://soyte.hanoi.gov.vn/y-te-du-phong-65152/cac-chi-tieu-ve-ty-le-tiem-chung-deu-dat-so-voi-ke-hoach-2849260911112830059.htm",
         title="Các chỉ tiêu về tỷ lệ tiêm chủng đều đạt so với kế hoạch",
         publisher="Sở Y tế TP Hà Nội (tác giả Hạnh Ngân)", published="2026-09-11",
         category="official",
         used_for="TCMR 7 tháng 2026: số mũi đã tiêm từng vắc xin, tiêm bù, giám sát sởi 364 ca"),
    dict(slug="soyte_dichbenh_16_23_10_2026",
         url="https://soyte.hanoi.gov.vn/y-te-du-phong-65152/tinh-hinh-dich-benh-tren-dia-ban-thanh-pho-ha-noi-tu-ngay-16-10-den-ngay-23-10-2849261026135314557.htm",
         title="Tình hình dịch bệnh trên địa bàn thành phố Hà Nội từ ngày 16/10 đến ngày 23/10",
         publisher="CDC Hà Nội / Sở Y tế TP Hà Nội", published="2026-10-27", category="official",
         used_for="Sởi cộng dồn 2026 đến 23/10: 412 ca tại 113 phường xã (bối cảnh dịch tả học)"),
    dict(slug="soyte_dichbenh_2_9_10_2026",
         url="https://soyte.hanoi.gov.vn/hoat-dong-nganh/tinh-hinh-dich-benh-tren-dia-ban-thanh-pho-ha-noi-tu-ngay-2-10-den-ngay-9-10-2849261011211143415.htm",
         title="Tình hình dịch bệnh trên địa bàn thành phố Hà Nội từ ngày 2/10 đến ngày 9/10",
         publisher="CDC Hà Nội / Sở Y tế TP Hà Nội", published="2026-10-12", category="official",
         used_for="Tuần báo 2-9/10/2026 (chỉ sốt xuất huyết, không nêu sởi) - bối cảnh"),
    dict(slug="press_tapchicongthuong_dot1_2024",
         url="https://tapchicongthuong.vn/ha-noi-trien-khai-chien-dich-tiem-vac-xin-phong-benh-soi-cho-tre-128150.htm",
         title="Hà Nội triển khai chiến dịch tiêm vắc xin phòng bệnh sởi cho trẻ",
         publisher="Tạp chí Công thương (báo chí bổ sung)", published="2024-10-14",
         category="press_supplementary",
         used_for="Vắc xin MRVAC; lịch sử sởi Hà Nội 2014/2019/2020-2023 (bổ sung)"),
    dict(slug="press_baomoi_chien-dich-soi",
         url="https://baomoi.com/ha-noi-trien-khai-chien-dich-tiem-vac-xin-phong-benh-soi-cho-tre-c50446009.epi",
         title="Hà Nội triển khai chiến dịch tiêm vắc xin phòng bệnh sởi cho trẻ (trang chuyển hướng)",
         publisher="Báo Mới (tổng hợp từ Tạp chí Công thương)", published="2024-10-14",
         category="press_supplementary",
         used_for="Chuỗi dẫn nguồn báo chí -> bài gốc tapchicongthuong.vn"),
]

# Nguồn chính thức đã cố tải nhưng MẠNG ĐẠT ĐẠT bị chặn (timeout) từ môi trường thu thập.
UNREACHABLE_SOURCES = [
    dict(slug="hanoicdc_dot3_2025",
         url="https://hanoicdc.gov.vn/2135n/ha-noi-trien-khai-hieu-qua-chien-dich-tiem-chung-vac-xin-soi-dot-3-nam-2025.html",
         title="Hà Nội triển khai hiệu quả chiến dịch tiêm chủng vắc xin sởi đợt 3 năm 2025",
         publisher="CDC Hà Nội", category="official",
         note="HTTP & HTTPS đều timeout >=30s từ môi trường thu thập (geo/firewall); cùng nội dung có bản sao tại soyte.hanoi.gov.vn (slug soyte_dot3_ketqua_2025)"),
]

# ---------------------------------------------------------------------------
# CƠ SỞ / ĐIỂM TIÊM đã được nêu tên (facility records). KHÔNG suy ra từ danh mục cơ sở.
# ---------------------------------------------------------------------------
FACILITIES = [
    dict(facility_id="F01", facility_name="Trạm y tế phường Vĩnh Tuy",
         facility_type="trạm y tế phường (điểm tiêm thường xuyên)", ward="phường Vĩnh Tuy",
         district="quận Hai Bà Trưng", city="Hà Nội", campaign_id="C2",
         role="điểm tiêm chiến dịch sởi 6 tháng - dưới 9 tháng tuổi, ngày 17/2/2025",
         count_value="241", count_unit="trẻ/đối tượng diện tiêm",
         count_type="planned_target", count_as_of="2025-02-17",
         source_slug="soyte_lanhdao_kiemtra_6thang9thang",
         quote="Qua rà soát, chiến dịch này trên địa bàn phường có 241 đối tượng trẻ từ đủ 6 tháng đến dưới 9 tháng tuổi tiêm vắc xin phòng bệnh sởi.",
         notes="Ngày đầu trạm mời tiêm cho hơn 30 đối tượng (số đã tiêm ngày đầu không nêu)."),
    dict(facility_id="F02", facility_name="TTYT quận Hai Bà Trưng (đơn vị tổ chức)",
         facility_type="trung tâm y tế quận", ward="", district="quận Hai Bà Trưng",
         city="Hà Nội", campaign_id="C2",
         role="đơn vị lập kế hoạch chiến dịch sởi quận, triển khai 17-28/2/2025",
         count_value="1000", count_unit="đối tượng diện tiêm (ước tính 'gần 1000')",
         count_type="planned_target", count_as_of="2025-02-17",
         source_slug="soyte_lanhdao_kiemtra_6thang9thang",
         quote="Qua rà soát, trên địa bàn quận dự kiến có gần 1000 đối tượng trong diện tiêm.",
         notes=""),
    dict(facility_id="F03", facility_name="15 trạm y tế phường trên địa bàn quận Hai Bà Trưng (không nêu tên từng trạm)",
         facility_type="mạng lưới trạm y tế phường", ward="", district="quận Hai Bà Trưng",
         city="Hà Nội", campaign_id="C2",
         role="tiêm đồng loạt 17-28/2/2025 cho trẻ đủ 6 tháng - dưới 9 tháng",
         count_value="", count_unit="", count_type="", count_as_of="",
         source_slug="soyte_lanhdao_kiemtra_6thang9thang",
         quote="Từ ngày 17-28/2, quận triển khai tiêm cho trẻ đủ 6 tháng đến dưới 9 tháng tuổi đồng loạt tại 15 trạm y tế phường.",
         notes="Số đối tượng từng trạm không công bố."),
    dict(facility_id="F04", facility_name="Điểm tiêm phường Quỳnh Mai (trạm y tế phường Quỳnh Mai)",
         facility_type="điểm tiêm chủng cố định", ward="phường Quỳnh Mai",
         district="quận Hai Bà Trưng", city="Hà Nội", campaign_id="C2",
         role="điểm tiêm vét chiến dịch sau 28/2/2025",
         count_value="", count_unit="", count_type="", count_as_of="",
         source_slug="soyte_lanhdao_kiemtra_6thang9thang",
         quote="triển khai tiêm tại 2 điểm tiêm phường Quỳnh Mai và phường Đồng Nhân",
         notes=""),
    dict(facility_id="F05", facility_name="Điểm tiêm phường Đồng Nhân (trạm y tế phường Đồng Nhân)",
         facility_type="điểm tiêm chủng cố định", ward="phường Đồng Nhân",
         district="quận Hai Bà Trưng", city="Hà Nội", campaign_id="C2",
         role="điểm tiêm vét chiến dịch sau 28/2/2025",
         count_value="", count_unit="", count_type="", count_as_of="",
         source_slug="soyte_lanhdao_kiemtra_6thang9thang",
         quote="triển khai tiêm tại 2 điểm tiêm phường Quỳnh Mai và phường Đồng Nhân",
         notes=""),
    dict(facility_id="F06", facility_name="Trạm y tế phường Dịch Vọng",
         facility_type="trạm y tế phường (điểm tiêm thường xuyên)", ward="phường Dịch Vọng",
         district="quận Cầu Giấy", city="Hà Nội", campaign_id="C2",
         role="điểm tiêm chiến dịch sởi từ 17/2/2025",
         count_value="33", count_unit="trẻ đã tiêm (trong 75 trẻ diện tiêm)",
         count_type="actual_administered", count_as_of="2025-03-21",
         source_slug="soyte_rasoat_6den9thang_2025",
         quote="Thống kê trên địa bàn phường có 75 trẻ từ 6 tháng đến dưới 9 tháng tuổi trong diện được tiêm trong chiến dịch. Kể từ ngày 17/2 đến nay, đã có 33 trẻ được tiêm vắc xin sởi an toàn.",
         notes="75 trẻ diện tiêm là planned_target của phường."),
    dict(facility_id="F07", facility_name="Trạm y tế phường Kim Liên",
         facility_type="trạm y tế phường", ward="phường Kim Liên",
         district="quận Đống Đa", city="Hà Nội", campaign_id="C2",
         role="điểm tiêm chiến dịch sởi (kiểm tra ngày 24/3/2025)",
         count_value="24", count_unit="trẻ đã tiêm (trong 65 trẻ đủ điều kiện)",
         count_type="actual_administered", count_as_of="2025-03-24",
         source_slug="soyte_kiemtra_dongda_hoankiem_2025",
         quote="trên địa bàn phường có tổng số 65 trẻ từ 6 đến dưới 9 tháng tuổi đủ điều kiện tiêm phòng sởi. Đến nay, trạm đã tiêm được cho 24 trẻ",
         notes=""),
    dict(facility_id="F08", facility_name="Mạng điểm tiêm quận Hoàn Kiếm (không nêu từng điểm)",
         facility_type="mạng lưới điểm tiêm", ward="", district="quận Hoàn Kiếm",
         city="Hà Nội", campaign_id="C2",
         role="tiêm chiến dịch sởi 6 tháng - dưới 9 tháng",
         count_value="88", count_unit="trẻ đã tiêm (trong 116 trẻ độ tuổi cần tiêm)",
         count_type="actual_administered", count_as_of="2025-03-24",
         source_slug="soyte_kiemtra_dongda_hoankiem_2025",
         quote="Tại quận Hoàn Kiếm, có 116 trẻ nằm trong độ tuổi cần tiêm phòng sởi, trong đó 88 trẻ đã được tiêm, 3 trẻ đang sốt chưa đủ điều kiện tiêm và 25 trẻ đã đồng ý tiêm vào sáng ngày 26/3.",
         notes=""),
    dict(facility_id="F09", facility_name="Trạm y tế thị trấn Kim Bài",
         facility_type="trạm y tế thị trấn", ward="thị trấn Kim Bài",
         district="huyện Thanh Oai", city="Hà Nội", campaign_id="C2",
         role="điểm tiêm chiến dịch (địa điểm kiểm tra đảm bảo vắc xin, 2/2025)",
         count_value="", count_unit="", count_type="", count_as_of="2025-02-12",
         source_slug="soyte_kehoach261_2025_6thang_9thang",
         quote="Lãnh đạo TTYT Thanh Oai kiểm tra công tác đảm bảo vác xin tại trạm y tế thị trấn Kim Bài.",
         notes="Bằng chứng là chú thích ảnh bài báo; không có số liệu tiêm tại đây."),
    dict(facility_id="F10", facility_name="Trạm y tế phường Yên Nghĩa",
         facility_type="trạm y tế phường (điểm tiêm thường xuyên)", ward="phường Yên Nghĩa",
         district="quận Hà Đông", city="Hà Nội", campaign_id="C2",
         role="điểm tiêm vắc xin phòng sởi thường xuyên (ảnh minh họa 16/4/2025)",
         count_value="", count_unit="", count_type="", count_as_of="2025-04-17",
         source_slug="soyte_tangcuong_soi_tcm_2025",
         quote="Người dân đưa trẻ đi tiêm chủng vắc xin phòng sởi tại Trạm y tế phường Yên Nghĩa (quận Hà Đông).",
         notes="Chú thích ảnh; không có số liệu tiêm tại đây."),
    dict(facility_id="F11", facility_name="TTYT quận Long Biên (đơn vị tổ chức)",
         facility_type="trung tâm y tế quận", ward="", district="quận Long Biên",
         city="Hà Nội", campaign_id="C3",
         role="tổ chức chiến dịch tiêm chủng vắc xin sởi đợt 3 (26-29/4/2025)",
         count_value="", count_unit="", count_type="", count_as_of="2025-05-06",
         source_slug="soyte_dot3_ketqua_2025",
         quote="Trung tâm Y tế quận Long Biên tổ chức chiến dịch tiêm chủng vắc xin sởi đợt 3 cho trẻ em trên địa bàn.",
         notes="Chú thích ảnh; không có số liệu riêng của quận."),
    dict(facility_id="F12", facility_name="446 trạm y tế xã/phường/thị trấn toàn thành phố (đợt 3 lần 1, không nêu tên từng trạm)",
         facility_type="mạng lưới trạm y tế", ward="", district="toàn thành phố (30 quận, huyện, thị xã)",
         city="Hà Nội", campaign_id="C3",
         role="điểm tiêm chiến dịch sởi đợt 3 lần 1 (26-29/4/2025)",
         count_value="446", count_unit="điểm tiêm", count_type="facility_count",
         count_as_of="2025-04-29",
         source_slug="soyte_dot3_ketqua_2025",
         quote="Thành phố có tổng số 519 điểm tiêm chủng, trong đó có 446 điểm tại các trạm y tế xã, phường, thị trấn và 73 điểm tiêm tại các trường học.",
         notes=""),
    dict(facility_id="F13", facility_name="73 điểm tiêm tại trường học toàn thành phố (đợt 3 lần 1, không nêu tên trường)",
         facility_type="điểm tiêm tại trường học", ward="", district="toàn thành phố (30 quận, huyện, thị xã)",
         city="Hà Nội", campaign_id="C3",
         role="điểm tiêm chiến dịch sởi đợt 3 lần 1 (26-29/4/2025)",
         count_value="73", count_unit="điểm tiêm", count_type="facility_count",
         count_as_of="2025-04-29",
         source_slug="soyte_dot3_ketqua_2025",
         quote="519 điểm tiêm chủng, trong đó có 446 điểm tại các trạm y tế xã, phường, thị trấn và 73 điểm tiêm tại các trường học",
         notes=""),
]

# ---------------------------------------------------------------------------
# CHIẾN DỊCH / SỰ KIỆN (campaign events)
# ---------------------------------------------------------------------------
CAMPAIGNS = [
    dict(campaign_id="C1", name="Chiến dịch tiêm chủng vắc xin sởi - rubella cho trẻ 1-5 tuổi và nhân viên y tế có nguy cơ (đợt 1, 2024)",
         vaccine="vắc xin sởi - rubella (báo chí nêu loại MRVAC do Trung tâm Nghiên cứu Vaccine và Sinh phẩm Y tế Việt Nam sản xuất)",
         age_group="trẻ 1-5 tuổi; nhân viên y tế có nguy cơ", geography="toàn thành phố Hà Nội",
         start_date="2024-10-14", end_date="", planned_target="57.777 trẻ (1-5 tuổi) + 2.367 nhân viên y tế",
         administered="55.640 trẻ (96,3%) + 2.263 nhân viên y tế (95,6%), tổng 57.903 đối tượng - tính đến 15/11/2024",
         coverage_pct="96,3% (trẻ 1-5 tuổi)", dose_limit="",
         source_slug="soyte_chudong_phongchong_dich_soi_2024; press_tapchicongthuong_dot1_2024",
         quote="từ ngày 14/10/2024, toàn thành phố đã tổ chức triển khai chiến dịch tiêm chủng vắc xin phòng sởi - rubella cho trẻ từ 1-5 tuổi và nhân viên y tế có nguy cơ... Tính đến ngày 15/11/2024, kết quả đã tiêm được 57.903 đối tượng, trong đó: 55.640 đối tượng là trẻ 1-5 tuổi, đạt tỷ lệ 96,3%",
         notes="Rà soát 61.590 trẻ chưa tiêm đủ 2 mũi + 3.813 trẻ tạm hoãn (tiêm vắc xin sống trong 1 tháng trước chiến dịch)."),
    dict(campaign_id="C2", name="Chiến dịch tiêm chủng vắc xin sởi cho trẻ đủ 6 tháng đến dưới 9 tháng tuổi (Kế hoạch 261/KH-KSBT, 2025)",
         vaccine="vắc xin sởi", age_group="trẻ từ đủ 6 tháng đến dưới 9 tháng tuổi (kể cả trẻ vãng lai)",
         geography="100% xã, phường, thị trấn của 30 quận, huyện, thị xã",
         start_date="2025-02-17", end_date="2025-03-31",
         planned_target=">=95% trẻ 6 tháng - dưới 9 tháng tuổi được tiêm 1 mũi",
         administered="", coverage_pct="66% toàn thành phố tính đến 13/3/2025",
         dose_limit="không quá 100 đối tượng/bàn tiêm/buổi cho riêng vắc xin sởi; không quá 50 đối tượng/bàn/buổi nếu tiêm kèm vắc xin khác",
         source_slug="soyte_kehoach261_2025_6thang_9thang; soyte_taptrung_6den9thang; soyte_lanhdao_kiemtra_6thang9thang; soyte_rasoat_6den9thang_2025; soyte_kiemtra_dongda_hoankiem_2025",
         quote="Mục đích của chiến dịch là bảo đảm 95% trẻ từ đủ 6 tháng đến dưới 9 tháng tuổi đang sinh sống trên địa bàn thành phố Hà Nội được tiêm 1 mũi vắc xin phòng bệnh sởi... Tính đến ngày 13/3, tỷ lệ tiêm chủng chiến dịch năm 2025 toàn thành phố đạt 66%.",
         notes="Quận/huyện tỷ lệ thấp (13/3/2025): Đống Đa, Hai Bà Trưng, Nam Từ Liêm, Gia Lâm, Long Biên. Tuần 17-28/2/2025 CDC giám sát tại: Bắc Từ Liêm, Ba Đình, Đông Anh, Hà Đông, Tây Hồ, Mê Linh, Nam Từ Liêm, Phú Xuyên, Sóc Sơn."),
    dict(campaign_id="C3", name="Chiến dịch tiêm chủng vắc xin phòng, chống dịch sởi đợt 3 năm 2025 (kế hoạch của Sở Y tế Hà Nội theo chỉ đạo Bộ Y tế)",
         vaccine="vắc xin sởi (32.500 liều do Bộ Y tế cấp cho lần 1)",
         age_group="trẻ đủ 6 tháng tuổi; trẻ 6 tháng - dưới 9 tháng chưa tiêm; trẻ 11-15 tuổi tại xã/phường nguy cơ cao/rất cao",
         geography="100% xã, phường, thị trấn 30 quận, huyện, thị xã (nhóm 11-15 tuổi chỉ tại đơn vị nguy cơ cao/rất cao)",
         start_date="2025-04-26", end_date="2025-04-29",
         planned_target="từ 95% trẻ thuộc diện tiêm chưa tiêm/đủ mũi được tiêm 1 mũi (lần 2 hoàn thành trước 2025-05-15)",
         administered="lần 1: 30.781 mũi (1.816 + 1.668 + 27.297); 32.500/32.500 liều dùng hết",
         coverage_pct="67,6% (đủ 6 tháng); 75,9% (6-<9 tháng); 92,4% (11-15 tuổi)",
         dose_limit="",
         source_slug="soyte_dot3_den15tuoi_2025; soyte_dot3_ketqua_2025",
         quote="Chiến dịch được triển khai lần 1 từ ngày 26/4 đến ngày 29/4/2025 tại 30 quận, huyện, thị xã... Thành phố có tổng số 519 điểm tiêm chủng... Sử dụng hết 32.500/32.500 liều vắc xin sởi được Bộ Y tế cấp trong đợt 1.",
         notes="Truyền thông 1.368 buổi loa truyền thanh; giám sát tuyến tỉnh 16 lượt, tuyến huyện 439 lượt."),
    dict(campaign_id="C4", name="Chương trình Tiêm chủng mở rộng (TCMR) thường xuyên - 9 tháng 2025 (không phải chiến dịch)",
         vaccine="TCMR: lao (BCG), viêm gan B sơ sinh, DPT-VGB-Hib, bOPV, IPV, sởi, sởi-rubella, viêm não Nhật Bản, Td, uốn ván thai phụ",
         age_group="trẻ em + phụ nữ có thai", geography="toàn thành phố Hà Nội (126 phường/xã mới sau sáp nhập)",
         start_date="2025-01-01", end_date="2025-09-30", planned_target="ke hoach 9T/2025: 71,25% (nhóm vắc xin chính) và 67,5% (nhóm còn lại)",
         administered="", coverage_pct="sởi 81,5%; sởi-rubella 85,3%; ... (xem bảng metrics)",
         dose_limit="", source_slug="soyte_tcmr_2026_2028",
         quote="Thống kê về tỷ lệ tiêm chủng 9 tháng năm 2025... vắc xin sởi đạt tỷ lệ 81,5%... Tỷ lệ tiêm chủng vắc xin sởi - rubella đạt ở tất cả các xã với tỷ lệ chung là 85,3%",
         notes="Đây là tiêm chủng thường xuyên, khác hoàn toàn với số mũi chiến dịch."),
    dict(campaign_id="C5", name="Kế hoạch 279/KH-UBND (09/10/2025): Chương trình TCMR Hà Nội giai đoạn 2026-2028 (kế hoạch)",
         vaccine="TCMR + vắc xin mới (rota dự kiến đưa vào sử dụng từ 2026)",
         age_group="trẻ em + phụ nữ có thai", geography="toàn thành phố Hà Nội",
         start_date="2026-01-01", end_date="2028-12-31",
         planned_target="VGB sơ sinh 24h >=90%; các vắc xin khác >=95%; không có vi rút bại liệt hoang dại; 100% phường xã loại trừ uốn ván sơ sinh",
         administered="", coverage_pct="", dose_limit="",
         source_slug="soyte_tcmr_2026_2028",
         quote="ngày 9/10/2025, UBND thành phố Hà Nội đã ban hành Kế hoạch số 279/KH-UBND về việc triển khai chương trình tiêm chủng mở rộng giai đoạn 2026 - 2028 trên địa bàn thành phố",
         notes="Chỉ là kế hoạch/chỉ tiêu, chưa có số liệu tiêm thực tế giai đoạn này."),
    dict(campaign_id="C6", name="Kế hoạch tiêm chủng thường xuyên năm 2026 của thành phố (11 chỉ tiêu)",
         vaccine="TCMR đầy đủ", age_group="trẻ em + phụ nữ có thai", geography="toàn thành phố Hà Nội",
         start_date="2026-01-01", end_date="2026-12-31",
         planned_target="10/11 chỉ tiêu >=95%; riêng viêm gan B liều sơ sinh trong 24 giờ >=90%; giảm bệnh: sởi dưới 434 ca/năm",
         administered="7 tháng đầu 2026: đạt 55,4%-61,8% tiến độ kế hoạch (số mũi chi tiết trong bảng metrics)",
         coverage_pct="tiến độ 7 tháng 2026: 55,4%-61,8% so với kế hoạch", dose_limit="",
         source_slug="soyte_chitieu_2026",
         quote="trong 7 tháng năm 2026... các chỉ tiêu về tỷ lệ tiêm chủng đều đạt so với tiến độ của kế hoạch với mức đạt từ 55,4% đến 61,8%... Chỉ tiêu kế hoạch về giảm tỷ lệ mắc... bệnh sởi dưới 434 ca; Kết quả giám sát từ đầu năm đến nay... bệnh sởi có 364 ca",
         notes="Tiêm bù 7T/2026: IPV 15.464 mũi; Td 4.044; VNNB 1.942; sởi-rubella MRVAC 509; sởi đơn MVVAX 259; DPT 464; OPV 390; DPT-VGB-Hib 14."),
]

# ---------------------------------------------------------------------------
# SỐ LIỆU (aggregate metrics). value_type phân biệt rõ: actual/ planned/ percent/ cases(bệnh).
# ---------------------------------------------------------------------------
METRICS = [
    # --- Chiến dịch đợt 1 năm 2024 (nguồn: soyte_chudong_phongchong_dich_soi_2024) ---
    dict(metric_id="M01", date_label="14/10/2024 - 15/11/2024 (đợt 1)", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="sởi-rubella", age_group="trẻ 1-5 tuổi",
         value="55640", unit="đối tượng/loại mũi tiêm", value_type="actual_administered",
         source_slug="soyte_chudong_phongchong_dich_soi_2024",
         quote="55.640 đối tượng là trẻ 1-5 tuổi, đạt tỷ lệ 96,3% tổng số đối tượng thuộc diện tiêm chiến dịch",
         notes=""),
    dict(metric_id="M02", date_label="14/10/2024 - 15/11/2024 (đợt 1)", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="sởi-rubella", age_group="nhân viên y tế có nguy cơ",
         value="2263", unit="đối tượng/loại mũi tiêm", value_type="actual_administered",
         source_slug="soyte_chudong_phongchong_dich_soi_2024",
         quote="2.263 đối tượng là nhân viên y tế đạt tỷ lệ 95,6% tổng số đối tượng thuộc diện tiêm chiến dịch",
         notes=""),
    dict(metric_id="M03", date_label="ra soát 2024", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="sởi-rubella", age_group="trẻ 1-5 tuổi",
         value="57777", unit="đối tượng", value_type="planned_target",
         source_slug="soyte_chudong_phongchong_dich_soi_2024",
         quote="tổng số trẻ từ 1-5 tuổi thuộc đối tượng tiêm chiến dịch năm 2024 là 57.777 trẻ",
         notes="= 61.590 trẻ chưa đủ 2 mũi - 3.813 trẻ tạm hoãn"),
    dict(metric_id="M04", date_label="ra soát 2024", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="sởi-rubella", age_group="nhân viên y tế",
         value="2367", unit="đối tượng", value_type="planned_target",
         source_slug="soyte_chudong_phongchong_dich_soi_2024",
         quote="tổng số nhân viên y tế chưa tiêm đủ 2 mũi vắc xin Sởi thuộc đối tượng tiêm chiến dịch là 2.367 người",
         notes=""),
    # --- Chiến dịch C2: bao phủ 13/3/2025 (nguồn: soyte_taptrung_6den9thang) ---
    dict(metric_id="M05", date_label="tính đến 13/3/2025", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="sởi", age_group="trẻ đủ 6 tháng - dưới 9 tháng tuổi",
         value="66", unit="%", value_type="coverage_percent",
         source_slug="soyte_taptrung_6den9thang",
         quote="Tính đến ngày 13/3, tỷ lệ tiêm chủng chiến dịch năm 2025 toàn thành phố đạt 66%.",
         notes="Chỉ số %, không công bố số mũi tuyệt đối"),
    # --- Chiến dịch đợt 3 lần 1, 26-29/4/2025 (nguồn: soyte_dot3_ketqua_2025) ---
    dict(metric_id="M06", date_label="26-29/4/2025 (đợt 3 lần 1)", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="sởi", age_group="trẻ đủ 6 tháng tuổi",
         value="1816", unit="mũi tiêm", value_type="actual_administered",
         source_slug="soyte_dot3_ketqua_2025",
         quote="nhóm trẻ đủ 6 tháng tuổi có 1.816/2.686 (số mũi tiêm/tổng số đối tượng) trẻ được tiêm",
         notes=""),
    dict(metric_id="M07", date_label="26-29/4/2025 (đợt 3 lần 1)", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="sởi", age_group="trẻ đủ 6 tháng tuổi",
         value="2686", unit="đối tượng", value_type="planned_target",
         source_slug="soyte_dot3_ketqua_2025", quote="1.816/2.686 (số mũi tiêm/tổng số đối tượng)",
         notes="mẫu số của tỷ lệ"),
    dict(metric_id="M08", date_label="26-29/4/2025 (đợt 3 lần 1)", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="sởi", age_group="trẻ đủ 6 tháng tuổi",
         value="67.6", unit="%", value_type="coverage_percent",
         source_slug="soyte_dot3_ketqua_2025", quote="đạt tỷ lệ 67,6%", notes=""),
    dict(metric_id="M09", date_label="26-29/4/2025 (đợt 3 lần 1)", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="sởi", age_group="trẻ 6 tháng - dưới 9 tháng",
         value="1668", unit="mũi tiêm", value_type="actual_administered",
         source_slug="soyte_dot3_ketqua_2025",
         quote="Nhóm trẻ từ 6 đến dưới 9 tháng tuổi có 1.668/2.199 trẻ được tiêm", notes=""),
    dict(metric_id="M10", date_label="26-29/4/2025 (đợt 3 lần 1)", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="sởi", age_group="trẻ 6 tháng - dưới 9 tháng",
         value="2199", unit="đối tượng", value_type="planned_target",
         source_slug="soyte_dot3_ketqua_2025", quote="1.668/2.199 trẻ được tiêm", notes="mẫu số"),
    dict(metric_id="M11", date_label="26-29/4/2025 (đợt 3 lần 1)", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="sởi", age_group="trẻ 11-15 tuổi",
         value="27297", unit="mũi tiêm", value_type="actual_administered",
         source_slug="soyte_dot3_ketqua_2025",
         quote="Nhóm trẻ từ 11 đến 15 tuổi có 27.297/29.555 trẻ được tiêm, đạt tỷ lệ 92,4%",
         notes="chỉ tiêm tại xã/phường nguy cơ cao/rất cao"),
    dict(metric_id="M12", date_label="26-29/4/2025 (đợt 3 lần 1)", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="sởi", age_group="trẻ 11-15 tuổi",
         value="29555", unit="đối tượng", value_type="planned_target",
         source_slug="soyte_dot3_ketqua_2025", quote="27.297/29.555 trẻ", notes="mẫu số"),
    dict(metric_id="M13", date_label="26-29/4/2025 (đợt 3 lần 1)", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="sởi", age_group="trẻ 11-15 tuổi",
         value="92.4", unit="%", value_type="coverage_percent",
         source_slug="soyte_dot3_ketqua_2025", quote="đạt tỷ lệ 92,4%", notes=""),
    dict(metric_id="M14", date_label="26-29/4/2025 (đợt 3 lần 1)", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="sởi (liều Bộ Y tế cấp)", age_group="tất cả nhóm chiến dịch",
         value="32500", unit="liều vắc xin", value_type="doses_used",
         source_slug="soyte_dot3_ketqua_2025",
         quote="Sử dụng hết 32.500/32.500 liều vắc xin sởi được Bộ Y tế cấp trong đợt 1.",
         notes="liều đã dùng = liều được cấp (100%)"),
    dict(metric_id="M15", date_label="26-29/4/2025 (đợt 3 lần 1)", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="sởi", age_group="tất cả",
         value="519", unit="điểm tiêm", value_type="facility_count",
         source_slug="soyte_dot3_ketqua_2025",
         quote="Thành phố có tổng số 519 điểm tiêm chủng, trong đó có 446 điểm tại các trạm y tế xã, phường, thị trấn và 73 điểm tiêm tại các trường học.",
         notes="446 TYT + 73 trường học"),
    # --- TCMR 9 tháng 2025 (nguồn: soyte_tcmr_2026_2028) ---
    dict(metric_id="M16", date_label="9 tháng 2025", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="sởi (TCMR)", age_group="trẻ theo lịch TCMR",
         value="81.5", unit="%", value_type="coverage_percent",
         source_slug="soyte_tcmr_2026_2028",
         quote="vắc xin sởi đạt tỷ lệ 81,5% và còn 6 xã chưa đạt yêu cầu", notes="tiêm thường xuyên, không phải chiến dịch"),
    dict(metric_id="M17", date_label="9 tháng 2025", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="sởi-rubella (TCMR)", age_group="trẻ theo lịch TCMR",
         value="85.3", unit="%", value_type="coverage_percent",
         source_slug="soyte_tcmr_2026_2028",
         quote="Tỷ lệ tiêm chủng vắc xin sởi -rubella đạt ở tất cả các xã với tỷ lệ chung là 85,3%", notes=""),
    dict(metric_id="M18", date_label="9 tháng 2025", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="lao/BCG (TCMR)", age_group="trẻ sơ sinh",
         value="71.3", unit="%", value_type="coverage_percent",
         source_slug="soyte_tcmr_2026_2028",
         quote="tỷ lệ tiêm vắc xin lao đạt 71,3%", notes=""),
    dict(metric_id="M19", date_label="9 tháng 2025", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="viêm gan B sơ sinh (TCMR)", age_group="sơ sinh",
         value="70.3", unit="%", value_type="coverage_percent",
         source_slug="soyte_tcmr_2026_2028",
         quote="tỷ lệ tiêm vắc xin viêm gan B sơ sinh 70,3% và 36 xã chưa đạt", notes=""),
    dict(metric_id="M20", date_label="9 tháng 2025", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="DPT-VGB-Hib mũi 3 (TCMR)", age_group="trẻ nhỏ",
         value="82", unit="%", value_type="coverage_percent",
         source_slug="soyte_tcmr_2026_2028",
         quote="DPT-VGB-Hib mũi 3 là 82%", notes=""),
    dict(metric_id="M21", date_label="9 tháng 2025", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="bOPV lần 3 (TCMR)", age_group="trẻ nhỏ",
         value="10.4", unit="%", value_type="coverage_percent",
         source_slug="soyte_tcmr_2026_2028",
         quote="Với chỉ tiêu tiêm vắc xin bOPV lần 3, cả thành phố không đạt được chỉ tiêu kế hoạch, cụ thể là chỉ đạt 10,4%",
         notes="chỉ tiêu duy nhất KHÔNG đạt; chỉ xã Ứng Thiên đạt 83,2%"),
    dict(metric_id="M22", date_label="9 tháng 2025", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="IPV mũi 2 (TCMR)", age_group="trẻ nhỏ",
         value="71.3", unit="%", value_type="coverage_percent",
         source_slug="soyte_tcmr_2026_2028",
         quote="Tỷ lệ tiêm vắc xin IPV mũi 2 đạt 71,3% nhưng vẫn còn 35/126 xã chưa đạt",
         notes=""),
    dict(metric_id="M23", date_label="9 tháng 2025", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="DPT mũi 4 (TCMR)", age_group="trẻ trên 1 tuổi",
         value="77.3", unit="%", value_type="coverage_percent",
         source_slug="soyte_tcmr_2026_2028", quote="DPT mũi 4 đạt 77,3%", notes=""),
    dict(metric_id="M24", date_label="9 tháng 2025", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="viêm não Nhật Bản mũi 2 (TCMR)",
         age_group="trẻ em",
         value="75.3", unit="%", value_type="coverage_percent",
         source_slug="soyte_tcmr_2026_2028",
         quote="viêm não Nhật Bản mũi 2 đạt 75,3%",
         notes=""),
    dict(metric_id="M24b", date_label="9 tháng 2025", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="viêm não Nhật Bản mũi 3 (TCMR)",
         age_group="trẻ em",
         value="72.8", unit="%", value_type="coverage_percent",
         source_slug="soyte_tcmr_2026_2028",
         quote="Tỷ lệ tiêm vắc xin viêm não Nhật Bản mũi 3 đạt 72,8%",
         notes=""),
    dict(metric_id="M25", date_label="9 tháng 2025", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="Td trẻ 7 tuổi (TCMR)", age_group="trẻ 7 tuổi",
         value="67.5", unit="%", value_type="coverage_percent",
         source_slug="soyte_tcmr_2026_2028", quote="Td cho trẻ 7 tuổi 67,5%", notes=""),
    dict(metric_id="M26", date_label="9 tháng 2025", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="uốn ván thai phụ (TCMR)", age_group="phụ nữ có thai",
         value="77.4", unit="%", value_type="coverage_percent",
         source_slug="soyte_tcmr_2026_2028",
         quote="vắc xin uốn ván cho phụ nữ có thai 77,4%", notes=""),
    # --- TCMR 7 tháng 2026 (nguồn: soyte_chitieu_2026) ---
    dict(metric_id="M27", date_label="7 tháng đầu 2026 (đến hết tháng 7)", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="viêm gan B sơ sinh trong 24h", age_group="trẻ dưới 1 tuổi",
         value="53210", unit="trẻ được tiêm (55,7% của 95.586 trẻ diện)", value_type="actual_administered",
         source_slug="soyte_chitieu_2026",
         quote="toàn thành phố đã tổ chức tiêm vắc xin viêm gan B trong vòng 24 giờ sau sinh là 53.210 trẻ, đạt 55,7%",
         notes=""),
    dict(metric_id="M28", date_label="7 tháng đầu 2026", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="BCG", age_group="trẻ dưới 1 tuổi",
         value="54555", unit="trẻ (57,1%)", value_type="actual_administered",
         source_slug="soyte_chitieu_2026",
         quote="Tỷ lệ tiêm vắc xin BCG đạt 57,1% với 54.555 trẻ được tiêm", notes=""),
    dict(metric_id="M29a", date_label="7 tháng đầu 2026", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="DPT-VGB-Hib mũi 1", age_group="trẻ dưới 1 tuổi",
         value="56834", unit="trẻ", value_type="actual_administered",
         source_slug="soyte_chitieu_2026",
         quote="mũi 1 là 56.834 trẻ", notes=""),
    dict(metric_id="M29b", date_label="7 tháng đầu 2026", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="DPT-VGB-Hib mũi 2", age_group="trẻ dưới 1 tuổi",
         value="57974", unit="trẻ", value_type="actual_administered",
         source_slug="soyte_chitieu_2026",
         quote="mũi 2 là 57.974 trẻ", notes=""),
    dict(metric_id="M29c", date_label="7 tháng đầu 2026", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="DPT-VGB-Hib mũi 3", age_group="trẻ dưới 1 tuổi",
         value="57349", unit="trẻ (60%)", value_type="actual_administered",
         source_slug="soyte_chitieu_2026",
         quote="mũi 3 là 57.349 trẻ", notes="đạt 60%"),
    dict(metric_id="M30", date_label="7 tháng đầu 2026", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="bại liệt (uống đủ liều)", age_group="trẻ dưới 1 tuổi",
         value="56179", unit="trẻ (58,8%)", value_type="actual_administered",
         source_slug="soyte_chitieu_2026",
         quote="có 56.179 trẻ được tiêm và uống đủ liều, đạt 58,8%", notes=""),
    dict(metric_id="M31", date_label="7 tháng đầu 2026", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="rotavirus (uống)", age_group="trẻ dưới 1 tuổi",
         value="55407", unit="trẻ (58%)", value_type="actual_administered",
         source_slug="soyte_chitieu_2026",
         quote="Có 55.407 trẻ được uống vắc xin rotavirus, đạt 58%", notes="rota đưa vào từ 2026 theo KH 279/KH-UBND"),
    dict(metric_id="M32", date_label="7 tháng đầu 2026", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="sởi mũi 1 (TCMR)", age_group="trẻ dưới 1 tuổi",
         value="55536", unit="trẻ (58,1%)", value_type="actual_administered",
         source_slug="soyte_chitieu_2026",
         quote="55.536 trẻ được tiêm sởi mũi 1, đạt 58,1%", notes=""),
    dict(metric_id="M33", date_label="7 tháng đầu 2026", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="uốn ván sơ sinh (bảo vệ trẻ)", age_group="trẻ dưới 1 tuổi",
         value="54769", unit="trẻ được bảo vệ (57,3%)", value_type="actual_administered",
         source_slug="soyte_chitieu_2026",
         quote="số trẻ được bảo vệ phòng uốn ván sơ sinh là 54.769, đạt 57,3%", notes=""),
    dict(metric_id="M34", date_label="7 tháng đầu 2026", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="sởi - rubella (TCMR)", age_group="trẻ trên 1 tuổi (diện 101.640)",
         value="58657", unit="trẻ (57,7%)", value_type="actual_administered",
         source_slug="soyte_chitieu_2026",
         quote="số trẻ được tiêm vắc xin sởi - rubella là 58.657, đạt 57,7%", notes=""),
    dict(metric_id="M35", date_label="7 tháng đầu 2026", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="DPT4 (bạch hầu - ho gà - uốn ván mũi 4)",
         age_group="trẻ trên 1 tuổi (diện 101.640)",
         value="59994", unit="trẻ (59%)", value_type="actual_administered",
         source_slug="soyte_chitieu_2026",
         quote="có 59.994 trẻ được tiêm vắc xin DPT4 (bạch hầu – ho gà – uốn ván mũi 4), đạt 59%", notes=""),
    dict(metric_id="M36a", date_label="7 tháng đầu 2026", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="viêm não Nhật Bản mũi 1 (TCMR)",
         age_group="trẻ em (diện 94.974)",
         value="57364", unit="trẻ (60,4%)", value_type="actual_administered",
         source_slug="soyte_chitieu_2026",
         quote="mũi 1 là 57.364/94.974 trẻ, đạt 60,4%", notes=""),
    dict(metric_id="M36b", date_label="7 tháng đầu 2026", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="viêm não Nhật Bản mũi 2 (TCMR)",
         age_group="trẻ em",
         value="57627", unit="trẻ (60,7%)", value_type="actual_administered",
         source_slug="soyte_chitieu_2026",
         quote="mũi 2 là 57.627 trẻ, đạt 60,7%", notes=""),
    dict(metric_id="M36c", date_label="7 tháng đầu 2026", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="viêm não Nhật Bản mũi 3 (TCMR)",
         age_group="trẻ em (diện 104.915)",
         value="64536", unit="trẻ (61,5%)", value_type="actual_administered",
         source_slug="soyte_chitieu_2026",
         quote="mũi 3 là 64.536/104.915 trẻ, đạt 61,5%", notes=""),
    dict(metric_id="M37", date_label="7 tháng đầu 2026", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="Td (bạch hầu - uốn ván)", age_group="trẻ diện 129.487",
         value="71726", unit="trẻ (55,4%)", value_type="actual_administered",
         source_slug="soyte_chitieu_2026",
         quote="Tỷ lệ tiêm vắc xin Td phòng bệnh bạch hầu – uốn ván là 71.726/129.487 trẻ, đạt 55,4%",
         notes=""),
    dict(metric_id="M38", date_label="7 tháng đầu 2026", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="uốn ván thai phụ >=2 mũi", age_group="phụ nữ có thai (diện 95.571)",
         value="59018", unit="người (61,8%)", value_type="actual_administered",
         source_slug="soyte_chitieu_2026",
         quote="Số phụ nữ có thai được tiêm vắc xin phòng uốn ván từ 2 mũi trở lên là 59.018/95.571 người, đạt 61,8%",
         notes=""),
    dict(metric_id="M39", date_label="7 tháng đầu 2026 (tiêm bù)", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="IPV", age_group="trẻ trong độ tuổi",
         value="15464", unit="mũi", value_type="actual_administered",
         source_slug="soyte_chitieu_2026",
         quote="vắc xin tiêm phòng bại liệt IPV (15.464 mũi)", notes="tiêm bù"),
    dict(metric_id="M40", date_label="7 tháng đầu 2026 (tiêm bù)", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="Td", age_group="trẻ trong độ tuổi",
         value="4044", unit="mũi", value_type="actual_administered",
         source_slug="soyte_chitieu_2026",
         quote="vắc xin phòng uốn ván và bạch hầu Td (4044 mũi)", notes="tiêm bù"),
    dict(metric_id="M41", date_label="7 tháng đầu 2026 (tiêm bù)", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="viêm não Nhật Bản", age_group="trẻ trong độ tuổi",
         value="1942", unit="mũi", value_type="actual_administered",
         source_slug="soyte_chitieu_2026",
         quote="viêm não Nhật Bản (1942 mũi)", notes="tiêm bù"),
    dict(metric_id="M42", date_label="7 tháng đầu 2026 (tiêm bù)", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="sởi-rubella MRVAC", age_group="trẻ trong độ tuổi",
         value="509", unit="mũi", value_type="actual_administered",
         source_slug="soyte_chitieu_2026",
         quote="vắc xin sởi –rubella MRVAC (509 mũi)", notes="tiêm bù"),
    dict(metric_id="M43", date_label="7 tháng đầu 2026 (tiêm bù)", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="sởi đơn MVVAX", age_group="trẻ trong độ tuổi",
         value="259", unit="mũi", value_type="actual_administered",
         source_slug="soyte_chitieu_2026",
         quote="vắc xin sởi đơn MVVAX (259 mũi)", notes="tiêm bù"),
    dict(metric_id="M44", date_label="7 tháng đầu 2026 (tiêm bù)", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="DPT", age_group="trẻ trong độ tuổi",
         value="464", unit="mũi", value_type="actual_administered",
         source_slug="soyte_chitieu_2026", quote="DPT (464 mũi)", notes="tiêm bù"),
    dict(metric_id="M45", date_label="7 tháng đầu 2026 (tiêm bù)", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="OPV (uống)", age_group="trẻ trong độ tuổi",
         value="390", unit="mũi", value_type="actual_administered",
         source_slug="soyte_chitieu_2026", quote="vắc xin uống phòng bại liệt OPV (390 mũi)",
         notes="tiêm bù"),
    dict(metric_id="M46", date_label="7 tháng đầu 2026 (tiêm bù)", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="DPT-VGB-Hib", age_group="trẻ trong độ tuổi",
         value="14", unit="mũi", value_type="actual_administered",
         source_slug="soyte_chitieu_2026", quote="vắc xin DPT-VGB-Hib (14 mũi)", notes="tiêm bù"),
    dict(metric_id="M47", date_label="7 tháng đầu 2026", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="(mẫu số diện tiêm)", age_group="trẻ dưới 1 tuổi",
         value="95586", unit="trẻ diện tiêm TCMR", value_type="planned_target",
         source_slug="soyte_chitieu_2026",
         quote="số trẻ dưới 1 tuổi trong diện được tiêm vắc xin của Chương trình Tiêm chủng mở rộng là 95.586",
         notes="mẫu số các tỷ lệ TCMR <1 tuổi"),
    dict(metric_id="M48", date_label="7 tháng đầu 2026", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="(mẫu số diện tiêm)", age_group="trẻ trên 1 tuổi",
         value="101640", unit="trẻ diện sởi-rubella + DPT4", value_type="planned_target",
         source_slug="soyte_chitieu_2026",
         quote="số trẻ trong độ tuổi được tiêm vắc xin sởi-rubella và DPT4 là 101.640", notes="mẫu số"),
    dict(metric_id="M49", date_label="7 tháng đầu 2026", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="(mẫu số diện tiêm)", age_group="trẻ 7 tuổi",
         value="129487", unit="trẻ diện Td", value_type="planned_target",
         source_slug="soyte_chitieu_2026", quote="Td... là 71.726/129.487 trẻ", notes="mẫu số"),
    dict(metric_id="M50", date_label="7 tháng đầu 2026", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="(mẫu số diện tiêm)", age_group="phụ nữ có thai",
         value="95571", unit="người diện uốn ván", value_type="planned_target",
         source_slug="soyte_chitieu_2026",
         quote="59.018/95.571 người", notes="mẫu số"),
    # --- BỐI CẢNH BỆNH SỞI (KHÔNG phải số mũi tiêm; dùng cho phân bố dịch) ---
    dict(metric_id="M51", date_label="01/01 - 22/11/2024", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="(bệnh sởi, không phải mũi tiêm)",
         age_group="tất cả", value="115", unit="ca mắc xác định",
         value_type="disease_cases_context",
         source_slug="soyte_chudong_phongchong_dich_soi_2024",
         quote="từ 01/01-22/11/2024, toàn thành phố đã ghi nhận 115 trường hợp sởi xác định. Bệnh nhân ghi nhận tại 88/579 xã phường thị trấn tại 25/30 quận, huyện, thị xã",
         notes="88/579 XPTT; ~40% ca liên quan lây bệnh viện; dưới 1 tuổi 43,5%; chưa tiêm đủ 91%"),
    dict(metric_id="M52", date_label="năm 2024", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="(bệnh sởi)", age_group="tất cả",
         value="570", unit="ca mắc", value_type="disease_cases_context",
         source_slug="soyte_taptrung_6den9thang",
         quote="năm 2024 có 570 ca và hơn 2 tháng đầu năm 2025 có 876 ca", notes="lũy tích từ 2024 đến 14/3/2025 là 1.446 ca"),
    dict(metric_id="M53", date_label="cộng dồn 2025 đến 14/2/2025", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="(bệnh sởi)", age_group="tất cả",
         value="441", unit="ca mắc tại 30/30 quận huyện", value_type="disease_cases_context",
         source_slug="soyte_quanhuyen_trienkhai_6thang9thang",
         quote="Cộng dồn năm 2025 ghi nhận 441 trường hợp tại 30/30 quận, huyện, thị xã, 0 tử vong",
         notes="47 ca dưới 6 tháng; 56 ca 6-8 tháng; 45 ca 9-11 tháng; 110 ca 1-5 tuổi; 74 ca 6-10 tuổi; 109 ca >10 tuổi"),
    dict(metric_id="M54", date_label="lũy tích 2024 đến 14/3/2025", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="(bệnh sởi)", age_group="tất cả",
         value="1446", unit="ca mắc tại 377 XPTT của 30/30 quận huyện",
         value_type="disease_cases_context",
         source_slug="soyte_taptrung_6den9thang; soyte_rasoat_6den9thang_2025",
         quote="Lũy tích từ năm 2024 đến ngày 14/3/2025, toàn thành phố ghi nhận 1.446 trường hợp mắc sởi",
         notes="2 nguồn trùng số -> đã gộp một dòng"),
    dict(metric_id="M55", date_label="đến hết ngày 13/4/2025", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="(bệnh sởi)", age_group="tất cả",
         value="1700", unit="ca (gần 1.700, số gần đúng)", value_type="disease_cases_context",
         source_slug="soyte_tangcuong_soi_tcm_2025",
         quote="tính đến hết ngày 13/4/2025, toàn thành phố đã ghi nhận gần 1.700 trường hợp mắc sởi, số ca mắc theo tuần chưa có xu hướng giảm (trung bình 200 ca mắc/tuần)",
         notes="1 ca tử vong liên quan sởi trên người nhiều bệnh nền"),
    dict(metric_id="M56", date_label="đầu năm 2026 đến 11/9/2026", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="(bệnh sởi)", age_group="tất cả",
         value="364", unit="ca mắc", value_type="disease_cases_context",
         source_slug="soyte_chitieu_2026",
         quote="bệnh sởi có 364 ca và ho gà là 87 ca (chỉ tiêu 2026: sởi dưới 434 ca)",
         notes="không có ca bại liệt, uốn ván sơ sinh, bạch hầu"),
    dict(metric_id="M57", date_label="cộng dồn 2026 đến 23/10/2026", geography="toàn thành phố Hà Nội",
         geography_level="thành phố", vaccine="(bệnh sởi)", age_group="tất cả",
         value="412", unit="ca mắc tại 113 phường, xã", value_type="disease_cases_context",
         source_slug="soyte_dichbenh_16_23_10_2026",
         quote="cộng dồn năm 2026 ghi nhận 412 trường hợp tại 113 phường, xã, 0 ca tử vong",
         notes="tuần 16-23/10/2026 chỉ 4 ca mới"),
    # --- Phân bố bệnh sởi theo QUẬN/HUYỆN (lũy tích 2024 -> 14/3/2025; nguồn trùng nhau đã gộp 1 slug chính) ---
    dict(metric_id="M58", date_label="lũy tích 2024 đến 14/3/2025", geography="quận Hoàng Mai",
         geography_level="quận", vaccine="(bệnh sởi)", age_group="tất cả",
         value="221", unit="ca", value_type="disease_cases_context",
         source_slug="soyte_taptrung_6den9thang",
         quote="quận Hoàng Mai đứng đầu với 221 ca", notes="cao nhất thành phố"),
    dict(metric_id="M59", date_label="lũy tích 2024 đến 14/3/2025", geography="quận Hà Đông",
         geography_level="quận", vaccine="(bệnh sởi)", age_group="tất cả",
         value="100", unit="ca", value_type="disease_cases_context",
         source_slug="soyte_taptrung_6den9thang", quote="tiếp đến là Hà Đông với 100 ca", notes=""),
    dict(metric_id="M60", date_label="lũy tích 2024 đến 14/3/2025", geography="huyện Thanh Trì",
         geography_level="quận", vaccine="(bệnh sởi)", age_group="tất cả",
         value="93", unit="ca", value_type="disease_cases_context",
         source_slug="soyte_taptrung_6den9thang", quote="Thanh Trì 93 ca", notes=""),
    dict(metric_id="M61", date_label="lũy tích 2024 đến 14/3/2025", geography="quận Nam Từ Liêm",
         geography_level="quận", vaccine="(bệnh sởi)", age_group="tất cả",
         value="90", unit="ca", value_type="disease_cases_context",
         source_slug="soyte_taptrung_6den9thang", quote="Nam Từ Liêm 90 ca", notes=""),
    dict(metric_id="M62", date_label="lũy tích 2024 đến 14/3/2025", geography="quận Đống Đa",
         geography_level="quận", vaccine="(bệnh sởi)", age_group="tất cả",
         value="85", unit="ca", value_type="disease_cases_context",
         source_slug="soyte_taptrung_6den9thang", quote="Đống Đa 85 ca", notes=""),
    dict(metric_id="M63", date_label="lũy tích 2024 đến 14/3/2025", geography="quận Tây Hồ",
         geography_level="quận", vaccine="(bệnh sởi)", age_group="tất cả",
         value="71", unit="ca", value_type="disease_cases_context",
         source_slug="soyte_taptrung_6den9thang", quote="Tây Hồ 71 ca", notes=""),
    dict(metric_id="M64", date_label="lũy tích 2024 đến 14/3/2025", geography="quận Hoàn Kiếm",
         geography_level="quận", vaccine="(bệnh sởi)", age_group="tất cả",
         value="66", unit="ca", value_type="disease_cases_context",
         source_slug="soyte_taptrung_6den9thang", quote="Hoàn Kiếm 66 ca", notes=""),
    dict(metric_id="M65", date_label="lũy tích 2024 đến 14/3/2025", geography="huyện Thường Tín",
         geography_level="quận", vaccine="(bệnh sởi)", age_group="tất cả",
         value="62", unit="ca", value_type="disease_cases_context",
         source_slug="soyte_taptrung_6den9thang", quote="Thường Tín 62 ca", notes=""),
    dict(metric_id="M66", date_label="lũy tích 2024 đến 14/3/2025", geography="quận Ba Đình",
         geography_level="quận", vaccine="(bệnh sởi)", age_group="tất cả",
         value="60", unit="ca", value_type="disease_cases_context",
         source_slug="soyte_taptrung_6den9thang", quote="Ba Đình 60 ca", notes=""),
    # --- Phân bố bệnh sởi theo quận 2024 (1/1-22/11/2024, mốc khác với M58-M66, KHÔNG gộp) ---
    dict(metric_id="M67", date_label="01/01 - 22/11/2024", geography="quận Hoàng Mai",
         geography_level="quận", vaccine="(bệnh sởi)", age_group="tất cả",
         value="19", unit="ca", value_type="disease_cases_context",
         source_slug="soyte_chudong_phongchong_dich_soi_2024",
         quote="Hoàng Mai ghi nhận số bệnh nhân nhiều nhất với 19 ca", notes="mốc thời gian khác M58, không gộp"),
    dict(metric_id="M68", date_label="01/01 - 22/11/2024", geography="quận Ba Đình",
         geography_level="quận", vaccine="(bệnh sởi)", age_group="tất cả",
         value="9", unit="ca", value_type="disease_cases_context",
         source_slug="soyte_chudong_phongchong_dich_soi_2024",
         quote="quận Ba Đình ghi nhận 9 ca", notes=""),
    dict(metric_id="M69", date_label="01/01 - 22/11/2024", geography="huyện Thanh Trì",
         geography_level="quận", vaccine="(bệnh sởi)", age_group="tất cả",
         value="8", unit="ca", value_type="disease_cases_context",
         source_slug="soyte_chudong_phongchong_dich_soi_2024",
         quote="huyện Thanh Trì ghi nhận 8 ca", notes=""),
    # --- Phân bố diện tiêm theo PHƯỜNG/QUẬN trong chiến dịch C2 (2025) ---
    dict(metric_id="M70", date_label="17/2/2025", geography="phường Vĩnh Tuy, quận Hai Bà Trưng",
         geography_level="phường", vaccine="sởi", age_group="trẻ đủ 6 tháng - dưới 9 tháng",
         value="241", unit="đối tượng diện tiêm", value_type="planned_target",
         source_slug="soyte_lanhdao_kiemtra_6thang9thang",
         quote="chiến dịch này trên địa bàn phường có 241 đối tượng trẻ từ đủ 6 tháng đến dưới 9 tháng tuổi",
         notes="chỉ dẫn bởi bảng cơ sở F01"),
    dict(metric_id="M71", date_label="17/2/2025", geography="quận Hai Bà Trưng (toàn quận)",
         geography_level="quận", vaccine="sởi", age_group="trẻ đủ 6 tháng - dưới 9 tháng",
         value="1000", unit="đối tượng diện tiêm (ước tính 'gần 1000')",
         value_type="planned_target",
         source_slug="soyte_lanhdao_kiemtra_6thang9thang",
         quote="trên địa bàn quận dự kiến có gần 1000 đối tượng trong diện tiêm", notes=""),
    dict(metric_id="M72", date_label="17/2 - 21/3/2025", geography="phường Dịch Vọng, quận Cầu Giấy",
         geography_level="phường", vaccine="sởi", age_group="trẻ đủ 6 tháng - dưới 9 tháng",
         value="33", unit="trẻ đã tiêm", value_type="actual_administered",
         source_slug="soyte_rasoat_6den9thang_2025",
         quote="Kể từ ngày 17/2 đến nay, đã có 33 trẻ được tiêm vắc xin sởi an toàn",
         notes="75 trẻ diện tiêm -> tương đương 44% đến 21/3"),
    dict(metric_id="M73", date_label="đến 24/3/2025", geography="phường Kim Liên, quận Đống Đa",
         geography_level="phường", vaccine="sởi", age_group="trẻ đủ 6 tháng - dưới 9 tháng",
         value="24", unit="trẻ đã tiêm", value_type="actual_administered",
         source_slug="soyte_kiemtra_dongda_hoankiem_2025",
         quote="trạm đã tiêm được cho 24 trẻ", notes="65 trẻ đủ điều kiện"),
    dict(metric_id="M74", date_label="đến 24/3/2025", geography="quận Đống Đa (toàn quận)",
         geography_level="quận", vaccine="sởi", age_group="trẻ đủ 6 tháng - dưới 9 tháng",
         value="744", unit="trẻ trong độ tuổi tiêm chủng", value_type="planned_target",
         source_slug="soyte_kiemtra_dongda_hoankiem_2025",
         quote="toàn quận Đống Đa có 744 trẻ trong độ tuổi tiêm chủng phòng bệnh sởi",
         notes="quận có tỷ lệ chiến dịch thấp (13/3/2025)"),
    dict(metric_id="M75", date_label="đến 24/3/2025", geography="quận Hoàn Kiếm (toàn quận)",
         geography_level="quận", vaccine="sởi", age_group="trẻ đủ 6 tháng - dưới 9 tháng",
         value="88", unit="trẻ đã tiêm (trong 116 trẻ diện)", value_type="actual_administered",
         source_slug="soyte_kiemtra_dongda_hoankiem_2025",
         quote="Tại quận Hoàn Kiếm, có 116 trẻ nằm trong độ tuổi cần tiêm phòng sởi, trong đó 88 trẻ đã được tiêm",
         notes=""),
]

# ---------------------------------------------------------------------------
# XỬ LÝ
# ---------------------------------------------------------------------------
SCHEMA = {
    "sources_provenance.csv": [
        "source_slug", "title", "publisher", "url", "category", "published",
        "retrieval_date", "http_status", "bytes", "sha256", "used_for", "note"],
    "vaccination_facilities.csv": [
        "facility_id", "facility_name", "facility_type", "ward", "district", "city",
        "campaign_id", "role", "count_value", "count_unit", "count_type",
        "count_as_of", "source_slug", "quote", "notes"],
    "vaccination_campaign_events.csv": [
        "campaign_id", "name", "vaccine", "age_group", "geography", "start_date",
        "end_date", "planned_target", "administered", "coverage_pct", "dose_limit",
        "source_slug", "quote", "notes"],
    "vaccination_administered_metrics.csv": [
        "metric_id", "date_label", "geography", "geography_level", "vaccine",
        "age_group", "value", "unit", "value_type", "source_slug", "quote", "notes"],
}

VALID_VALUE_TYPES = {
    "actual_administered", "planned_target", "coverage_percent", "doses_used",
    "facility_count", "disease_cases_context"}
VALID_COUNT_TYPES = {"", "planned_target", "actual_administered", "facility_count"}


def _norm(s):
    return s.replace(".", "").replace(",", ".").strip()


def _is_num(s):
    try:
        float(_norm(s))
        return True
    except ValueError:
        return False


def fetch_sources():
    os.makedirs(RAW_DIR, exist_ok=True)
    rows, failures = [], 0
    manifest_path = os.path.join(RAW_DIR, "fetch_manifest.csv")
    for src in SOURCES + UNREACHABLE_SOURCES:
        slug, url = src["slug"], src["url"]
        status, nbytes, sha = "error", "0", ""
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            t0 = time.time()
            with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_S) as r:
                data = r.read()
                status = str(getattr(r, "status", 200))
            nbytes = str(len(data))
            sha = hashlib.sha256(data).hexdigest()
            with open(os.path.join(RAW_DIR, slug + ".html"), "wb") as f:
                f.write(data)
            print(f"[fetch] OK   {slug} {status} {nbytes}B ({time.time()-t0:.1f}s)")
        except Exception as e:  # timeout, HTTP, geo-block -> ghi lại và đi tiếp
            status = f"unreachable ({type(e).__name__})"
            failures += 1
            print(f"[fetch] FAIL {slug} {status}: {e}")
        rows.append(dict(slug=slug, url=url, fetched_at_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                         status=status, bytes=nbytes, sha256=sha))
        time.sleep(1)
    _write_csv(manifest_path, ["slug", "url", "fetched_at_utc", "status", "bytes", "sha256"], rows)
    print(f"[fetch] xong: {len(rows)} nguồn thử, {failures} bị chặn/thất bại (ghi trong fetch_manifest.csv)")
    return failures


class _TextExtractor(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip > 0:
            self.skip -= 1
        if tag in ("p", "div", "br", "li", "tr", "h1", "h2", "h3", "td"):
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def extract_texts():
    import glob as _glob
    n = 0
    for path in _glob.glob(os.path.join(RAW_DIR, "*.html")):
        slug = os.path.basename(path)[:-5]
        txt_path = os.path.join(RAW_DIR, slug + ".txt")
        p = _TextExtractor()
        p.feed(open(path, encoding="utf-8", errors="replace").read())
        p.close()
        text = "\n".join(x for x in re.sub(r"\n\s+", "\n", "".join(p.out)).splitlines(True) if x.strip())
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(text)
        n += 1
    print(f"[extract] {n} file text được làm lại từ html thô")
    return n


def _write_csv(path, header, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:  # UTF-8 BOM cho tiếng Việt
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _raw_stats(slug):
    path = os.path.join(RAW_DIR, slug + ".html")
    if not os.path.exists(path):
        return "", ""
    data = open(path, "rb").read()
    return str(len(data)), hashlib.sha256(data).hexdigest()


def process():
    os.makedirs(PROC_DIR, exist_ok=True)
    # sources_provenance
    prov = []
    for s in SOURCES:
        b, sha = _raw_stats(s["slug"])
        prov.append(dict(source_slug=s["slug"], title=s["title"], publisher=s["publisher"],
                         url=s["url"], category=s["category"], published=s.get("published", ""),
                         retrieval_date=RETRIEVAL_DATE, http_status="200" if b else "not_fetched",
                         bytes=b, sha256=sha, used_for=s["used_for"],
                         note="chính thức" if s["category"] == "official" else "báo chí bổ sung, đánh dấu riêng"))
    for u in UNREACHABLE_SOURCES:
        prov.append(dict(source_slug=u["slug"], title=u["title"], publisher=u["publisher"],
                         url=u["url"], category=u["category"], published="",
                         retrieval_date=RETRIEVAL_DATE, http_status="unreachable_timeout",
                         bytes="", sha256="", used_for="", note=u["note"]))
    _write_csv(os.path.join(PROC_DIR, "sources_provenance.csv"),
               SCHEMA["sources_provenance.csv"], prov)
    _write_csv(os.path.join(PROC_DIR, "vaccination_facilities.csv"),
               SCHEMA["vaccination_facilities.csv"], FACILITIES)
    _write_csv(os.path.join(PROC_DIR, "vaccination_campaign_events.csv"),
               SCHEMA["vaccination_campaign_events.csv"], CAMPAIGNS)
    _write_csv(os.path.join(PROC_DIR, "vaccination_administered_metrics.csv"),
               SCHEMA["vaccination_administered_metrics.csv"], METRICS)
    print(f"[process] ghi {len(prov)} nguồn, {len(FACILITIES)} cơ sở, {len(CAMPAIGNS)} chiến dịch, {len(METRICS)} chỉ số")


def self_check():
    problems, warnings = [], []
    slugs = {s["slug"] for s in SOURCES}

    def read(name):
        path = os.path.join(PROC_DIR, name)
        if not os.path.exists(path):
            problems.append(f"thiếu file {name}")
            return None
        raw = open(path, "rb").read()
        if not raw.startswith(b"\xef\xbb\xbf"):
            problems.append(f"{name}: thiếu UTF-8 BOM")
        rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
        if list(rows[0].keys()) != SCHEMA[name] if rows else True:
            if not rows or list(rows[0].keys()) != SCHEMA[name]:
                problems.append(f"{name}: header sai schema")
        return rows

    prov = read("sources_provenance.csv")
    fac = read("vaccination_facilities.csv")
    camp = read("vaccination_campaign_events.csv")
    met = read("vaccination_administered_metrics.csv")

    # 1) nguồn: >= 10 trang, URL hợp lệ, ngày lấy dạng ISO
    if prov:
        ok = [r for r in prov if r["http_status"] == "200"]
        if len(ok) < 10:
            problems.append(f"chỉ {len(ok)} nguồn tải được (yêu cầu >= 10)")
        for r in prov:
            if not re.match(r"^https?://", r["url"]):
                problems.append(f"URL lỗi: {r['source_slug']}")
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", r["retrieval_date"]):
                problems.append(f"ngày lấy lỗi: {r['source_slug']}")
            if r["category"] not in ("official", "press_supplementary"):
                problems.append(f"category lạ: {r['source_slug']}")
        press = [r for r in prov if r["category"] == "press_supplementary"]
        if not all("bổ sung" in r["note"] for r in press):
            problems.append("nguồn báo chí chưa được đánh dấu riêng")

    # 2) facilities: id duy nhất, count hợp lệ, source_slug có trong nguồn
    if fac:
        ids = [r["facility_id"] for r in fac]
        if len(ids) != len(set(ids)):
            problems.append("facility_id bị trùng")
        for r in fac:
            if r["count_value"] and not _is_num(r["count_value"]):
                problems.append(f"count_value không phải số: {r['facility_id']}")
            if r["count_type"] not in VALID_COUNT_TYPES:
                problems.append(f"count_type lạ: {r['facility_id']}")
            if not r["district"] or not r["city"]:
                problems.append(f"thiếu địa hạt: {r['facility_id']}")
            for s in r["source_slug"].split("; "):
                if s and s not in slugs:
                    problems.append(f"source_slug lạ: {r['facility_id']} -> {s}")
            if float(_norm(r["count_value"] or "0")) < 0:
                problems.append(f"count âm: {r['facility_id']}")

    # 3) campaigns: id duy nhất, ngày ISO hoặc trống
    if camp:
        ids = [r["campaign_id"] for r in camp]
        if len(ids) != len(set(ids)):
            problems.append("campaign_id bị trùng")
        for r in camp:
            for d in (r["start_date"], r["end_date"]):
                if d and not re.match(r"^\d{4}-\d{2}-\d{2}$", d):
                    problems.append(f"ngày sai định dạng: {r['campaign_id']} -> {d}")
            for s in r["source_slug"].split("; "):
                if s and s not in slugs:
                    problems.append(f"campaign source_slug lạ: {r['campaign_id']} -> {s}")

    # 4) metrics: id duy nhất, giá trị >= 0, value_type hợp lệ, DEDUP theo khoá
    if met:
        ids = [r["metric_id"] for r in met]
        if len(ids) != len(set(ids)):
            problems.append("metric_id bị trùng")
        seen = {}
        for r in met:
            if not _is_num(r["value"]):
                problems.append(f"value không phải số: {r['metric_id']}")
            elif float(_norm(r["value"])) < 0:
                problems.append(f"value âm: {r['metric_id']}")
            if r["value_type"] not in VALID_VALUE_TYPES:
                problems.append(f"value_type lạ: {r['metric_id']}")
            if r["geography_level"] not in ("thành phố", "quận", "phường"):
                problems.append(f"geography_level lạ: {r['metric_id']}")
            if not r["source_slug"]:
                problems.append(f"thiếu nguồn: {r['metric_id']}")
            for s in r["source_slug"].split("; "):
                if s and s not in slugs:
                    problems.append(f"metric source_slug lạ: {r['metric_id']} -> {s}")
            key = (r["date_label"], r["geography"], r["vaccine"], r["age_group"], r["value_type"], r["unit"])
            if key in seen:
                problems.append(f"trùng lặp số liệu: {seen[key]} ~= {r['metric_id']} (khoá {key})")
            seen[key] = r["metric_id"]
        n_admin = sum(1 for r in met if r["value_type"] == "actual_administered")
        print(f"[self-check] số mũi đã tiêm thực tế (actual_administered): {n_admin} chỉ số")

    # 5) bằng chứng thô
    for s in SOURCES:
        path = os.path.join(RAW_DIR, s["slug"] + ".html")
        if not os.path.exists(path):
            warnings.append(f"chưa có bằng chứng thô: {s['slug']} (chạy --fetch để tải lại)")
        elif os.path.getsize(path) < 1000:
            warnings.append(f"bằng chứng thô quá nhỏ: {s['slug']}")

    print("[self-check] CẢNH BÁO:" if warnings else "[self-check] không có cảnh báo")
    for w in warnings:
        print("  -", w)
    if problems:
        print("[self-check] LỖI:")
        for p in problems:
            print("  -", p)
        raise SystemExit(1)
    print("[self-check] ĐẠT: schema, URL, loại số liệu, dedup, nguồn >= 10 trang đều hợp lệ")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fetch", action="store_true", help="tải lại bằng chứng thô (chấp nhận nguồn bị chặn)")
    ap.add_argument("--extract", action="store_true", help="làm lại file .text từ html thô")
    ap.add_argument("--process", action="store_true", help="dựng lại CSV trong data/processed")
    ap.add_argument("--self-check", dest="self_check", action="store_true", help="kiểm tra dữ liệu")
    args = ap.parse_args()
    any_action = args.fetch or args.extract or args.process or args.self_check
    if args.fetch:
        fetch_sources()
        extract_texts()
    if args.extract:
        extract_texts()
    if args.process:
        process()
    if args.self_check or not any_action:
        process()
        self_check()
    return 0


if __name__ == "__main__":
    sys.exit(main())
