# Project: nieuw-legmeer

**Status:** PROTOTYPE OUTPUT, NOT VERIFIED
**Generated:** 2026-05-20T16:21:53+00:00
**Location:** Amstelveen, Nieuw Legmeer

## How to consume this output

1. `framework.json` — the structured design inputs. Top-level fields:
   `metadata`, `objective`, `constraints` (numerical, geometric, narrative),
   `variables`, `kpis`, `programme`, `geo_context`, `massings`.
   The JSON wraps the validated `ParametricFramework` with a small
   `header` block carrying the prototype banner, generation timestamp,
   tool version, and source-document checksums.
2. `geometry/*.compas` — 0 polygons (plot, bouwvlakken,
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

> Hoofdstuk 2 gaat in op de zeven kwalitatieve doelen voor Nieuw Legmeer.

> In hoofdstuk 4 wordt het kwaliteitsniveau van de openbare ruimte beschreven.

> DOEL 1 Ontwerp de binnenhoven op eigen terrein als integraal onderdeel van het publiek toegankelijk domein met een groene, Amstelveense kwaliteit.

> DOEL 2 Maak het onderscheid tussen de formele buitenwereld (straten, grachten) en de informele binnenwereld (binnenhoven, tuinen) zichtbaar.

> DOEL 3 Creëer een expressief, pand-voor-pand straatbeeld met hoge gevelplasticiteit en herkenbare eenheid in variatie.

> DOEL 4 Stel de menselijke maat centraal — ontwerp vanuit ooghoogte; plint- en entréekwaliteit is cruciaal.

> DOEL 5 Gebruik de verschillen in het landschappelijk raamwerk om openbare ruimten en straatgevels identiteit te geven.

> DOEL 6 Integreer technische ruimten en functionele voorzieningen zorgvuldig in het architectonisch geheel.

> DOEL 7 Maak Nieuw Legmeer groen, klimaatadaptief, biodivers en duurzaam.

## Programme proposal (from inference, see programme.json)

- **Target total GFA:** 589,389 m² (500,000–589,389 m²)
- **Use split:** residential 555,214 m² (94%) | productive 15,000 m² (3%) | office 5,000 m² (1%) | retail/horeca 3,025 m² (1%) | cultural 1,000 m² (0%) | social 10,150 m² (2%)
- **Dwelling count target:** 4400 (4000–4400)
- **Parking demand:** 4400 spaces
- **Tenure split:** koop 20% | middenhuur 40% | sociale_huur 20% | vrije_sector_huur 20%
- **Unit mix:**
  - sociale_huur × 30_60m2 (1br): 12% (480–560 dwellings), 45–60 m²
  - sociale_huur × 60_90m2 (2br): 8% (320–360 dwellings), 60–80 m²
  - middenhuur × 60_90m2 (2br): 25% (1000–1150 dwellings), 65–85 m²
  - middenhuur × 60_90m2 (3br): 15% (600–700 dwellings), 80–95 m²
  - vrije_sector_huur × 60_90m2 (2br): 20% (800–920 dwellings), 70–95 m²
  - koop × over_90m2 (3br): 20% (800–920 dwellings), 90–130 m²

**Rationale:** Total programme anchored to [max_bvo_ontwikkelpotentie] of 589,389 m² BVO. Non-residential uses fixed by document targets: commercial [totaal_bvo_commercieel] 3,025 m², bedrijven [min_bvo_bedrijven] ≥15,000 m², kantoren [bvo_kantoren] 3,500–6,500 m² (midpoint 5,000), cultureel [bvo_cultuur_maatschappelijk] 1,000 m², social/education (basisschool 4,230 + medisch 2,200 + cultuur excluded + horeca counted in retail) - using subset of [totaal_bvo_maatschappelijk] 22,150 m² but excluding outdoor spaces (schoolplein 2,300 + buitenruimte VO 2,100) and VO school (8,320 m²) booked separately under soci…

**Overall confidence:** 0.78 — see `programme.json` for the full reasoning trace.

## Numerical constraints (top binding values)

### Heights (26 total, showing top 15)

- **Maximale hoogte hekwerk rondom school** (`max_height_hekwerk_school`): 1 m — confidence 0.92
  - condition: Hekwerk rondom de basisschool / onderwijsgebouw
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.81
- **Maximale bouwhoogte Het Carré, Het Eiland, De Mantel** (`max_height_carre_eiland_mantel`): 6 bouwlagen — confidence 0.90
  - condition: Met uitzondering van hoogbouwaccenten. Geldt voor 'Het Carré', 'Het Eiland' en 'De Mantel'.
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.12
- **Maximale bouwhoogte Het Hart** (`max_height_het_hart`): 4 bouwlagen — confidence 0.90
  - condition: Geldt voor deelgebied 'Het Hart'. Lagere hoogte om het intieme karakter te borgen.
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.12
- **Maximale hoogte maaiveld binnenhof t.o.v. openbare ruimte** (`max_maaiveld_hoogte`): 1.5 m — confidence 0.90
  - condition: Hoogte van het maaiveld van binnenhoven ten opzichte van de omliggende openbare ruimte; uitzondering geldt ter plaatse van bomen
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.25
- **Hoogbouwaccent hoogte** (`hoogbouwaccent_bouwlagen`): 12–14 bouwlagen — confidence 0.85
  - condition: Voor hoogbouwaccenten
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.39
- **Plinthoogte** (`plint_height_range`): 4–6 m — confidence 0.85
  - condition: De plint telt als één bouwlaag.
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.12
- **Maximum plint height** (`plint_height_max`): 6 m — confidence 0.85
  - condition: Plint counts as one bouwlaag
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.56
- **Maximum clear height plint with residential function** (`plint_wonen_height_max`): 6 m — confidence 0.85
  - condition: Wanneer een woonfunctie in de plint is gevestigd, grenzend aan de openbare ruimte
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.56
- **Totaal aantal bouwlagen parkeergebouw** (`max_total_bouwlagen_parking_building`): 6 bouwlagen — confidence 0.85
  - condition: Parkeergebouw; begane grond als eerste laag geteld
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.85
- **Maximale bouwhoogte algemeen (Amstelveense hoogte)** (`max_height_general_bouwlagen`): 6 bouwlagen — confidence 0.85
  - condition: Geldt als maximale bouwhoogte voor alle bebouwing in Legmeer (basislaag); incidentele hoogbouwaccenten zijn bovenop deze basislaag toegestaan.
  - source: Bijlage 1 - Stedenbouwkundig plan Nieuw Legmeer.pdf p.33
- **Maximaal aantal parkeerlagen parkeergebouw** (`max_parking_layers`): 5 bouwlagen — confidence 0.85
  - condition: Parkeerlagen; begane grond als eerste laag geteld. Totaal aantal bouwlagen inclusief begane grond = 6.
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.85
- **Minimum plint height – Carré** (`plint_min_height_carre`): 4 m — confidence 0.85
  - condition: Ground floor plint (BG/PLINT) of the Carré building type
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.65
- **Maximale bouwhoogte 'Het Hart'** (`max_height_het_hart_bouwlagen`): 4 bouwlagen — confidence 0.85
  - condition: Van toepassing op sfeergebied 'Het Hart', vanwege het afwijkende karakter van dit gebied.
  - source: Bijlage 1 - Stedenbouwkundig plan Nieuw Legmeer.pdf p.33
- **Minimum plint height** (`plint_height_min`): 3.5 m — confidence 0.85
  - condition: Plint counts as one bouwlaag
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.56
- **Minimum clear height plint with residential function** (`plint_wonen_height_min`): 3 m — confidence 0.85
  - condition: Wanneer een woonfunctie in de plint is gevestigd, grenzend aan de openbare ruimte
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.56
- … and 11 more in `framework.json` → `constraints.numerical` (category = `height`).

### Setbacks (35 total, showing top 15)

- **Max. breedte privéruimte op maaiveldniveau** (`max_setback_private_ground_level`): 2 m — confidence 0.92
  - condition: Privéruimtes op maaiveldniveau binnen binnenhoven
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.27
- **Minimale onderlinge afstand hoogbouwaccenten (hart-hart)** (`min_distance_hoogbouwaccenten`): 60 m — confidence 0.90
  - condition: Gemeten van kern tot kern, met name in de randen van de wijk.
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.12
- **Hoofdgracht Profiel B2-B2' – Totale profielbreedte** (`hoofdgracht_profiel_b2_b2_total_width`): 27.8 m — confidence 0.90
  - condition: Profiel B2-B2' Hoofdgracht (30 km twee richtingen)
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.97
- **Carré profiel E-E' totale breedte** (`profile_ee_total_width`): 25.5 m — confidence 0.90
  - condition: Carré - profiel E-E' (30 km twee richtingen)
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.102
- **Street profile L-L' total width** (`straat_profiel_ll_total_width`): 21.75 m — confidence 0.90
  - condition: Street profile L-L' (30 km two directions)
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.114
- **Total width street profile J-J'** (`street_profile_jj_total_width`): 21.1 m — confidence 0.90
  - condition: Street profile J-J' (30 km two directions)
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.112
- **Carré profiel G-G' totale breedte (langzaamverkeersverbinding)** (`carre_profiel_gg_total_width`): 17.5 m — confidence 0.90
  - condition: Profiel G-G' langzaamverkeersverbinding in het Carré
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.104
- **Minimale afstand tussen twee achterzijden van gebouwen** (`min_afstand_achterzijden`): 15 m — confidence 0.90
  - condition: Afstand tussen twee achterzijden van gebouwen
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.32
- **Minimale breedte programmatische plint bij halfverdiepte parkeeroplossing** (`min_plint_breedte_halfverdiepte_garage`): 6 m — confidence 0.90
  - condition: Halfverdiepte parkeeroplossingen richting het openbaar gebied; gerekend vanuit de voorgevel van een gebouw
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.25
- **Minimum height for outdoor spaces on public-facing facades** (`min_height_balcony_public_facade`): 4 m — confidence 0.90
  - condition: Buitenruimtes aan gevels gelegen aan de openbare ruimte
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.51
- **Maximum entry recess depth in facade** (`entree_setback_max`): 2 m — confidence 0.90
  - condition: Entrees gelegen aan de openbare ruimte
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.59
- **Maximum balcony protrusion above 4 m (public facade)** (`max_balcony_protrusion_above_4m`): 1.5 m — confidence 0.90
  - condition: Buitenruimtes aan gevels gelegen aan de openbare ruimte, boven 4 m hoogte
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.51
- **Stoepenzone depth – Het Hart and Het Eiland** (`stoepenzone_depth_hart_eiland`): 0.4–1 m — confidence 0.90
  - condition: Stoepenzone in 'Het Hart' en op 'Het Eiland'
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.123
- **Maximum balcony protrusion below 4 m (public facade)** (`max_balcony_protrusion_below_4m`): 0.5 m — confidence 0.90
  - condition: Onder de 4 meter, buitenruimtes aan openbare gevels
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.51
- **Minimum entry recess depth in facade** (`entree_setback_min`): 0.5 m — confidence 0.90
  - condition: Entrees gelegen aan de openbare ruimte
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.59
- … and 20 more in `framework.json` → `constraints.numerical` (category = `setback`).

### Footprint / coverage (11 total, showing top 11)

- **Maximum bebouwd oppervlakte per ontwikkelcluster** (`max_footprint_ontwikkelcluster`): 70 % — confidence 0.95
  - condition: Per ontwikkelcluster
  - source: Bijlage 1 - Stedenbouwkundig plan Nieuw Legmeer.pdf p.28
- **Minimum onbebouwd oppervlakte per ontwikkelcluster** (`min_unbuilt_ontwikkelcluster`): 30 % — confidence 0.95
  - condition: Per ontwikkelcluster
  - source: Bijlage 1 - Stedenbouwkundig plan Nieuw Legmeer.pdf p.28
- **Maximale frontbreedte gebouw** (`max_frontbreedte_gebouw`): 25 m — confidence 0.92
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.37
- **Minimum bebouwing rooilijn** (`min_rooilijn_bebouwd`): 80 % — confidence 0.90
  - condition: Van de lengte van elke rooilijn
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.32
- **Maximaal bebouwd percentage per cluster** (`max_footprint_per_cluster`): 70 % — confidence 0.90
  - condition: Per ontwikkelcluster
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.11
- **Maximale horizontale diameter gebouwen vanaf 7e bouwlaag** (`max_horizontal_diameter_above_7th_floor`): 45 m — confidence 0.90
  - condition: Gerekend vanaf de 7e bouwlaag.
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.12
- **Minimaal onbebouwd percentage per cluster** (`min_unbuilt_per_cluster`): 30 % — confidence 0.90
  - condition: Per ontwikkelcluster; bovengronds onbebouwd
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.11
- **Minimaal breedte verschil naast elkaar staande panden** (`min_breedte_verschil_naastgelegen_panden`): 5 m — confidence 0.90
  - condition: Naast elkaar staande panden
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.37
- **Maximale breedte smal gebouw per clusterzijde** (`max_breedte_cluster_zijde_gebouw`): 15 m — confidence 0.88
  - condition: Elke zijde van het cluster heeft minimaal één gebouw met een maximale breedte van 15 meter. Indien de zijde langer is dan 100 meter, zijn minimaal twee gebouwen van maximaal 15 meter breed vereist.
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.37
- **Verhard oppervlak percentage Legmeer (huidige situatie)** (`current_paved_percentage`): 79 % — confidence 0.85
  - condition: Bestaande situatie Legmeer bedrijventerrein
  - source: Bijlage 1 - Stedenbouwkundig plan Nieuw Legmeer.pdf p.13
- **Bebouwd/onbebouwd verhouding per cluster** (`bebouwd_onbebouwd_ratio`): 70 % — confidence 0.85
  - source: Bijlage 1 - Stedenbouwkundig plan Nieuw Legmeer.pdf p.18

### Programme BVO caps and floors (16 total, showing top 15)

- **Maximaal BVO ontwikkelpotentie Nieuw-Legmeer** (`max_bvo_ontwikkelpotentie`): 589389 m2 — confidence 0.90
  - source: Bijlage 1 - Stedenbouwkundig plan Nieuw Legmeer.pdf p.30
- **Totaal BVO maatschappelijk programma** (`totaal_bvo_maatschappelijk`): 22150 m2 — confidence 0.85
  - condition: Totaal maatschappelijk programma
  - source: Bijlage 1 - Stedenbouwkundig plan Nieuw Legmeer.pdf p.42
- **BVO Voortgezet onderwijs / Middelbaar beroepsonderwijs** (`bvo_voortgezet_onderwijs`): 8320 m2 — confidence 0.85
  - condition: Maatschappelijk programma
  - source: Bijlage 1 - Stedenbouwkundig plan Nieuw Legmeer.pdf p.42
- **Totaal minimum BVO commercieel programma** (`totaal_bvo_commercieel`): 3025 m2 — confidence 0.85
  - condition: Totaal commercieel programma
  - source: Bijlage 1 - Stedenbouwkundig plan Nieuw Legmeer.pdf p.42
- **BVO Medisch centrum** (`bvo_medisch_centrum`): 2200 m2 — confidence 0.85
  - condition: Maatschappelijk programma
  - source: Bijlage 1 - Stedenbouwkundig plan Nieuw Legmeer.pdf p.42
- **Minimum BVO Supermarkt** (`min_bvo_supermarkt`): 1800 m2 — confidence 0.85
  - condition: Commercieel programma
  - source: Bijlage 1 - Stedenbouwkundig plan Nieuw Legmeer.pdf p.42
- **BVO Cultuur/maatschappelijk** (`bvo_cultuur_maatschappelijk`): 1000 m2 — confidence 0.85
  - condition: Maatschappelijk programma
  - source: Bijlage 1 - Stedenbouwkundig plan Nieuw Legmeer.pdf p.42
- **Minimum BVO Overig dagelijks** (`min_bvo_overig_dagelijks`): 500 m2 — confidence 0.85
  - condition: Commercieel programma
  - source: Bijlage 1 - Stedenbouwkundig plan Nieuw Legmeer.pdf p.42
- **Minimum BVO Niet-dagelijks** (`min_bvo_niet_dagelijks`): 300 m2 — confidence 0.85
  - condition: Commercieel programma
  - source: Bijlage 1 - Stedenbouwkundig plan Nieuw Legmeer.pdf p.42
- **Minimum BVO Wijk-/centrumgebonden horeca** (`min_bvo_horeca`): 200 m2 — confidence 0.85
  - condition: Commercieel programma; exclusief horeca categorie 2 en 3
  - source: Bijlage 1 - Stedenbouwkundig plan Nieuw Legmeer.pdf p.42
- **Minimum BVO Commerciële dienstverlening** (`min_bvo_commerciele_dienstverlening`): 150 m2 — confidence 0.85
  - condition: Commercieel programma
  - source: Bijlage 1 - Stedenbouwkundig plan Nieuw Legmeer.pdf p.42
- **Minimum BVO Bedrijven** (`min_bvo_bedrijven`): 15000 m2 — confidence 0.80 ❗
  - condition: Programmering op basis van Herziene ontwikkelvisie Legmeer 2024
  - source: Bijlage 1 - Stedenbouwkundig plan Nieuw Legmeer.pdf p.42
- **BVO Kantoren (bandbreedte)** (`bvo_kantoren`): 3500–6500 m2 — confidence 0.80 ❗
  - condition: Programmering op basis van Herziene ontwikkelvisie Legmeer 2024
  - source: Bijlage 1 - Stedenbouwkundig plan Nieuw Legmeer.pdf p.42
- **BVO Schoolplein (basisschool)** (`bvo_schoolplein`): 2300 m2 — confidence 0.80 ❗
  - condition: Maatschappelijk programma
  - source: Bijlage 1 - Stedenbouwkundig plan Nieuw Legmeer.pdf p.42
- **BVO Buitenruimte voortgezet onderwijs** (`bvo_vo_buitenruimte`): 2100 m2 — confidence 0.80 ❗
  - condition: Maatschappelijk programma; buitenruimte bij voortgezet onderwijs/MBO
  - source: Bijlage 1 - Stedenbouwkundig plan Nieuw Legmeer.pdf p.42
- … and 1 more in `framework.json` → `constraints.numerical` (category = `bvo_limit`).

### Parking norms (1 total, showing top 1)

- **Pre-investment parking garages** (`parking_garage_preinvestment`): 2e+07 EUR — confidence 0.75 ❗
  - condition: Provisional pre-investment amount for parking garages where on-site underground parking is not feasible; to be recovered from landowner contributions or garage exploitation.
  - source: Bijlage 2 - Brede Businesscase Nieuw Legmeer 2024 bij collegevoorstel Businesscase Nieuw Legmeer 2024.pdf p.4

### Use mix (3 total, showing top 3)

- **Aandeel middelduur woningen** (`aandeel_middelduur_woningen`): 40 percent — confidence 0.85
  - applies to: max_woningen_nieuw_legmeer
  - source: Bijlage 1 - Stedenbouwkundig plan Nieuw Legmeer.pdf p.30
- **Aandeel vrije sector woningen** (`aandeel_vrije_sector_woningen`): 40 percent — confidence 0.85
  - applies to: max_woningen_nieuw_legmeer
  - source: Bijlage 1 - Stedenbouwkundig plan Nieuw Legmeer.pdf p.30
- **Aandeel sociale woningen** (`aandeel_sociaal_woningen`): 20 percent — confidence 0.85
  - applies to: max_woningen_nieuw_legmeer
  - source: Bijlage 1 - Stedenbouwkundig plan Nieuw Legmeer.pdf p.30

### Sustainability (28 total, showing top 15)

- **Hevige neerslag 1/250 jaar – vitale infrastructuur functioneel** (`rainfall_vital_infra_250yr`): 90 mm/uur — confidence 0.90
  - condition: 1/250 jaar neerslaggebeurtenis (90 mm in een uur)
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.73
- **Hevige neerslag 1/100 jaar – geen schade aan gebouwen** (`rainfall_damage_threshold_100yr`): 70 mm/uur — confidence 0.90
  - condition: 1/100 jaar neerslaggebeurtenis (70 mm in een uur)
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.73
- **Minimum grondpakket diepte daken parkeervoorzieningen** (`min_substrate_depth_parking_roof`): 40 cm — confidence 0.90
  - condition: Daken van parkeervoorzieningen
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.76
- **Minimum groen dak onderste zes bouwlagen** (`min_green_roof_lower_floors`): 30 % — confidence 0.90
  - condition: Daken op de onderste zes bouwlagen
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.76
- **Minimum grondpakket diepte groene dakinrichting** (`min_substrate_depth_green_roof`): 30 cm — confidence 0.90
  - condition: Standaard groene dakinrichting, exclusief drainage en waterberging
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.76
- **Minimum aandeel 'volle grond' in onbebouwde ruimte per ontwikkelcluster** (`min_volle_grond_unbuilt_space`): 30 % — confidence 0.90
  - condition: Van de onbebouwde ruimte per ontwikkelcluster
  - source: Bijlage 1 - Stedenbouwkundig plan Nieuw Legmeer.pdf p.28
- **Minimum insectvriendelijke planten op daktuin** (`min_insect_plants_daktuin`): 20 stuks — confidence 0.90
  - condition: Op een daktuin
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.75
- **Maximale afvoer naar openbaar water** (`max_discharge_to_open_water`): 15 m³/min/100ha — confidence 0.90
  - condition: Na filtratie via wadi's, kratten of andere voorzieningen; directe lozing naar open water is niet toegestaan
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.73
- **Maximaal debiet vertraagde afvoer privaat terrein** (`max_discharge_rate_private`): 1.2 liter/m²/uur — confidence 0.90
  - condition: Waterberging privaatterrein – vertraagde afvoer
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.73
- **Minimum substraatdikte natuurdak (daktuinen/parkeergarages)** (`min_substrate_natuurdak`): 40 cm — confidence 0.88
  - condition: Daktuinen of daken van parkeergarages die onderdeel zijn van de 70% hoogwaardige groene inrichting binnen het cluster
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.76
- **Biodiversiteitsvoorzieningen per 110 m² gevel- en dakoppervlakte** (`biodiversity_provisions_per_110m2`): 110 m2 — confidence 0.85
  - condition: Per 110 m² gesloten gevel- en dakoppervlakte (vergelijkbaar met een rijwoning)
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.75
- **Waterberging privaat terrein – verwerking 70 mm neerslag op eigen terrein** (`water_retention_private_terrain_70mm`): 70 mm/uur — confidence 0.85
  - condition: Basisveiligheidsniveau: hevige bui op bebouwd deel van privaat terrein
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.73
- **Minimum hoogwaardig groen onbebouwde ruimte** (`min_green_unbuild_space`): 70 % — confidence 0.85
  - condition: Onbebouwde ruimte
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.77
- **Waterberging voorzieningen – maximaal 60 uur teruglooptijd** (`water_retention_availability_max_60hr`): 60 uur — confidence 0.85
  - condition: Na vertraagde afvoer gedurende eerste 24 uur
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.73
- **Maximum aandeel PV-panelen op groene daken** (`max_pv_combination_green_roof`): 50 % — confidence 0.85
  - condition: Groene daken gecombineerd met PV-panelen
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.76
- … and 13 more in `framework.json` → `constraints.numerical` (category = `sustainability`).

### Accessibility (2 total, showing top 2)

- **Max. hellingbaan fietsenstalling** (`max_ramp_gradient_bike_storage`): 4 percent — confidence 0.90
  - condition: When collective bike storage is half-sunken or half-raised relative to ground level (halfverlaagd/halfverhoogd)
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.67
- **Maximale helling oever toegang water (mindervalide)** (`max_hellingpercentage_oever`): 6.5 percent — confidence 0.80 ❗
  - condition: Helling van de oever/brug toegang voor mindervalide toegankelijkheid
  - source: Bijlage 1 - Stedenbouwkundig plan Nieuw Legmeer.pdf p.36

### Other (84 total, showing top 15)

- **Totale financiering Nieuw Legmeer** (`total_financing_nieuw_legmeer`): 233 mln EUR — confidence 0.95
  - source: Bijlage 2 - Brede Businesscase Nieuw Legmeer 2024 bij collegevoorstel Businesscase Nieuw Legmeer 2024.pdf p.5
- **Maximum snelheidsregime Legmeer** (`max_speed_legmeer`): 30 km/uur — confidence 0.95
  - source: Bijlage 1 - Stedenbouwkundig plan Nieuw Legmeer.pdf p.40
- **Totaal risicoprofiel Nieuw Legmeer** (`total_risk_profile`): 28 mln EUR — confidence 0.95
  - source: Bijlage 2 - Brede Businesscase Nieuw Legmeer 2024 bij collegevoorstel Businesscase Nieuw Legmeer 2024.pdf p.5
- **Maximum bridge slope (licht getoogd)** (`max_bridge_slope`): 6.5 percent — confidence 0.95
  - condition: Applies to all bridges in Nieuw Legmeer
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.119
- **Minimum bridge clearance width (doorvaarbreedte)** (`min_bridge_clearance_width`): 4 m — confidence 0.95
  - condition: Minimum clearance width for recreational navigation and maintenance
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.119
- **Jaarlijkse annuïteit totaal** (`annual_annuity_total`): 3.78 mln EUR/jaar — confidence 0.95
  - source: Bijlage 2 - Brede Businesscase Nieuw Legmeer 2024 bij collegevoorstel Businesscase Nieuw Legmeer 2024.pdf p.5
- **Financieringslast (alleen overig)** (`financing_charge_overig`): 2.46 mln EUR/jaar — confidence 0.95
  - condition: alleen overig (direct-financed portion only)
  - source: Bijlage 2 - Brede Businesscase Nieuw Legmeer 2024 bij collegevoorstel Businesscase Nieuw Legmeer 2024.pdf p.5
- **Minimum bridge clearance height (doorvaarhoogte)** (`min_bridge_clearance_height`): 1.5 m — confidence 0.95
  - condition: Minimum clearance height for recreational navigation (canoes and small boats) and maintenance
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.119
- **Straat profiel O-O' totale breedte** (`street_profile_oo_width_total`): 21.1 m — confidence 0.92
  - condition: Straat profiel O-O' (30 km twee richtingen)
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.117
- **Gracht profiel I-I' total width** (`gracht_profiel_ii_total_width`): 12 m — confidence 0.92
  - condition: Gracht - profiel I-I' (fietsverbinding twee richtingen)
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.109
- **Maximale breedte blinde gevel zonder openingen** (`max_blinde_gevel_breedte`): 6 m — confidence 0.92
  - condition: Een blinde gevel zonder openingen
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.69
- **Max. hoogte erfafscheiding achtertuin grondgebonden woning** (`max_height_rear_garden_fence`): 1.5 m — confidence 0.92
  - condition: Achtertuinen van eengezins grondgebondenwoningen
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.27
- **Max. hoogte afscheiding privéruimte op maaiveldniveau** (`max_height_private_ground_level_screen`): 1 m — confidence 0.92
  - condition: Haag of transparant hekwerk rondom privéruimtes op maaiveld
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.27
- **Max. hoogte erfafscheiding voorgevel grondgebonden woning** (`max_height_front_facade_fence`): 1 m — confidence 0.92
  - condition: Aan de voorgevel van grondgebonden woningen
  - source: Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.27
- **Investering VO-school (raming)** (`investering_vo_school`): 2.2e+07 EUR — confidence 0.90
  - condition: School voor 500-600 leerlingen inclusief gymzaal
  - source: Bijlage 2 - Brede Businesscase Nieuw Legmeer 2024 bij collegevoorstel Businesscase Nieuw Legmeer 2024.pdf p.3
- … and 69 more in `framework.json` → `constraints.numerical` (category = `other`).

See `framework.json` → `constraints.numerical` for all 206 constraints with full provenance (document, page, verbatim Dutch text) and confidence scores.

## Geometric constraints

Polygon counts by feature type:

Source drawing:
- File: Bijlage 1 - Stedenbouwkundig plan Nieuw Legmeer-verbeelding.pdf

Reconciled with regels for bouwvlak heights — see the Reconciliation summary below and `reconciliation_report.json`.

## Narrative constraints (selected)

- **This image is a visualisation of a possible design. No rights can be derived from this image.** (`visualisation_disclaimer`, ambiguity_flag) — confidence 1.00
  > "Visualisatie van een mogelijk ontwerp. Aan dit beeld kunnen geen rechten worden ontleend." — Bijlage 1 - Stedenbouwkundig plan Nieuw Legmeer.pdf p.46
- **The rules (spelregels) take precedence over the shown reference images in chapters 2, 3 and 4 of the beeldkwaliteitsplan.** (`spelregels_leidend_over_referentiebeelden`, process) — confidence 0.95
  > "Met betrekking tot hoofdstukken 2, 3 en 4 geldt dat de spelregels leidend zijn ten opzichte van de getoonde referentiebeelden." — Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.3
- **No rights can be derived from any maps, drawings, visualisations or other imagery included in this document.** (`no_rights_from_visuals`, process) — confidence 0.95
  > "Aan alle in dit document opgenomen kaarten, tekeningen, visualisaties en overig beeldmateriaal kunnen geen rechten worden ontleend." — Bijlage 1 - Stedenbouwkundig plan Nieuw Legmeer.pdf p.6
- **All spatial initiatives for Nieuw Legmeer must be assessed by a Quality team (Q-team) against the goals and rules of the beeldkwaliteitsplan, the clusterpaspoorten including the spelregelkaart, and the Stedenbouwkundig plan. The Q-team monitors coherence and desired image quality of landscape, architecture and public space, and advises the College B&W.** (`quality_team_review_process`, process) — confidence 0.92
  > "Alle ruimtelijke initiatieven worden in een Q-team getoetst aan de hand van de doelen en spelregels uit het beeldkwaliteitsplan, de clusterpaspoorten inclusief spelregelkaart en het Stedenbouwkundig plan." — Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.15
- **The beeldkwaliteitsplan, together with supplementary rules (spelregels), forms the quality assessment framework (toetsingskader) for spatial quality of all developments in Nieuw Legmeer.** (`beeldkwaliteitsplan_toetsingskader`, urban_design) — confidence 0.90
  > "Samen met aanvullende spelregels vormen de doelen en het beeldkwaliteitsplan het toetsingskader voor de ruimtelijke kwaliteit voor ontwikkelingen in Nieuw Legmeer." — Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.5
- **For every high-rise initiative, the effects on wind nuisance (windhinder) and cast shadow (slagschaduw) must be demonstrated.** (`hoogbouw_wind_shadow_study`, process) — confidence 0.90
  > "Voor elk hoogbouwinitiatief moeten de effecten op windhinder en slagschaduw worden aangetoond." — Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.12
- **The plinth (plint) counts as one bouwlaag when calculating building height.** (`plint_counts_as_one_floor`, urban_design) — confidence 0.90
  > "De plint telt als één bouwlaag." — Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.12
- **If a design deviates from the beeldkwaliteitsplan on any aspect, alignment must take place with the Q-team, which in turn issues advice to the College van B&W.** (`quality_team_deviation_procedure`, process) — confidence 0.90
  > "Indien een ontwerp op onderdelen afwijkt van het beeldkwaliteitsplan vindt er afstemming plaats met het Q-team dat op haar beurt advies uit brengt aan het College van B&W." — Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.15
- **Gates (poorten) and openings must be designed as a distinctive architectural landmark along informal pedestrian routes and serve as transitions between the public realm and the binnenhof (inner courtyard). The ambition is to create a world of gates and openings as a characteristic architectural identity marker of Nieuw Legmeer.** (`poorten_architectonisch_beeldmerk`, urban_design) — confidence 0.90
  > "De ambitie is een wereld van poorten en openingen te creëren, als kenmerkend, architectonisch beeldmerk van Nieuw Legmeer." — Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.21
- **The width of an opening (B) must equal half the depth of the adjacent building (D): B = ½D, using the shallowest adjacent building depth as the reference.** (`opening_breedte_gebouwdiepte_ratio`, urban_design) — confidence 0.90
  > "De breedte van een opening is gelijk aan de helft van de aangrenzende gebouwdiepte (B = 1/2 D), waarbij de minst diepe gebouwdiepte wordt gerekend." — Bijlage 1 - Beeldkwaliteitplan Nieuw Legmeer.pdf p.21
- … and 328 more in `framework.json` → `constraints.narrative`.

## Flagged ambiguities

- **15 numerical constraints with confidence < 0.80:** review before relying on them. Listed with the ❗ marker under the relevant category above.
- **59 narrative constraints with confidence < 0.80.**
- **13 pages had extraction errors** (see `extraction_raw.json` → `pages_with_extraction_errors`).

## Data sources used

- ✓ Document extraction: 206 numerical, 338 narrative constraints across 3 PDFs (180 pages total).
- ✗ Vector geometry: parsing failed (Could not derive scale: no Measure dictionary on the page and no 'Schaal 1:N' text found. Manual scale entry required.).
- ✗ IMRO API cross-validation: 0 agreed, 0 disagreed, 0 unverifiable, 206 not attempted (API unavailable).
- ✓ PDOK BAG: 1000 buildings within 2000 m (year built 1823–9999).
- ✗ 3D BAG: not available — 2D context only for massing visualisation.
- ✓ CBS demographics (buurt BU03621104): pop 230, 165 households, avg household size 1.3, median age None.
- ✓ OSM Overpass: bus 249 m, tram 309 m, 272 amenities across 55 categories.

## Sanity check

No physical-sense violations detected. Every numerical constraint sits within universal bounds (heights 3–200 m, FSI 0–8, parking 0–4/dwelling, GFA 100–1,000,000 m²) and the programme is internally consistent.

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
