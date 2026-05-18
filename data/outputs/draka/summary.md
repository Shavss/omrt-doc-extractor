# Project: draka

**Status:** PROTOTYPE OUTPUT, NOT VERIFIED
**Plan ID:** NL.IMRO.0363.N2102BPGST-VG01 (IMRO API cross-validation unavailable — see Data sources)
**Generated:** 2026-05-18T12:13:27+00:00
**Location:** Amsterdam, Hamerkwartier

## How to consume this output

1. `framework.json` — the structured design inputs. Top-level fields:
   `metadata`, `objective`, `constraints` (numerical, geometric, narrative),
   `variables`, `kpis`, `programme`, `geo_context`, `massings`.
   The JSON wraps the validated `ParametricFramework` with a small
   `header` block carrying the prototype banner, generation timestamp,
   tool version, and source-document checksums.
2. `geometry/*.compas` — 35 polygons (plot, bouwvlakken,
   constraint zones) as COMPAS-JSON Polygon blocks in the native
   CRS (EPSG:28992 RD New). Load in Grasshopper via the
   compas_ghpython component or via `compas_rhino.draw_mesh` /
   `MeshArtist`. See https://compas.dev for documentation.
3. `massings/*.compas.json` — 2 example massings
   (max envelope, compliant with setbacks). Illustrative only;
   not design recommendations. `.obj` sidecars are exported for
   quick preview.
4. `massing_inputs.json` — slim envelope-driver subset of
   `framework.json` (heights, setbacks, footprints, BVO limits,
   use-mix only) plus the geometric polygons. Use this when you
   only need the envelope-binding rules and want to skip the audit
   tail (noise, sustainability, etc.).
5. `summary.md` (this file) — start here. Then read `framework.json`.

Every value in `framework.json` carries `provenance` (document, page,
verbatim Dutch `quoted_text`) and `confidence` (score 0.0–1.0, with
0.85 as the review threshold). Click
through to provenance for any ambiguous value.

## Programme intent (from toelichting)

> Het Hamerkwartier staat op het punt te groeien tot een levendig stedelijk woon- en werkgebied met een grote variatie aan functies en een aantrekkelijke openbare ruimte.

> De herontwikkeling van Draka is gericht op de bouw van een gemengd gebied met circa 1.630 woningen, maakindustrie, kantoren, horeca en maatschappelijke voorzieningen in de vorm van onderwijs.

> Het voorliggende bestemmingsplan 'Draka Terrein Hamerkwartier' maakt de nieuwe ontwikkeling juridisch-planologisch mogelijk. Het bestemmingsplan geeft aan op welke gronden welke functies zijn toegestaan zijn en hoe deze gronden bebouwd mogen worden.

## Programme proposal (from inference, see programme.json)

- **Target total GFA:** 151,400 m² (145,000–151,400 m²)
- **Use split:** residential 120,000 m² (79%) | productive 12,000 m² (8%) | office 9,000 m² (6%) | retail/horeca 3,000 m² (2%) | cultural 3,500 m² (2%) | social 3,900 m² (3%)
- **Dwelling count target:** 1630 (1540–1720)
- **Parking demand:** 595 spaces
- **Tenure split:** middenhuur 40% | sociale_huur 30% | vrije_sector_huur 30%
- **Unit mix:**
  - sociale_huur × 30_60m2 (1br): 18% (280–310 dwellings), 40–55 m²
  - sociale_huur × 60_90m2 (2br): 12% (180–210 dwellings), 60–80 m²
  - middenhuur × 30_60m2 (1br): 20% (310–340 dwellings), 40–60 m²
  - middenhuur × 60_90m2 (2br): 20% (310–340 dwellings), 60–85 m²
  - vrije_sector_huur × 60_90m2 (2br): 18% (280–310 dwellings), 60–90 m²
  - vrije_sector_huur × over_90m2 (3br): 12% (180–210 dwellings), 90–130 m²

**Rationale:** Use split is directly anchored in the bestemmingsplan's explicit programmatic caps for the Draka terrein: 120,000 m² residential (max_bvo_residential), 12,000 m² productive industry (min_bvo_productive_industry, a hard minimum), 9,000 m² office (max_bvo_office), 3,900 m² social/maatschappelijk (max_bvo_social_functions), 3,500 m² culture (max_bvo_culture_recreation), 3,000 m² horeca (max_bvo_horeca). Total reconciles with max_bvo_total_draka = 151,400 m². Office, horeca, culture, and social are capped; productive is a floor. The combined dienstverlening+horeca+culture ceiling of 6,500 m² (max_…

**Overall confidence:** 0.85 — see `programme.json` for the full reasoning trace.

## Numerical constraints (top binding values)

### Heights (92 total, showing top 15)

- **Maximum bouwhoogte woontoren (direct toegestaan)** (`max_height_woontoren_direct`): 70 m — confidence 1.00
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.22
- **Maximum bouwhoogte verhoogd voor sba-2** (`max_height_sba2_increased`): 65 m — confidence 1.00
  - applies to: sba_2
  - condition: Met omgevingsvergunning; gemiddelde bouwhoogte op sba-2 gronden maximaal 60 m
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.22
- **Gemiddelde bouwhoogte sba-2** (`avg_height_sba2`): 60 m — confidence 1.00
  - applies to: sba_2
  - condition: Geldt als gemiddelde over alle bouwhoogtes op gronden met sba-2
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.22
- **Maximum bouwhoogte verhoogd voor sba-1** (`max_height_sba1_increased`): 50 m — confidence 1.00
  - applies to: sba_1
  - condition: Met omgevingsvergunning; gemiddelde bouwhoogte op sba-1 gronden maximaal 45 m
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.22
- **Gemiddelde bouwhoogte sba-1** (`avg_height_sba1`): 45 m — confidence 1.00
  - applies to: sba_1
  - condition: Geldt als gemiddelde over alle bouwhoogtes op gronden met sba-1
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.22
- **Landscape integration study threshold height** (`landscape_integration_study_threshold`): 30 m — confidence 1.00
  - condition: buildings exceeding this height require landscape integration study
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.20
- **Wind study threshold height** (`wind_study_threshold_height`): 20 m — confidence 1.00
  - condition: buildings exceeding this height require wind impact study
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.20
- **Sunlight study threshold height** (`sunlight_study_threshold_height`): 20 m — confidence 1.00
  - condition: buildings exceeding this height require sunlight impact study
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.20
- **Maximale bouwhoogte lichtmasten** (`max_height_lichtmasten_verkeer`): 15 m — confidence 1.00
  - applies to: verkeer
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.25
- **Maximale bouwhoogte reclamemasten en vlaggenmasten** (`max_height_reclamemasten_verkeer`): 10 m — confidence 1.00
  - applies to: verkeer
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.25
- **Minimum plint height** (`min_plint_height`): 8 m — confidence 1.00
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.17
- **Maximale bouwhoogte overige bouwwerken (geen gebouwen)** (`max_height_overige_bouwwerken_verkeer`): 6 m — confidence 1.00
  - applies to: verkeer
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.25
- **Maximum bouwhoogte nutsvoorzieningen (afwijking)** (`deviation_utility_building_max_height`): 6 m — confidence 1.00
  - condition: bij omgevingsvergunning voor gebouwen ten behoeve van nutsvoorzieningen
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.33
- **Maximale overschrijding bouwhoogte voor schoorstenen, ventilatie etc. (afwijking)** (`deviation_rooftop_equipment_height_increase`): 5 m — confidence 1.00
  - condition: bij omgevingsvergunning ten behoeve van schoorstenen, ventilatie-inrichtingen, vlaggenmasten, antennes en vergelijkbare bouwwerken voor duurzame energie
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.33
- **Minimum overhead door height for commercial functions** (`min_overhead_door_height_commercial`): 4 m — confidence 1.00
  - condition: For buildings with functions mentioned under 3.1 sub c and d, on the street-facing side
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.17
- … and 77 more in `framework.json` → `constraints.numerical` (category = `height`).

### Setbacks (19 total, showing top 15)

- **Minimum gap between buildings per bouwvlak** (`min_building_gap_general`): 12 m — confidence 1.00
  - condition: At least two gaps of minimum 12m per bouwvlak, except at bouwvlakken with 'specifieke bouwaanduiding – 4' or '– 3'
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.17
- **Minimum gap between buildings at sba-4** (`min_building_gap_sba4`): 12 m — confidence 1.00
  - condition: At specifieke bouwaanduiding – 4, at least one gap of minimum 12m must be provided
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.17
- **Setback above 21m building height (general)** (`setback_above_21m_general`): 2.5 m — confidence 1.00
  - condition: For buildings with height 21m or higher, on the exterior side of bouwvlakken, except at bouwvlakken with 'specifieke bouwaanduiding – 3'
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.17
- **Setback above 30.5m at sba-3** (`setback_above_30_5m_sba3`): 2.5 m — confidence 1.00
  - condition: At specifieke bouwaanduiding – 3, for buildings with height 30.5m or higher, on the exterior side of bouwvlakken
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.17
- **Minimum afstand dakterrassen en technische installaties tot gevellijn** (`min_setback_dakterras_techniek`): 2 m — confidence 1.00
  - condition: wanneer deze de bouwhoogte overschrijden
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.29
- **Maximum afwijking situering bouwwerken (afwijking)** (`deviation_siting_max_shift`): 2 m — confidence 1.00
  - condition: bij omgevingsvergunning voor geringe afwijkingen in het belang van ruimtelijk of technisch beter verantwoorde plaatsing
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.33
- **Maximale overschrijding bebouwingsgrenzen voor balkons etc. (afwijking)** (`deviation_building_boundary_overhang`): 2 m — confidence 1.00
  - condition: bij omgevingsvergunning ten behoeve van balkons, bordessen, luifels, buitentrappen, bouwkundige maatregelen voor ondergeschikte delen van gebouwen
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.33
- **Maximum overschrijding plinten, funderingen e.d.** (`max_overschrijding_plint_fundament`): 0.2 m — confidence 1.00
  - condition: voor stoepen, stoeptreden, funderingen, plinten, pilasters, kozijnen, standleidingen voor hemelwater, gevelversieringen, wanden van ventilatiekanalen, schoorstenen en dergelijke delen van gebouwen
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.29
- **Minimum afstand tot spoorlijn** (`min_distance_spoorlijn`): 200 m — confidence 0.85
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.168
- **Richtafstand milieucategorie 4.1 (GVB Veren)** (`setback_milieucategorie_4_1_gvb_veren`): 100 m — confidence 0.85
  - condition: voor milieucategorie 4.1 bedrijven zoals GVB Veren
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.134
- **Vrijwaringszone vaarweg Barro** (`barro_vaarweg_vrijwaringszone_50m`): 50 m — confidence 0.85
  - condition: Voor vaarwegen met een CEMT-klasse VI
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.55
- **Afstand gevoelige bestemmingen drukke stedelijke wegen** (`sensitive_function_setback_busy_urban_roads`): 50 m — confidence 0.85
  - condition: Voor stedelijke wegen met meer dan 10.000 motorvoertuigbewegingen per etmaal, ongeacht de luchtkwaliteit
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.140
- **Vrijwaringszone Rijksvaarweg (nautische veiligheid)** (`nautical_safety_setback`): 50 m — confidence 0.85
  - condition: aan weerszijden van de Rijksvaarweg, gemeten vanaf de begrenzing van de vaarweg
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.166
- **Vrijwaringszone vaarweg IJ** (`vaarweg_vrijwaringszone_50m`): 50 m — confidence 0.85
  - condition: gemeten vanaf de begrenzingslijn van de vaarweg; geen bebouwing toegestaan binnen deze zone
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.172
- **Richtafstand milieucategorie 3.1 bedrijf** (`setback_milieucategorie_3_1`): 30 m — confidence 0.85
  - condition: van perceelgrens van een categorie 3.1 bedrijf tot de gevels van milieugevoelige functies in gemengd gebied
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.134
- … and 4 more in `framework.json` → `constraints.numerical` (category = `setback`).

### Footprint / coverage (9 total, showing top 9)

- **Maximum footprint coverage for inhangvloer** (`inhangvloer_footprint_max`): 50 percent — confidence 1.00
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.12
- **Oppervlak bouwveld A9** (`oppervlak_a9`): 5726 m2 — confidence 0.90
  - applies to: bouwveld_a9
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.37
- **Oppervlak bouwveld A13** (`oppervlak_a13`): 4774 m2 — confidence 0.90
  - applies to: bouwveld_a13
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.37
- **Oppervlak bouwveld A7** (`oppervlak_a7`): 4217 m2 — confidence 0.90
  - applies to: bouwveld_a7
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.37
- **Oppervlak bouwveld A12** (`oppervlak_a12`): 4053 m2 — confidence 0.90
  - applies to: bouwveld_a12
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.37
- **Oppervlak bouwveld A6** (`oppervlak_a6`): 2183 m2 — confidence 0.90
  - applies to: bouwveld_a6
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.37
- **Oppervlak bouwveld A10** (`oppervlak_a10`): 2174 m2 — confidence 0.90
  - applies to: bouwveld_a10
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.37
- **Oppervlak bouwveld A8** (`oppervlak_a8`): 1729 m2 — confidence 0.90
  - applies to: bouwveld_a8
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.37
- **Oppervlak bouwveld A11** (`oppervlak_a11`): 1562 m2 — confidence 0.90
  - applies to: bouwveld_a11
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.37

### FSI / FAR (1 total, showing top 1)

- **Maximum Floor Space Index Hamerstraatgebied** (`max_fsi_hamerstraatgebied`): 2 ratio — confidence 0.85
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.11

### Programme BVO caps and floors (50 total, showing top 15)

- **Maximum BVO per floor for high-rise 21-50m** (`max_bvo_per_floor_high_rise_21_50m`): 600 m2 — confidence 1.00
  - condition: For high-rise accents between 21 and 50 meters height
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.17
- **Maximum BVO per floor for high-rise above 50m (from 21m upward)** (`max_bvo_per_floor_high_rise_above_50m_from_21m`): 500 m2 — confidence 1.00
  - condition: For high-rise accents above 50 meters height, starting from 21 meters upward
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.17
- **Maximum BVO for ondergeschikte detailhandel** (`ondergeschikte_detailhandel_bvo_max`): 50 m2 — confidence 1.00
  - condition: when realized within another main function
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.12
- **Maximum BVO for ondergeschikte horeca** (`ondergeschikte_horeca_bvo_max`): 50 m2 — confidence 1.00
  - condition: when realized within another main function
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.12
- **Maximum bruto vloeroppervlak nutsvoorzieningen (afwijking)** (`deviation_utility_building_max_bvo`): 25 m2 — confidence 1.00
  - condition: bij omgevingsvergunning voor gebouwen ten behoeve van nutsvoorzieningen
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.33
- **Minimum BVO productieve bedrijvigheid - gemengd 6** (`bvo_min_gemengd_6`): 3000 m2 — confidence 0.95
  - applies to: gemengd_vorm_6
  - condition: voor woningen op gronden met Specifieke vorm van gemengd - 6
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.21
- **Minimum BVO productieve bedrijvigheid - gemengd 2** (`bvo_min_gemengd_2`): 2000 m2 — confidence 0.95
  - applies to: gemengd_vorm_2
  - condition: voor woningen op gronden met Specifieke vorm van gemengd - 2
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.21
- **Minimum BVO productieve bedrijvigheid - gemengd 3** (`bvo_min_gemengd_3`): 2000 m2 — confidence 0.95
  - applies to: gemengd_vorm_3
  - condition: voor woningen op gronden met Specifieke vorm van gemengd - 3
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.21
- **Minimum BVO productieve bedrijvigheid - gemengd 4** (`bvo_min_gemengd_4`): 1000 m2 — confidence 0.95
  - applies to: gemengd_vorm_4
  - condition: voor woningen op gronden met Specifieke vorm van gemengd - 4
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.21
- **Maximum basement area for Overige zone - 2 (≤300 m² threshold)** (`max_basement_area_overige_zone_2`): 300 m2 — confidence 0.95
  - applies to: overige_zone_2
  - condition: when basement depth ≤ 4 m and approval via beleidsregel 'Grondwaterneutrale Kelders Amsterdam'
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.31
- **Minimum work and facilities BVO in final state** (`min_work_and_facilities_bvo`): 270000 m2 — confidence 0.90
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.21
- **Maximum office volume after 2020** (`max_office_volume_post_2020`): 50000 m2 — confidence 0.90
  - condition: na 2020
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.21
- **Total residential GFA in Hamerkwartier** (`programme_total_residential_bvo`): 510000 m2 — confidence 0.85
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.21
- **Harde ondergrens werken en voorzieningen BVO** (`work_facilities_gfa_minimum`): 270000 m2 — confidence 0.85
  - applies to: programme.commercial, programme.facilities
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.38
- **BVO niet wonen totaal** (`non_residential_bvo_total`): 234000 m2 — confidence 0.85
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.46
- … and 35 more in `framework.json` → `constraints.numerical` (category = `bvo_limit`).

### Parking norms (30 total, showing top 15)

- **Minimum electric vehicle parking** (`ev_parking_minimum`): 50 percent — confidence 1.00
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.35
- **Minimum car-share replacement** (`carshare_replacement_minimum`): 30 percent — confidence 1.00
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.35
- **Parking norm vrije sector > 60 m² bvo** (`parking_norm_vrije_sector_over_60m2`): 0.6 per_dwelling — confidence 1.00
  - applies to: programme.vrije_sector
  - condition: when dwelling GFA > 60 m²
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.35
- **Parking norm kantoor** (`parking_norm_kantoor`): 0.6 per_100m2_bvo — confidence 1.00
  - applies to: programme.kantoor
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.35
- **Parking norm vrije sector 30-60 m² bvo** (`parking_norm_vrije_sector_30_60m2`): 0.5 per_dwelling — confidence 1.00
  - applies to: programme.vrije_sector
  - condition: when dwelling GFA is 30-60 m²
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.35
- **Parking norm middeldure huur** (`parking_norm_middeldure_huur`): 0.4 per_dwelling — confidence 1.00
  - applies to: programme.middeldure_huur
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.35
- **Parking norm vrije sector < 30 m² bvo** (`parking_norm_vrije_sector_under_30m2`): 0.4 per_dwelling — confidence 1.00
  - applies to: programme.vrije_sector
  - condition: when dwelling GFA < 30 m²
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.35
- **Parking norm sociale huur** (`parking_norm_sociale_huur`): 0.1 per_dwelling — confidence 1.00
  - applies to: programme.sociale_huur
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.35
- **Parking norm bezoekers wonen** (`parking_norm_bezoekers_wonen`): 0.1 per_dwelling — confidence 1.00
  - applies to: programme.residential
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.35
- **Bicycle parking spaces for residents (worst-case)** (`parking_bike_residents_total`): 4295 parking_spaces — confidence 0.85
  - applies to: programme.residential
  - condition: worst-case functieprogramma
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.104
- **Bicycle parking spaces for residents (worst-case programme)** (`bike_parking_residents_worst_case`): 4295 per_dwelling — confidence 0.85
  - applies to: programme.residents
  - condition: worst-case functieprogramma
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.105
- **Bicycle parking spaces for residents in low racks** (`parking_bike_residents_low_rack`): 3260 parking_spaces — confidence 0.85
  - applies to: programme.residential
  - condition: worst-case functieprogramma
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.104
- **Bicycle parking for short and long-term visitors (realistic scenario)** (`parking_bike_visitors_total_realistic`): 2133 parking_spaces — confidence 0.85
  - condition: reële scenario, without double-use
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.104
- **Bicycle parking spaces for visitors and workers** (`bike_parking_visitors_workers`): 1535 per_dwelling — confidence 0.85
  - applies to: programme.visitors, programme.workers
  - condition: worst-case functieprogramma, maatgevende moment
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.105
- **Total car parking spaces required (worst-case)** (`parking_car_total`): 595 parking_spaces — confidence 0.85
  - condition: worst-case functieprogramma
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.104
- … and 15 more in `framework.json` → `constraints.numerical` (category = `parking`).

### Use mix (10 total, showing top 10)

- **Minimum proportion of work floor for kantoor classification** (`kantoor_werkvloer_min`): 50 percent — confidence 1.00
  - condition: for the hybrid office/workspace definition; more than 50% of the work floor must be set up as office space
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.12
- **Maximum ratio of ondergeschikte detailhandel to host function** (`ondergeschikte_detailhandel_ratio_max`): 20 percent — confidence 1.00
  - condition: when realized within another main function
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.12
- **Maximum ratio of ondergeschikte horeca to host function** (`ondergeschikte_horeca_ratio_max`): 20 percent — confidence 1.00
  - condition: when realized within another main function
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.12
- **Mid-price housing percentage for transformation projects** (`programme_middeldure_transformation_40_percent`): 40 percent — confidence 0.90
  - applies to: programme.middeldure
  - condition: For transformation projects (herontwikkeling) specifically
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.74
- **Social housing percentage for transformation projects** (`programme_social_housing_transformation_30_percent`): 30 percent — confidence 0.90
  - applies to: programme.social_housing
  - condition: For transformation projects (herontwikkeling) specifically
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.74
- **Expensive housing percentage for transformation projects** (`programme_dure_transformation_30_percent`): 30 percent — confidence 0.90
  - applies to: programme.dure
  - condition: For transformation projects (herontwikkeling) specifically
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.74
- **Social housing percentage for new developments** (`programme_social_housing_40_percent`): 40 percent — confidence 0.85
  - applies to: programme.social_housing
  - condition: For new development projects without existing investment decisions or contracts
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.74
- **Mid-price housing percentage for new developments** (`programme_middeldure_40_percent`): 40 percent — confidence 0.85
  - applies to: programme.middeldure
  - condition: For new development projects without existing investment decisions or contracts
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.74
- **Expensive housing percentage for new developments** (`programme_dure_20_percent`): 20 percent — confidence 0.85
  - applies to: programme.dure
  - condition: For new development projects without existing investment decisions or contracts
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.74
- **Minimum percentage bedrijven (business use)** (`min_business_use_percent`): 50 percent — confidence 0.75 ❗
  - condition: voor transformatie van bestaande bedrijventerrein (anno 2009)
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.64

### Noise (64 total, showing top 15)

- **Minimum height for noise-sensitive functions at dove gevel 1** (`min_height_noise_sensitive_sba_dove_gevel_1`): 21 m — confidence 1.00
  - condition: At 'specifieke bouwaanduiding - dove gevel 1', noise-sensitive functions only allowed from 21m height upward if the facade is a dove gevel or has noise-reducing cladding
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.17
- **Geluidsniveau geluidsluwe gevel (afwijking toegestaan)** (`noise_quiet_facade_limit`): 3 dB(A) — confidence 1.00
  - condition: Afwijking boven voorkeursgrenswaarde, met akoestisch onderzoek en maatregelen
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.22
- **Maximum exemption value for noise-zoned roads** (`noise_max_exemption_zoned_roads`): 63 dB — confidence 0.95
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.125
- **Maximum allowable higher noise limit for new residential buildings (industrial noise)** (`noise_limit_residential_max_allowable`): 55 dB — confidence 0.95
  - condition: Industrial noise, hogere waarde for new residential buildings
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.131
- **Base noise limit for new residential buildings (industrial noise)** (`noise_limit_residential_base`): 50 dB — confidence 0.95
  - condition: Industrial noise, etmaalwaarde
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.131
- **Cumulative noise from all surrounding roads** (`noise_cumulative_all_roads`): 64 dB — confidence 0.93
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.125
- **Noise threshold for 'still side' requirement** (`noise_threshold_still_side`): 48 dB — confidence 0.93
  - applies to: existing_dwellings
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.125
- **Hogere waarde voor industrielawaai Johan van Hasseltkanaal Oost** (`noise_hogere_waarde_industrielawaai`): 58 dB — confidence 0.92
  - condition: Geluidbelasting als gevolg van gezoneerd industrieterrein Johan van Hasseltkanaal Oost
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.137
- **Baseline noise level at Hamerstraat 3-5** (`noise_baseline_hamerstraat_3_5`): 53 dB — confidence 0.92
  - applies to: hamerstraat_3_5
  - condition: without plan development
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.125
- **Baseline noise level at Schaafstraat 4** (`noise_baseline_schaafstraat_4`): 48 dB — confidence 0.92
  - applies to: schaafstraat_4
  - condition: without plan development
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.125
- **Maximum noise increase at existing dwellings, Gedempt Hamerkanaal** (`noise_increase_existing_gedempt_hamerkanaal`): 4 dB — confidence 0.92
  - applies to: existing_dwellings_gedempt_hamerkanaal
  - condition: as result of traffic to and from the plan area
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.125
- **Maximum noise increase at Schaafstraat 4 and Hamerstraat 3-5** (`noise_increase_schaafstraat_hamerstraat`): 3 dB — confidence 0.92
  - applies to: schaafstraat_4, hamerstraat_3_5
  - condition: as result of plan development
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.125
- **Absolute noise level at Exclusiva, Gedempt Hamerkanaal** (`noise_absolute_exclusiva_gedempt_hamerkanaal`): 58 dB — confidence 0.90
  - applies to: exclusiva_development
  - condition: traffic noise from Gedempt Hamerkanaal
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.125
- **Maximum noise exceedance above allowable limit** (`noise_exceedance_max`): 3 dB — confidence 0.90
  - condition: At various facades where 55 dB(A) limit is exceeded
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.131
- **Noise increase at Hamerstraat and Johan van Hasseltweg** (`noise_increase_hamerstraat_johan_van_hasseltweg`): 1–2 dB — confidence 0.90
  - condition: existing and planned dwellings, traffic on Hamerstraat and Johan van Hasseltweg
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.125
- … and 49 more in `framework.json` → `constraints.numerical` (category = `noise`).

### Sustainability (44 total, showing top 15)

- **Minimum water storage capacity** (`water_storage_min`): 60 mm — confidence 1.00
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.20
- **Minimum green coverage percentage** (`green_coverage_min`): 40 percent — confidence 1.00
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.20
- **Rainfall retention duration** (`rainfall_retention_duration`): 24 uur — confidence 1.00
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.20
- **Maximum water discharge rate** (`water_discharge_rate_max`): 2.5 liter/m2/uur — confidence 1.00
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.20
- **Maximum MPG (Milieuprestatie Gebouwen)** (`mpg_max`): 0.7 ratio — confidence 1.00
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.20
- **Minimum substrate thickness for roof green** (`roof_green_substrate_min`): 10 m — confidence 0.95
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.20
- **Totaal groen te realiseren** (`green_total_target`): 125260 m2 — confidence 0.85
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.46
- **Urban sportpark op Hamerkop** (`urban_sportpark_hamerkop`): 6500 m2 — confidence 0.85
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.46
- **Sport in openbare ruimte totaal** (`sport_public_space_total`): 6500 m2 — confidence 0.85
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.46
- **Speelplekken (0-6 jaar)** (`play_areas_0_6_year`): 3500 m2 — confidence 0.85
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.46
- **Speelvelden (6-12 jaar)** (`play_fields_6_12_year`): 3000 m2 — confidence 0.85
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.46
- **CO₂ reduction target 2040** (`co2_reduction_2040`): 75 percent — confidence 0.85
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.157
- **Openbare ruimte regenwaterafvoer capaciteit** (`rainwater_drainage_capacity`): 60 mm/h — confidence 0.85
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.33
- **Hemelwater bergingsnorm per m² bebouwd oppervlak** (`hemelwater_bergingsnorm`): 60 liter per m2 — confidence 0.85
  - condition: voor nieuwe gebouwen en voor bestaande gebouwen die ingrijpend worden gerenoveerd, waaraan één of meer bouwlagen worden toegevoegd, of waarvan het bebouwde oppervlak wordt uitgebreid
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.142
- **Rainproof plan maaiveld design capacity** (`rainproof_capacity_60mm_1hr`): 60 mm — confidence 0.85
  - condition: precipitation event of 60 mm in 1 hour
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.144
- … and 29 more in `framework.json` → `constraints.numerical` (category = `sustainability`).

### Other (77 total, showing top 15)

- **Maximum disturbance area without archaeology permit** (`archaeology_area_threshold`): 10000 m2 — confidence 1.00
  - applies to: archaeology_zone
  - condition: when disturbance depth is less than 4.0m below NAP
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.26
- **Maximale afwijking toegestane afmetingen en percentages (afwijking)** (`deviation_dimensions_max_variation`): 10 percent — confidence 1.00
  - condition: bij omgevingsvergunning mits geen onevenredige aantasting plaatsvindt van straat- en bebouwingsbeeld, verkeersveiligheid, gebruiksmogelijkheden aangrenzende gronden en bouwwerken en milieusituatie
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.33
- **Overgangsrecht bouwwerk uitbreiding maximum** (`overgangsrecht_uitbreiding_max`): 10 percent — confidence 1.00
  - condition: Alleen voor bestaande bouwwerken die afwijken van het plan, bij eenmalige afwijking door bevoegd gezag
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.36
- **Maximum disturbance depth without archaeology permit** (`archaeology_depth_threshold`): 4 m — confidence 1.00
  - applies to: archaeology_zone
  - condition: measured below NAP (or below waterbed if water is present)
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.26
- **Maximum oppervlakte bouwwerken geen gebouwen (afwijking)** (`deviation_minor_structures_max_area_pct`): 2 percent — confidence 1.00
  - condition: bij omgevingsvergunning voor bouwwerken geen gebouwen zijnde (gedenktekens, plastieken, reclameobjecten, vrijstaande muren, geluidwerende voorzieningen, etc.)
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.33
- **Minimum depth for kelder classification** (`kelder_depth_min`): 0.5 m — confidence 1.00
  - condition: measured from peil to the underside of the floor slab of the relevant building layer
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.12
- **Maximum basement area for small basements** (`basement_max_area_small`): 300 m2 — confidence 0.95
  - condition: for basements qualifying under small basement standard measures
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.143
- **Maximum basement depth for Overige zone - 2 (≤4 m threshold)** (`max_basement_depth_overige_zone_2`): 4 m — confidence 0.95
  - applies to: overige_zone_2
  - condition: when basement area ≤ 300 m² and approval via beleidsregel 'Grondwaterneutrale Kelders Amsterdam'
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.31
- **Maximum basement depth for small basements** (`basement_max_depth_small`): 4 m — confidence 0.95
  - condition: for basements qualifying under small basement standard measures
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.143
- **Maximum adjustment to boundary lines** (`boundary_adjustment_limit`): 2 m — confidence 0.95
  - condition: when adjusting plot boundaries, destination boundaries, or other boundary lines for improved spatial or technical placement of buildings or to align with actual site conditions
  - source: Draka Terrein Hamerkwartier_Regels.pdf p.34
- **Desired groundwater dewatering depth for trees in public space** (`groundwater_tree_dewatering_depth`): 0.9 m — confidence 0.92
  - condition: for trees in public space (openbare ruimte)
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.143
- **Groundwater norm depth below surface** (`groundwater_norm_depth_below_surface`): 0.5 m — confidence 0.92
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.143
- **Speed limit Gedempt Hamerkanaal and Hamerstraat** (`speed_limit_30kmh_gedempt_hamerkanaal`): 30 km/h — confidence 0.90
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.124
- **Grondwater ontwateringsnorm** (`grondwater_ontwateringsnorm`): 0.9 m — confidence 0.88
  - condition: for new construction in public space, post-2021 policy target
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.141
- **Maximum verkoopprijs middeldure koopwoning** (`price_range_middeldure_koop_max`): 306000 euro — confidence 0.85
  - applies to: programme.middeldure_koop
  - source: Draka Terrein Hamerkwartier_Toelichting.pdf p.75
- … and 62 more in `framework.json` → `constraints.numerical` (category = `other`).

See `framework.json` → `constraints.numerical` for all 396 constraints with full provenance (document, page, verbatim Dutch text) and confidence scores.

## Geometric constraints

Polygon counts by feature type:
- other: 19
- bouwvlak: 11
- dvg_overlay: 2
- no_build_zone: 2
- plot_boundary: 1

Source drawing:
- File: Drakaterrein-A2_2022-04-26 versie 2_kaveltekening.pdf
- Scale: 1:1000
- Plot bounding box: 594 m × 420 m (RD New)

Reconciled with regels for bouwvlak heights — see the Reconciliation summary below and `reconciliation_report.json`.

## Zone programme summary

| Zone | Height | Source | Codes | Matched rules | Key constraints |
|------|--------|--------|-------|---------------|-----------------|
| Bouwvlak sba-4 | 30.5m | verbeelding_uncorrected | sba_4 | 0 | — |
| Bouwvlak sba-1 | 45m | regels | sba_1 | 2 | Maximum bouwhoogte verhoogd voor sba-1=50.0m, Gemiddelde bouwhoogte sba-1=45.0m |
| Bouwvlak sba-3, sba-dvg2 | 30.5m | verbeelding_uncorrected | sba_3, sba_dvg2 | 0 | — |
| Bouwvlak sba-2, sba-dvg3, sba-dvg5 | 60m | regels | sba_2, sba_dvg3, sba_dvg5 | 2 | Maximum bouwhoogte verhoogd voor sba-2=65.0m, Gemiddelde bouwhoogte sba-2=60.0m |
| Bouwvlak sba-4 | 30.5m | verbeelding_uncorrected | sba_4 | 0 | — |
| Bouwvlak sba-4, sgd-7 | 30.5m | verbeelding_uncorrected | sba_4, sgd_7 | 0 | — |
| Bouwvlak sba-2, sgd-4 | 60m | verbeelding | sba_2, sgd_4 | 2 | Maximum bouwhoogte verhoogd voor sba-2=65.0m, Gemiddelde bouwhoogte sba-2=60.0m |
| Bouwvlak sba-4, GD | 40m | verbeelding_uncorrected | gd, sba_4 | 0 | — |
| Bouwvlak sba-1, sgd-2 | 45m | regels | sba_1, sgd_2 | 2 | Maximum bouwhoogte verhoogd voor sba-1=50.0m, Gemiddelde bouwhoogte sba-1=45.0m |
| Bouwvlak sba-2, m | 60m | verbeelding | m, sba_2 | 2 | Maximum bouwhoogte verhoogd voor sba-2=65.0m, Gemiddelde bouwhoogte sba-2=60.0m |
| Bouwvlak sba-dvg1, sba-dvg2, sgd-3 | 60m | verbeelding_uncorrected | sba_dvg1, sba_dvg2, sgd_3 | 0 | — |

Full zone-constraint mapping in `zone_programme_summary.json`. Zones with 0 matched rules may indicate that `applies_to` codes in the extracted constraints do not match the zone labels from the kaveltekening. Run `scripts/inspect_zones.py` to diagnose.

## Narrative constraints (selected)

- **Rainwater collected on the plot must be reused for irrigating green areas on the plot.** (`rainwater_reuse_green`, sustainability) — confidence 1.00
  > "opgevangen hemelwater dient hergebruikt te worden voor de bevloeiing van de groenvoorzieningen op de kavel" — Draka Terrein Hamerkwartier_Regels.pdf p.21
- **No crawl spaces shall be constructed.** (`no_crawl_spaces`, urban_design) — confidence 1.00
  > "er worden geen kruipruimtes gerealiseerd" — Draka Terrein Hamerkwartier_Regels.pdf p.21
- **At the location with designation 'specifieke vorm van gemengd - 9', construction is only permitted when a cultural-historical assessment has been submitted to the competent authority demonstrating that the proposed changes do not disproportionately damage the image-defining elements.** (`cultural_heritage_assessment_gemengd_9`, historical_cultural) — confidence 1.00
  > "Ter plaatse van de aanduiding 'specifieke vorm van gemengd - 9' mag alleen worden gebouwd wanneer een cultuurhistorische verkenning aan het bevoegd gezag is overhandigd waaruit blijkt dat met de beoogde wijzigingen de beeldbepalende elementen niet onevenredig worden aangetast." — Draka Terrein Hamerkwartier_Regels.pdf p.21
- **Gronden met de bestemming 'Groen' zijn bestemd voor groen, fiets- en voetpaden, ontsluitingswegen, parkeervoorzieningen, speelvoorzieningen, water en waterstaatsdoeleinden, oevervoorzieningen, nutsvoorzieningen, kunstwerken ten behoeve van weg- en waterbouw, objecten van beeldende kunst, en overige voorzieningen ten behoeve van deze functie.** (`groen_permitted_uses`, urban_design) — confidence 1.00
  > "De voor 'Groen' aangewezen gronden zijn bestemd voor: a. groen; b. fiets- en/of voetpaden en/of ontsluitingswegen; c. parkeervoorzieningen; d. speelvoorzieningen; e. water, waterstaatsdoeleinden en oevervoorzieningen; f. nutsvoorzieningen; g. kunstwerken ten behoeve van weg- en waterbouw; h. objecten van beeldende kunst; i. overige voorzieningen ten behoeve van deze functie." — Draka Terrein Hamerkwartier_Regels.pdf p.24
- **Op gronden met bestemming 'Groen' mogen uitsluitend bouwwerken, geen gebouwen zijnde, worden gebouwd ten dienste van de bestemming.** (`groen_structures_only`, urban_design) — confidence 1.00
  > "Op en onder de in 4.1 genoemde gronden mag uitsluitend bouwwerken, geen gebouwen zijnde gebouwd worden ten dienste van de bestemming." — Draka Terrein Hamerkwartier_Regels.pdf p.24
- **Within the Waarde - Archeologie zone, an omgevingsvergunning with archaeological report is required for ground disturbances exceeding 10,000 m² in area or 4.0 m depth below NAP, unless the disturbance qualifies for exemption (normal maintenance or already in execution at plan adoption).** (`archaeology_permit_requirement`, process) — confidence 1.00
  > "voor zover met betrekking tot de in lid 6.1 genoemde gronden sprake is van bodemverstoring, dient de aanvrager van een omgevingsvergunning een archeologisch rapport te overleggen" — Draka Terrein Hamerkwartier_Regels.pdf p.26
- **The omgevingsvergunning for ground disturbance in the archaeology zone may include conditions requiring: (1) technical measures to preserve archaeological values in situ, (2) excavations, or (3) supervision by a qualified archaeological expert meeting the specifications set by the municipal executive.** (`archaeology_permit_conditions`, process) — confidence 1.00
  > "aan de onder a, genoemde vergunning kunnen de volgende voorschriften worden verbonden: 1. de verplichting tot het treffen van technische maatregelen waardoor de archeologische waarden in de bodem worden behouden; 2. de verplichting tot het doen van opgravingen; 3. de verplichting de activiteit die tot bodemverstoring leidt, te laten begeleiden door een deskundige" — Draka Terrein Hamerkwartier_Regels.pdf p.26
- **The municipal executive (dagelijks bestuur) is authorized to impose additional siting requirements for buildings within the archaeology zone to protect archaeological values, if research has confirmed their presence on site.** (`archaeology_siting_authority`, process) — confidence 1.00
  > "Het dagelijks bestuur is bevoegd ter bescherming van de in lid 6.1 genoemde archeologische waarden nadere eisen te stellen aan de situering van de bouwwerken, indien uit onderzoek is gebleken dat ter plaatse archeologische waarden aanwezig zijn." — Draka Terrein Hamerkwartier_Regels.pdf p.26
- **Within the archaeology zone, the following works and activities are prohibited without (or in deviation from) an omgevingsvergunning: groundworks deeper than 4m below NAP; pile-driving or driving objects into the ground; creating or widening waterways; raising or lowering water levels; installing underground cables, pipes, and infrastructure; and installing drainage. Exemptions apply for disturbances smaller than 10,000 m² and shallower than 4m, normal maintenance, and works already in execution at plan adoption.** (`archaeology_works_prohibition`, process) — confidence 1.00
  > "Op en onder de in lid 6.1 genoemde gronden is het verboden zonder of in afwijking van een omgevingsvergunning de volgende werken, geen bouwwerken zijnde en werkzaamheden uit te voeren: 1. het uitvoeren van grondbewerkingen op een grotere diepte dan 4,00 meter onder NAP ... 2. het uitvoeren van heiwerkzaamheden ... 3. het aanleggen en verbreden van wateren; 4. het verlagen of verhogen van het waterpeil; 5. het aanbrengen van ondergrondse kabels, leidingen ... 6. het aanbrengen van drainage" — Draka Terrein Hamerkwartier_Regels.pdf p.26
- **Land that has once been counted towards an approved building plan that has been or can still be executed, must be excluded from consideration when assessing subsequent building plans.** (`anti_dubbeltelregel`, process) — confidence 1.00
  > "Grond die eenmaal in aanmerking is genomen bij het toestaan van een bouwplan waaraan uitvoering is gegeven of alsnog kan worden gegeven, blijft bij de beoordeling van latere bouwplannen buiten beschouwing." — Draka Terrein Hamerkwartier_Regels.pdf p.28
- … and 542 more in `framework.json` → `constraints.narrative`.

## Flagged ambiguities

- **Reconciliation overrides (2):** regels clauses corrected the verbeelding's spatial-proximity reading. See `reconciliation_report.json`.
- **55 numerical constraints with confidence < 0.80:** review before relying on them. Listed with the ❗ marker under the relevant category above.
- **41 narrative constraints with confidence < 0.80.**

## Data sources used

- ✓ Document extraction: 396 numerical, 552 narrative constraints across 3 PDFs (237 pages total).
- ✓ Vector geometry: 35 polygons from kaveltekening, scale 1:1000 (1 plot, 11 bouwvlakken, 23 constraint zones).
- ✗ IMRO API cross-validation: 0 agreed, 0 disagreed, 0 unverifiable, 396 not attempted (API unavailable).
- ✓ PDOK BAG: 1000 buildings within 1000 m (year built 1888–2022).
- ✗ 3D BAG: not available — 2D context only for massing visualisation.
- ✓ CBS demographics (buurt BU0363NL03): pop 4075, 2135 households, avg household size 1.9, median age 39.4.
- ✓ OSM Overpass: bus 76 m, metro 377 m, train 377 m, 147 amenities across 46 categories.

## Reconciliation summary

- 2 polygon heights confirmed (regels matched verbeelding).
- 2 polygon heights corrected by regels (verbeelding's spatial-proximity reading overridden).
- 1 polygon height inferred from regels (verbeelding had no label).
- 1 regels clause with no matching polygon (non-bouwvlak labels or permit-gated deviations).
- 1 non-base height constraint skipped (deviations, fences, lights).

See `reconciliation_report.json` for per-polygon details.

## Sanity check

**5 finding(s):** 5 error(s), 0 warning(s).

- **[error]** `Maximum building height per maatvoeringsaanduiding` = 0.0 m — Maximum building height per maatvoeringsaanduiding = 0.0 m is outside the universal height bound (0.5, 250.0).
- **[error]** `Bicycle parking spaces for residents (worst-case programme)` = 4295.0 per_dwelling — Bicycle parking spaces for residents (worst-case programme) = 4295.0 per_dwelling is outside the universal parking bound (0.0, 5.0).
- **[error]** `Bicycle parking spaces for visitors and workers` = 1535.0 per_dwelling — Bicycle parking spaces for visitors and workers = 1535.0 per_dwelling is outside the universal parking bound (0.0, 5.0).
- **[error]** `Scooter parking spaces for residents (worst-case programme)` = 212.0 per_dwelling — Scooter parking spaces for residents (worst-case programme) = 212.0 per_dwelling is outside the universal parking bound (0.0, 5.0).
- **[error]** `Scooter parking spaces for visitors and workers` = 77.0 per_dwelling — Scooter parking spaces for visitors and workers = 77.0 per_dwelling is outside the universal parking bound (0.0, 5.0).

See `sanity_report.json` for the full list.

## For the Grasshopper engineer

Start with `framework.json` → `objective` and `programme` for context. Then `constraints.geometric` for the polygons (or load the `.compas` files directly). Then `constraints.numerical` for the binding rules. `massings/` contains two example variants illustrating how the inputs translate to geometry.

**What to trust most:**

- `source_type: "document"` with `confidence ≥ 0.85` — verbatim from regels or toelichting and above the review threshold.
- `cross_validation.agreement == "agreement"` — additionally confirmed by the IMRO authoritative API.
- Bouwvlak heights with `height_reconciled_from == "regels"` — the regels clause is the canonical source; verbeelding-only values may reflect drawing-association errors.

**What to treat with care:**

- `source_type: "inferred"` — derived by LLM reasoning. The entire `programme` block is inferred; treat numbers as the model's best estimate, not a brief.
- Any constraint flagged ❗ above (confidence below 0.85).
- Bouwvlak heights with `height_reconciled_from == "verbeelding_uncorrected"` — drawing value with no regels clause to confirm.

This output is **PROTOTYPE OUTPUT, NOT VERIFIED**. A project manager will review before final use in the Run system.
