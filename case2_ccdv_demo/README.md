# Case 2: School District Partitioning in Hanoi — Revised Density-Based CCDV

This self-contained directory provides the implementation, spatial datasets, and experimental benchmark results for the **Revised 6-Step Density-Based Capacity-Constrained Dynamic Voronoi (CCDV)** algorithm (adapted from Cui et al., 2021) applied to **1,215 schools** and **1,041,039 students (aged 5–14)** across **584 communes** in Hanoi (`EPSG:32648`, UTM Zone 48N).

---

## 1. Directory Structure

```text
case2_ccdv_demo/
├── README.md                                 # Instructions for running the algorithm and inspecting results
├── requirements.txt                          # Python dependencies
├── ccdv_cui2021.py                           # Core 6-step density-based CCDV algorithm implementation
├── run_ccdv_demo.py                          # Standalone CLI runner script
├── test_ccdv_cui2021.py                      # Automated unit tests (pytest)
├── data/
│   ├── hanoi_boundaries.geojson              # 584 commune polygons of Hanoi
│   ├── scenario2_commune_density.csv         # Commune area (m², km²) and student count (children_5_14)
│   ├── scenario2_schools_age5_14.csv         # 1,215 schools (kindergarten, primary, lower secondary)
│   └── scenario2_sampled_children.geojson    # 10,000 sampled student points for distance evaluation
└── outputs/
    ├── Rp_Algorithm_Report_16_11.pdf         # Theoretical & algorithmic formulation report (Sections 1–5)
    ├── Case2_CCDV_Experimental_Results_16_11.pdf # Experimental benchmark & granularity report (Section 6)
    ├── Case2_CCDV_Combined_Report_16_11.pdf  # Complete combined report (Sections 1–6, 7 pages)
    ├── cui2021_benchmark_summary.csv         # Summary metrics table across all methods & unit granularities
    ├── cui2021_per_school_allocation.csv     # Per-school student allocation table (1,215 rows)
    ├── figure4_cui2021_comparison.png        # 2x2 comparison map with zoom insets A, B, C
    └── figure4_subcommunes_and_ccdv.png      # Sub-commune polygon refinement (39,144 units) & CCDV map
```

---

## 2. Quick Start (How to Run)

### Step 1: Install Dependencies
Requires Python 3.10+ with `geopandas` and `shapely>=2.0`:
```bash
pip install -r requirements.txt
```

### Step 2: Run the Unit Tests
Verify the 6-step algorithm (Voronoi construction, left-to-right centroid ordering, discrete cell accumulation, $100\text{m} + 10\text{m}$ outward search expansion, and analytic bisector for the final 2 schools):
```bash
pytest test_ccdv_cui2021.py -v
```

### Step 3: Run the Algorithm on the Hanoi Dataset (1,215 Schools)
From inside `case2_ccdv_demo/`, run:
```bash
# Default run: executes Boundary-Slice (36s) and Capacity-Bounded Grid (75s)
python run_ccdv_demo.py
```

You can also run specific spatial unit variants using `--mode`:
```bash
# 1. Fast run with boundary subdivision (~36 seconds, 99.9% within ±5%, 0 unassigned):
python run_ccdv_demo.py --mode slice

# 2. Pure atomic accumulation on capacity-bounded grid cells p_i <= 42 (~75 seconds, 100.0% within ±5%):
python run_ccdv_demo.py --mode bounded_grid

# 3. Run on uncut 584 administrative communes (~20 seconds, demonstrates why coarse communes only reach 2.7%):
python run_ccdv_demo.py --mode commune

# 4. Run all 4 variants sequentially:
python run_ccdv_demo.py --mode all
```

Each run prints the summary benchmark table to the terminal and exports the resulting school district polygons (`*_zones.geojson`) and metrics (`demo_run_summary.csv`) into `outputs/`.

---

## 3. Summary of Experimental Benchmark (1,215 Schools, $q_j \in \{856, 857\}$, $\varepsilon = 0.05$)

| Method / Spatial Unit Definition $\mathcal{C}$ | Within $\pm 5\%$ ($\lvert M_j - q_j\rvert \le 0.05q_j$) | Empty ($M_j=0$) | Over $>5\%$ ($>1.05q_j$) | Max Load (students) | Unassigned Area (%) | Dist. (km) Mean / $P_{90}$ | Time (s) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1. Traditional Voronoi (Baseline)** | `68 / 1,215` (`5.6%`) | `0` | `444` | `5,175` | `0.0 km²` (`0.0%`) | `0.75 / 1.63` | `0.2s` |
| **2. Previous CCVD (Buffer $\pm 50\text{ m}$, Centre-Out)** | `1,097 / 1,215` (`90.3%`) | `95` | `20` | `18,249` | `57.1 km²` (`1.7%`) | `2.07 / 5.65` | `81.5s` |
| **3. Revised CCDV — 584 Communes (Uncut)** | `33 / 1,215` (`2.7%`) | `683` | `491` | `10,717` | `0.0 km²` (`0.0%`) | `13.49 / 17.82` | `20.6s` |
| **4. Revised CCDV — 500m Uniform Grid** | `923 / 1,215` (`76.0%`) | `40` | `251` | `2,019` | `0.0 km²` (`0.0%`) | `3.40 / 5.94` | `48.4s` |
| **5. Revised CCDV — Bounded Grid ($p_i \le 0.05q_j$)** | **`1,215 / 1,215` (`100.0%`)** | **`0`** | **`0`** | **`886`** | `88.0 km²` (`2.6%`) | **`2.97 / 5.36`** | `75.3s` |
| **6. Revised CCDV — Communes + Boundary Slice** | **`1,214 / 1,215` (`99.9%`)** | **`0`** | **`0`** | **`898`** | **`0.0 km²` (`0.0%`)** | `3.55 / 5.76` | **`36.5s`** |
| **7. Revised CCDV — Sub-Commune Polygons (`39,144` units)** | **`1,215 / 1,215` (`100.0%`)** | **`0`** | **`0`** | **`895`** | **`0.0 km²` (`0.0%`)** | `3.66 / 5.76` | `68.4s` |
