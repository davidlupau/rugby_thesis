# Thesis Status

# Profile

48-year old man with 20+ years experience in Learning and Development. 

Initiated 3 years ago a career switch to Data Analytics/Science

Currently in 6th semester of BSc Data Science

## Tools used

- Mac os with a 8Gb RAM.
- Ubuntu installed on an external hard drive with 4GB RAM allocated from Macos to create a dedicated Data Science space
- Anaconda environment set up with key libraries installed (Pandas, scikit-learn, seaborn, numpy, matplotlib) to be used to code with Spyder
- Github account
- Plan to do the heavy ML work for this project on the cloud (Kaggle notebooks or Anaconda cloud or Google Collab). tbd
- Potential workflow: scrape and build `top14_complete.csv` locally/on VPS → upload to Kaggle → run all your `src/analysis/` code there → download results and figures for the thesis.
- Use of Claude Code

---

# **📚 Literature review**

## **Objective**

Establish and defend the thesis gap statement — that no existing study combines a systematic multi-family ensemble comparison with engineered international-absence and contextual features, in rugby union — before approaching the supervisor.

## Methodology

### Sourcing strategy

Candidates are sourced across four buckets, tagged on entry so coverage can be audited per bucket rather than as one undifferentiated pile:

- **A — General ML/ensemble methods** for team-sport outcome prediction (mostly football)
- **B — Rugby-specific** performance/outcome prediction
- **C — Player availability/absence/injury** as a predictive feature (any sport)
- **D — Contextual/environmental features** (weather, fixture congestion, travel)

Buckets C and D are the load-bearing ones for the thesis's novelty claim and get priority in any further sourcing. Sources used: web search, Perplexity (Feb 2026 brainstorm), and Elicit Pro (planned, targeted at C/D once Pass 1 identifies real gaps).

**Current corpus: 25 papers** in the tracker 

### Three-pass screening process

**Pass 1 — Screen.** Title and abstract only, per paper:

- Kill obvious non-fits: wrong sport family, no ML/prediction angle, not credible/peer-reviewed.
- Assign the bucket tag (A/B/C/D) if not already set.
- No scoring yet — Usefulness stays "⌛ Pending" until Pass 2 scores are entered.
- Target: cut the pool roughly in half; survivors move to Pass 2.
- *Currently owed on ~22 of the 25 tracked papers* — the 3 near-miss papers (Campos et al., Yazbek et al., O'Donoghue et al.) skipped straight to Pass 2 since they were already known must-reads.

**Pass 2 — Deep read.** For each survivor:

- Read in this order: abstract → conclusion/limitations → figures/tables → methods (lightly) → intro (skim for gap framing only).
- Score four criteria, 0–10 each: Topical Fit, Uniqueness, Scientific Validity, Practical Applicability.
- Write one sentence in the tracker's Key Insights column, following the template: *"[Paper] does ___ using ___ on ___ data. It does NOT do ___."*
- Full notes (page references, method detail) go in Zotero, attached to the reference.
- Time-box: ~25–30 min per paper.

**Pass 3 — Final selection.** From everything that clears Pass 2:

- Keep only papers that will actually be cited.
- For each, note the specific claim it supports and which thesis section it belongs to.

### Scoring model

- Relevance score = `(Topical Fit×0.35 + Uniqueness×0.30 + Scientific Validity×0.20 + Practical Applicability×0.15) × 2`, scaled to **/20**.
- Usefulness tiers (auto-derived): **⌛ Pending** (not yet scored) → **❌ Discard** (<10) → **📋 Relevant** (10–14) → **✅ Important** (15–17) → **⭐ Key paper** (≥18).
- Weights and thresholds live in the Scoring Model tab/config and are editable.

### Notes structure

- **Zotero** — source of truth for all the papers. Useful later for report writing and citation.
- **Seatable** — list all papers so that I can track them at each pass
- **Notion journal** — synthesis only, written after a batch of papers, not per-paper.
- **Notion database** for key papers that pass pass 3 to write the key insights

### Working gap statement (subject to revision after Pass 2 on the 3 near-misses)

> No existing study combines a systematic multi-family ensemble comparison with engineered international-absence and contextual features, in rugby union, using Top 14 data.
> 

### Refined gap after reading 5 key papers:

<aside>
💡

No existing study combines a systematic multi-family ensemble comparison with engineered, player-importance-weighted absence and contextual features, in rugby union, using Top 14 data.

</aside>

## **Research** Topic

**Title:** "Comparative Analysis of Ensemble Methods for Rugby Team Performance Prediction: Incorporating Tactical and Contextual Features"

**Research Questions:**

1. Which ensemble family (bagging, boosting, meta-learning) works best for rugby prediction?
2. Does complex ensemble methods (Stacking) outperform simpler approaches (Voting)?
3. How much do contextual features improve tactical-only models?
4. What is the impact of the "international players away" feature?

**Methods to Compare:**

1. Random Forest (bagging baseline)
2. XGBoost (gradient boosting)
3. LightGBM (alternative boosting)
4. Stacking Ensemble (meta-learning)
5. Voting Classifier (simple combination)

Seasons: from 2021/2022 to 2025/2026 excluding 2 seasons impacted by covid

---

# ⚙️ Process flow university

### **Pre-Registration Phase**

**Can be completed BEFORE 8-week clock starts:**

- ✅ Complete literature review
- ✅ Collect and clean rugby data
- ✅ Set up Python environment and code ensemble methods
- ✅ Write exposé and find supervisor
- ✅ Draft methodology chapter

### **Official 8-Week Period (Registration to Submission)**

**Must happen during official thesis time:**

- ⚠️ Run final model comparisons and statistical analysis
- ⚠️ Results interpretation and validation
- ⚠️ Final thesis writing and formatting
- ⚠️ Submission via Turnitin

**Key Insight:** 80% of work can be done BEFORE the 8-week clock starts!

---

# 🎓 **IU University requirements**

### **Technical Specifications**

- **Length:** 40 pages ±10% (36-44 pages for BSc)
- **Format:** Arial 11pt, 1.5 spacing, justified text
- **Structure:** Introduction → Literature Review → Methodology → Results → Discussion
- **Submission:** Online via Turnitin (<100MB PDF)

### **Registration Process**

1. Write exposé using IU template
2. Find supervisor from official Supervisor Board (one at a time, 48h response wait)
3. Sign Supervision Agreement with start date
4. Submit application via myCampus within 10-day window of start date
5. Receive confirmation email with submission deadline

### **Key Compliance Points**

- Declaration of Authenticity (signed and included)
- Maximum 30% images rule
- Proper citation format throughout
- No external plagiarism software use (advised against)

---

# 🗂️ Project Structure

```python
rugby_thesis/
│
├── build_dataset.py                  # 🔵 Phase 1: Data preparation
├── main.py                           # 🟢 Phase 2: ML analysis
│
├── data/
│   ├── raw/                          # Scraped HTML/JSON
│   ├── reference/                    # Manually created lookup tables
│   │   ├── playoffs.csv
│   │   ├── venues.csv
│   │   ├── international_calendar.csv
│   ├── processed/                    # CSV files created from scrapping
│   │   ├── matches.csv
│   │   ├── match_stats_all.csv
│   │   ├── playoff_stats.csv
│   │   ├── player_match_stats.csv
│   │   ├── players.csv
│   │   ├── regular_season_stats.csv
│   └── final/
│       └── top14_complete.csv        # THE dataset for ML
│
├── src/
│   ├── collection/                   # 🔵 Everything that CREATES data
│   │   ├── scrape_lnr.py
│   │   ├── scrape_lnr_players.py
│   │   ├── scrape_matches_list.py
│   │   ├── scrape_wikipedia.py
│   │   ├── fetch_weather.py
│   │   └── create_international_windows.py
│   │
│   ├── processing/                   # 🟡 Everything that TRANSFORMS data
│   │   ├── parse_matches.py
│   │   ├── calculate_players_away.py
│   │   ├── calculate_travel.py
│   │   ├── calculate_form.py
│   │   └── assemble_final_dataset.py
│   │
│   ├── analysis/                     # 🟢 Everything for ML (8-week period)
│   │   ├── train_models.py
│   │   ├── evaluate_models.py
│   │   ├── statistical_tests.py
│   │   └── visualizations.py
│   │
│   ├── constants.py                  # Shared everywhere
│   └── utils.py                      # Helper functions used everywhere
│
├── results/                          # Created by main.py
│   ├── figures/
│   └── tables/
│
└── notebooks/                        # For Kaggle/exploration
    └── exploratory_analysis.ipynb
```

---

# Pseudocode

| Step | What? | runs from | Files involved | Output |
| --- | --- | --- | --- | --- |
| 1 | Scrape LNR website to get the list of matches with url | build_dataset.py |  |  |
| 2 |  |  |  |  |

## Steps to build the dataset

1. **Merge match data & drop the known gaps:** Combine regular season (910 matches) and playoff (30 matches) stats into one table. Drop the matches you've now confirmed have no real stats on LNR's site: the 2022-23 Round 10-18 block, the access-match gaps, and the five 2025-26 playoff matches with placeholder zeros. This gives you your clean base match list.
2. **Fetch weather for every match:** Run the weather script against the full merged match list so each match gets temperature, rain, and wind tied to its venue and kickoff time. Already validated, should be the quickest step.
3. **Build the player registry:** Scrape each player's profile page to get season-by-season club and average minutes played, using the 1,300+ player URLs you've already collected from the match scrapes.
4. **Build the international windows calendar:** Compile the Six Nations, Autumn Internationals, and July tour windows for your five seasons, plus each nation's squad list for those windows, so you know which weeks pull players away from their clubs.
5. **Calculate the players-away feature:** For each match, weight how much of a team's usual lineup is missing to international duty, using the minutes-played data from the player registry against the international calendar. This is your thesis's core contribution.
6. **Calculate the travel feature:** Work out the distance or travel burden between venues for each match, using the GPS coordinates already sitting in venues.csv.
7. **Calculate the form feature:** Compute each team's recent results heading into a match — e.g. results from the last 5 games — to capture momentum.
8. **Assemble and validate the final dataset:** Merge every piece into one table, sanity-check it (nulls, odd distributions, a manual spot-check of a handful of matches against the source), and save it as top14_complete.csv — the single file the ML models will run on.

---

# Files Status

Python files 

csv files

---

# Current status

- 🟠 Currently preparing data collection
- ✅ Read 5 key research papers to refine the gap.
- ✅ Decided to exclude seasons 2019/2020 and 2020/2021 as they were impacted by covid. Found a paper clearly showing the impact of home teams performances in empty stadiums
- ✅ LNR chosen as unique data source. It is the official source of truth for Top 14. The website seems relatively easy to scrape but an authorization is needed (email sent). Some extra features would be nice to have but there is a way to use the ones available.
- ✅ Got API from OpenWeather
- ✅ Decided to use relational data architecture approach. Not a proper SQL database that would over complicate things but multiple csv files with foreign keys to be merged before ML analysis instead of a huge messy csv file.
- ✅ Pending reply from FFR and LNR regarding the data that can be provided + authorization to scrap their website. Follow up email + message via contact form sent out on Jan 17th. No reply. As expressed in the email, if now answer by Jan 27th,  I will proceed and use the data available on the website as this is public data.
- 🟠 csv files created but need reshaping and update according to data collection progresses
- 🟠 creation of an ERD on LucidChart in progress. Will be updated along the way during data collection
- ✅ Matches number from round 1 to round 26 for regular season, round 27 for access match, round 28 to 30 for 1/4, 1/2 and final.
- ✅ All venues with their GPS coordinates have been listed in a dedicated csv file
- ✅ Tested Open Meteo as source for collection data about weather: validated
- ✅ Decision was made to drop attendance feature. Too much effort required for minimum relevancy. The core part of the thesis does not lie there
- ✅ fetch_weather.py created
- ✅ created file to scrape match list
- ✅ Working on the file to scrape matches statistics
- ✅ Listed the main international window that impacted the Top 14
- Paused at the end of Winter 2026 to complete other module. Back to it on August 21st 2026 with “fresh” brain to work on it and free calendar
- ✅ Updated all files to reflect the new season list.
- ✅ Script now gathers the number of minutes played by each player for each match.
- ✅ International window create plus script that scrapes players called up
- ✅ calculate_players_away.py built