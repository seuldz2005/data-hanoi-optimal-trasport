#!/usr/bin/env python3
"""Generate 2x2 landscape Figure 4 comparison and concise 2-page PDF benchmark report.

Reads saved GeoJSONs and CSV from data/processed/case2/:
  - cui2021_benchmark_summary.csv
  - scenario2_ccvd_zones.geojson
  - scenario2_cui2021_commune_atomic_zones.geojson
  - scenario2_cui2021_grid_adaptive_atomic_zones.geojson
  - scenario2_cui2021_commune_fractional_zones.geojson
Writes:
  - data/processed/case2/figure4_cui2021_comparison.png (2x2 landscape grid)
  - docs/bao_cao_ccdv_revised_cui2021.html
  - docs/bao_cao_ccdv_revised_cui2021.pdf
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402
from shapely import make_valid  # noqa: E402
from shapely.geometry import box  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
CASE2 = REPO / "data" / "processed" / "case2"
DOCS = REPO / "docs"
CRS = 32648
INSETS = {
    "A": (105.80, 21.10, 105.90, 21.17),
    "B": (105.82, 21.00, 105.87, 21.04),
    "C": (105.74, 20.95, 105.80, 21.00),
}
PALETTE = [
    "#66c2a5", "#fc8d62", "#8da0cb", "#e78ac3", "#a6d854", "#ffd92f", "#e5c494",
    "#80b1d3", "#fb8072", "#bebada", "#bc80bd", "#ccebc5", "#ffed6f", "#fdb462",
    "#b3de69", "#4c78b8", "#f0198a", "#d1e8cb", "#fde98a", "#c48fc4",
]


def zone_colors(n: int) -> list[str]:
    rng = np.random.default_rng(42)
    return [PALETTE[i] for i in rng.integers(0, len(PALETTE), n)]


def render_2x2_comparison(
    bnd: gpd.GeoDataFrame,
    schools: gpd.GeoDataFrame,
    rows_by_m: dict,
    out_path: Path,
) -> None:
    insets = {k: gpd.GeoSeries([box(*b)], crs=4326).to_crs(CRS).iloc[0].bounds for k, b in INSETS.items()}
    city = unary_union([make_valid(g).buffer(0) for g in bnd.geometry])
    xmin, ymin, xmax, ymax = bnd.total_bounds

    panels = [
        (
            "(a) Old Buffer-Loop CCVD (Center-Out, ±50m)",
            gpd.read_file(CASE2 / "scenario2_ccvd_zones.geojson").to_crs(CRS),
            rows_by_m["old_ccvd_buffer_center_voronoi"],
            (0, 0),
        ),
        (
            "(b) Revised Cui2021 — V1: 584 Communes Atomic (No Cut)",
            gpd.read_file(CASE2 / "scenario2_cui2021_commune_atomic_zones.geojson").to_crs(CRS),
            rows_by_m["cui2021_commune_atomic"],
            (0, 1),
        ),
        (
            "(c) Revised Cui2021 — V3: Bounded Grid Atomic (p_i ≤ 0.05 q_j)",
            gpd.read_file(CASE2 / "scenario2_cui2021_grid_adaptive_atomic_zones.geojson").to_crs(CRS),
            rows_by_m["cui2021_grid_adaptive_atomic"],
            (1, 0),
        ),
        (
            "(d) Revised Cui2021 — V4: 584 Communes + Left-to-Right Boundary Slice",
            gpd.read_file(CASE2 / "scenario2_cui2021_commune_fractional_zones.geojson").to_crs(CRS),
            rows_by_m["cui2021_commune_fractional"],
            (1, 1),
        ),
    ]

    fig = plt.figure(figsize=(20, 12.2))

    for title, zones_gdf, m_row, (r_idx, c_idx) in panels:
        x_base = 0.01 + c_idx * 0.50
        y_base = 0.51 if r_idx == 0 else 0.03
        w_cell = 0.48
        h_cell = 0.45

        ax = fig.add_axes([x_base, y_base + 0.035, w_cell * 0.63, h_cell - 0.04])
        z = zones_gdf[~zones_gdf.geometry.is_empty].copy()
        z["color"] = zone_colors(len(z))
        z.plot(ax=ax, color=z["color"], edgecolor="#222222", linewidth=0.25)

        valid_geoms = [make_valid(g).buffer(0) for g in z.geometry if g is not None and not g.is_empty]
        covered = unary_union(valid_geoms) if valid_geoms else box(0, 0, 0, 0)
        unassigned_geom = city.difference(covered)
        unassigned_gs = gpd.GeoSeries([unassigned_geom], crs=CRS)
        if not unassigned_geom.is_empty:
            unassigned_gs.plot(ax=ax, facecolor="#d9d9d9", edgecolor="#444444", hatch="////", linewidth=0.35)

        schools.plot(ax=ax, marker="^", color="black", markersize=2.5)
        ax.set_axis_off()
        ax.set_xlim(xmin, xmax)
        ax.set_ylim(ymin - (ymax - ymin) * 0.03, ymax)

        stats_txt = (
            f"Within ±5%: {int(m_row['within_5pct']):,}/{int(m_row['n_schools']):,} ({m_row['pct_within_5pct']:.1f}%)\n"
            f"Empty: {int(m_row['empty_zones'])} | Over >5%: {int(m_row['overloaded_gt_5pct'])}\n"
            f"Unassigned: {int(m_row['unassigned_students']):,} ({m_row['unassigned_area_pct']:.1f}% area)\n"
            f"Mean: {m_row['mean_km']:.2f} km (P90: {m_row['p90_km']:.2f} km) | {m_row['seconds']:.1f}s"
        )
        ax.text(
            0.01,
            0.16,
            stats_txt,
            transform=ax.transAxes,
            fontsize=8.5,
            family="monospace",
            bbox=dict(facecolor="white", alpha=0.93, edgecolor="#1e293b", boxstyle="round,pad=0.35"),
        )
        fig.text(
            x_base + w_cell * 0.48,
            y_base + 0.008,
            title,
            ha="center",
            fontsize=11,
            fontweight="bold",
            family="serif",
        )

        sub_h = (h_cell - 0.045) / 3.0
        for i, (key, (x0, y0, x1, y1)) in enumerate(insets.items()):
            ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, edgecolor="black", lw=1.3))
            ax.text(
                x0, y1, key, fontsize=8, fontweight="bold", ha="left", va="bottom",
                bbox=dict(facecolor="white", edgecolor="black", pad=1.0),
            )
            iax = fig.add_axes([
                x_base + w_cell * 0.64,
                y_base + 0.035 + (2 - i) * sub_h,
                w_cell * 0.34,
                sub_h - 0.008,
            ])
            z.plot(ax=iax, color=z["color"], edgecolor="#222222", linewidth=0.45)
            if not unassigned_geom.is_empty:
                unassigned_gs.plot(ax=iax, facecolor="#d9d9d9", edgecolor="#444444", hatch="////", linewidth=0.35)
            schools.plot(ax=iax, marker="^", color="black", markersize=8)
            iax.set_xlim(x0, x1)
            iax.set_ylim(y0, y1)
            iax.set_xticks([])
            iax.set_yticks([])
            iax.set_xlabel("")
            iax.set_ylabel("")
            for sp in iax.spines.values():
                sp.set_linewidth(1.1)
            iax.text(
                0.03, 0.92, f"Inset {key}", transform=iax.transAxes, fontsize=8.5, fontweight="bold", va="top",
                bbox=dict(facecolor="white", edgecolor="black", pad=1.0),
            )

    fig.savefig(out_path, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Saved 2x2 comparison figure to {out_path}")


def main() -> None:
    df = pd.read_csv(CASE2 / "cui2021_benchmark_summary.csv")
    rows_by_m = {r["method"]: r for _, r in df.iterrows()}

    bnd = gpd.read_file(REPO / "data" / "processed" / "hanoi_boundaries.geojson").to_crs(CRS)
    s = pd.read_csv(CASE2 / "scenario2_schools_age5_14.csv", dtype={"facility_id": str})
    schools = gpd.GeoDataFrame(s, geometry=gpd.points_from_xy(s.longitude, s.latitude), crs=4326).to_crs(CRS)

    fig4_path = CASE2 / "figure4_cui2021_comparison.png"
    render_2x2_comparison(bnd, schools, rows_by_m, fig4_path)

    fig4_uri = fig4_path.resolve().as_uri()

    labels = {
        "voronoi_plain": "1. Traditional Voronoi (Baseline)",
        "old_ccvd_buffer_center_voronoi": "2. Old CCVD (Buffer ±50m, Center-Out)",
        "cui2021_commune_atomic": "3. Cui2021 — V1: 584 Communes Atomic (No Cut)",
        "cui2021_grid500m_atomic": "4. Cui2021 — V2: 500m Uniform Grid Atomic",
        "cui2021_grid_adaptive_atomic": "5. Cui2021 — V3: Bounded Grid Atomic (p_i ≤ 0.05 q_j)",
        "cui2021_commune_fractional": "6. Cui2021 — V4: 584 Communes + L-to-R Slice",
    }

    tr_html = []
    for key, label in labels.items():
        if key not in rows_by_m:
            continue
        r = rows_by_m[key]
        highlight = ' class="highlight"' if key in ("cui2021_grid_adaptive_atomic", "cui2021_commune_fractional") else ""
        warn = ' class="warn"' if key == "cui2021_commune_atomic" else highlight
        tr_html.append(
            f"<tr{warn}>"
            f"<td><b>{label}</b></td>"
            f"<td class='num'><b>{int(r['within_5pct']):,} / {int(r['n_schools']):,}</b> ({r['pct_within_5pct']:.1f}%)</td>"
            f"<td class='num'>{int(r['empty_zones']):,}</td>"
            f"<td class='num'>{int(r['overloaded_gt_5pct']):,}</td>"
            f"<td class='num'>{int(r['max_load']):,}</td>"
            f"<td class='num'>{int(r['unassigned_students']):,}</td>"
            f"<td class='num'>{r['unassigned_area_km2']:.1f} ({r['unassigned_area_pct']:.1f}%)</td>"
            f"<td class='num'>{r['mean_km']:.2f} / {r['median_km']:.2f} / {r['p90_km']:.2f}</td>"
            f"<td class='num'>{r['pct_not_nearest_school']:.1f}%</td>"
            f"<td class='num'>{r['seconds']:.1f}s</td>"
            f"</tr>"
        )
    table_rows = "\n".join(tr_html)

    html = f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<title>Benchmark Revised CCDV (Cui et al., 2021) — Hanoi Case 2</title>
<style>
  @page {{
    size: A4 landscape;
    margin: 8mm 10mm;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: "Liberation Sans", "DejaVu Sans", Arial, sans-serif;
    font-size: 9.5pt;
    line-height: 1.32;
    color: #111827;
    background: #fff;
  }}
  .page {{
    width: 100%;
    page-break-after: always;
  }}
  .page:last-child {{
    page-break-after: auto;
  }}
  h1 {{
    font-size: 13.5pt;
    color: #0f172a;
    border-bottom: 2px solid #1e3a8a;
    padding-bottom: 3px;
    margin-bottom: 5px;
  }}
  h2 {{
    font-size: 10.5pt;
    color: #1e3a8a;
    margin: 6px 0 4px 0;
  }}
  .meta {{
    font-size: 8.5pt;
    color: #374151;
    background: #f8fafc;
    border-left: 3px solid #2563eb;
    padding: 4px 8px;
    margin-bottom: 6px;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 8.6pt;
    margin-bottom: 6px;
  }}
  th, td {{
    border: 1px solid #cbd5e1;
    padding: 3.5px 5px;
  }}
  th {{
    background: #1e293b;
    color: #ffffff;
    font-weight: 600;
    text-align: center;
  }}
  td.num {{
    text-align: right;
    font-variant-numeric: tabular-nums;
  }}
  tr.highlight {{
    background: #ecfdf5;
  }}
  tr.warn {{
    background: #fef2f2;
  }}
  .grid-2 {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
    margin-top: 4px;
  }}
  .box {{
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    padding: 6px 8px;
    background: #ffffff;
    font-size: 8.6pt;
  }}
  .box ul {{
    padding-left: 15px;
  }}
  .box li {{
    margin-bottom: 2.5px;
  }}
  .fig-full {{
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    padding: 4px;
    text-align: center;
    background: #fafafa;
  }}
  .fig-full img {{
    max-width: 100%;
    max-height: 168mm;
    width: auto;
    height: auto;
    display: block;
    margin: 0 auto;
  }}
  .cap {{
    font-size: 8.2pt;
    color: #334155;
    margin-top: 3px;
    font-weight: 600;
  }}
</style>
</head>
<body>

<div class="page">
  <h1>BÁO CÁO THỰC NGHIỆM: THUẬT TOÁN CCDV 6 BƯỚC CẢI TIẾN (CUI ET AL., 2021)</h1>
  <div class="meta">
    <b>Tuyên bố minh bạch dữ liệu (Real vs. Synthetic Data):</b>
    Tọa độ <b>1.215 trường học</b> (<code>scenario2_schools_age5_14.csv</code>), ranh giới <b>584 xã/phường</b> (<code>3.356,57 km²</code>, <code>EPSG:32648</code>) và tổng <b>1.041.039 học sinh</b> (5–14 tuổi, WorldPop 2020) là <b>dữ liệu thực tế</b>. Chỉ tiêu sức chứa mỗi trường <b>q_j = 856–857 học sinh</b> (dải hội tụ ±5%: <b>[814, 900]</b>, bề rộng dải ΔQ = 85,7 HS) là <b>giả định chia đều (synthetic balanced capacity)</b>.
  </div>

  <h2>1. Bảng Benchmark Thực Nghiệm Trên 1.215 Trường Học Hà Nội (Cùng Tập Đầu Vào &amp; Chỉ Số Đánh Giá)</h2>
  <table>
    <thead>
      <tr>
        <th>Phương pháp / Biến thể đơn vị C_i</th>
        <th>Trường đạt ±5%<br>(|M_j - q_j| ≤ 0.05 q_j)</th>
        <th>Vùng rỗng<br>(M_j = 0)</th>
        <th>Quá tải<br>(&gt; 1.05 q_j)</th>
        <th>Max Load<br>(HS/trường)</th>
        <th>HS bị bỏ sót<br>(Unassigned)</th>
        <th>Diện tích sót<br>km² (%)</th>
        <th>Khoảng cách (km)<br>Mean / Median / P90</th>
        <th>% Không học<br>trường gần nhất</th>
        <th>Thời gian<br>chạy (s)</th>
      </tr>
    </thead>
    <tbody>
      {table_rows}
    </tbody>
  </table>

  <div class="grid-2">
    <div class="box">
      <h2>2. Đối Chiếu Với Đặc Tả 6 Bước Trong CCDV_Methodology_Revised.pdf</h2>
      <ul>
        <li><b>Bước 1 &amp; Bước 6 (Voronoi động &amp; 2 trường cuối):</b> Tái tạo Voronoi trên các trường còn lại sau mỗi lượt; khi còn đúng 2 trường (Qhull suy biến), cắt miền Ω bằng đường trung trực giải tích chính xác.</li>
        <li><b>Bước 2 (Thứ tự trường Trái → Phải, Dưới → Trên):</b> Chọn trường có tâm đa giác Voronoi G_j = (X_j, Y_j) nhỏ nhất theo X_j, tie-break theo Y_j trên hệ trục mét EPSG:32648 gốc (min_x, min_y).</li>
        <li><b>Bước 3 (Co cụm bằng cộng dồn ô C_i):</b> Thay thế hoàn toàn <code>buffer(-r)</code> bằng việc sắp xếp các đơn vị C_i trong V_j theo (x_i, y_i) tăng dần và cộng dồn đến khi đạt dải ±5%, nhường phần dư bên phải cho các trường phía Đông.</li>
        <li><b>Bước 4 (Mở rộng 100m + 10m/bước):</b> Khi tổng học sinh trong V_j &lt; 0.95 q_j, mở rộng biên từ 100m, mỗi bước +10m và gom các C_i mới chạm tới theo đúng thứ tự (x_i, y_i).</li>
      </ul>
    </div>
    <div class="box">
      <h2>3. Phân Tích Phản Biện &amp; Quy Luật Toán Học Về Độ Mịn Đơn Vị C_i</h2>
      <ul>
        <li><b>Vì sao V1 (584 xã nguyên khối, không cắt) thất bại (chỉ đạt {rows_by_m['cui2021_commune_atomic']['pct_within_5pct']:.1f}%):</b> Bề rộng cửa sổ ±5% là ΔQ = 85,7 HS, nhưng <b>450/584 xã (77,1%)</b> có dân số &gt; 900 HS (trung bình 1.783 HS/xã, max 10.717 HS) và số xã (584) ít hơn số trường (1.215). Cộng nguyên xã làm bước nhảy vượt qua toàn bộ cửa sổ [814, 900].</li>
        <li><b>Vì sao V2 (Lưới đều 500m×500m) đạt {rows_by_m['cui2021_grid500m_atomic']['pct_within_5pct']:.1f}% nhưng còn {int(rows_by_m['cui2021_grid500m_atomic']['overloaded_gt_5pct'])} trường quá tải:</b> Ở nội đô (Đống Đa, Hoàn Kiếm), mật độ lên tới 12.500 HS/km² nên 1 ô 500m×500m vẫn chứa tới 2.019 HS (&gt; q_j).</li>
        <li><b>Định lý hội tụ rời rạc (V3 — Bounded Grid p_i ≤ 0.05 q_j ≈ 42 HS):</b> Khi chia nhỏ các ô nội đô sao cho mọi C_i có p_i ≤ 42 HS &lt; ΔQ, thuật toán cộng dồn rời rạc đạt <b>{int(rows_by_m['cui2021_grid_adaptive_atomic']['within_5pct']):,}/1.215 trường ({rows_by_m['cui2021_grid_adaptive_atomic']['pct_within_5pct']:.1f}%)</b> đạt chuẩn ±5%, <b>0 trường quá tải</b>, vượt xa thuật toán Buffer cũ (90,3%).</li>
        <li><b>V4 (584 xã + cắt lát Trái→Phải ở xã biên cuối):</b> Đạt <b>{int(rows_by_m['cui2021_commune_fractional']['within_5pct']):,}/1.215 trường ({rows_by_m['cui2021_commune_fractional']['pct_within_5pct']:.1f}%)</b>, 0 quá tải, 0 HS bị bỏ sót, chạy nhanh gấp 2,2 lần Buffer cũ.</li>
      </ul>
    </div>
  </div>
</div>

<div class="page">
  <h1>HÌNH 4: SO SÁNH TRỰC QUAN VÙNG TUYỂN SINH — CCVD BUFFER CŨ VS. CCDV CẢI TIẾN (CUI ET AL., 2021 — TRÁI SANG PHẢI)</h1>
  <div class="fig-full">
    <img src="{fig4_uri}" alt="Figure 4 Comparison 2x2">
    <div class="cap">Hình 4: So sánh 4 phương pháp phân vùng trên 1.215 trường học Hà Nội kèm 3 khung phóng đại A (Đông Anh), B (Nội đô), C (Hà Đông). Vùng gạch chéo xám là diện tích không gán (unassigned).</div>
  </div>
</div>

</body>
</html>
"""
    DOCS.mkdir(parents=True, exist_ok=True)
    html_path = DOCS / "bao_cao_ccdv_revised_cui2021.html"
    pdf_path = DOCS / "bao_cao_ccdv_revised_cui2021.pdf"
    html_path.write_text(html, encoding="utf-8")
    print(f"Wrote {html_path}")

    cmd = [
        "/usr/bin/chromium",
        "--headless",
        "--disable-gpu",
        "--no-sandbox",
        "--no-pdf-header-footer",
        f"--print-to-pdf={pdf_path}",
        str(html_path),
    ]
    subprocess.run(cmd, check=True)
    print(f"Wrote {pdf_path}")


if __name__ == "__main__":
    main()
