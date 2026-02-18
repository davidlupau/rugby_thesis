# Thesis Status

# Profile

48-year old man with 20+ years experience in Learning and Development. 

Initiated 3 years ago a career switch to Data Analytics/Science

Currently in year 3 of BSc Data Science

## Tools used

- Mac os with a 8Gb RAM.
- Ubuntu installed on an external hard drive with 4GB RAM allocated from Macos to create a dedicated Data Science space
- Anaconda environment set up with key libraries installed (Pandas, scikit-learn, seaborn, numpy, matplotlib) to be used to code with Spyder
- Github account
- Plan to do the heavy ML work for this project on the cloud (Kaggles notebooks or Anaconda cloud or Google Collab). tbc

---

# **📚 Research** Topic

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

Seasons: from 2017/2018 to 2024/2025 excluding 2 seasons impacted by covid

---

# Process flow university

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

# Project Structure

```python
rugby_thesis/
│
├── build_dataset.py                  # 🔵 Phase 1: Data preparation
├── main.py                           # 🟢 Phase 2: ML analysis
│
├── data/
│   ├── raw/                          # Your scraped HTML/JSON
│   ├── processed/                    # Your CSV blocks
│   │   ├── matches.csv
│   │   ├── venues.csv
│   └── final/
│       └── top14_complete.csv        # THE dataset for ML
│
├── src/
│   ├── collection/                   # 🔵 Everything that CREATES data
│   │   ├── scrape_lnr.py
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

## Csv files status

🟠 teams.csv
🟠 seasons.csv
🟠 international_windows.csv
🟠 player_callups.csv
🟠 matches.csv
🟠 match_stats.csv
🟠 contextual_features.csv

✅ venues.csv

---

# Current status

- 🟠 Currently preparing data collection
- ✅ Decided to exclude seasons 2019/2020 and 2020/2021 as they were impacted by covid. Found a paper clearly showing the impact of home teams performances in empty stadiums
- ✅ LNR chosen as unique data source. It is the official source of truth for Top 14. The website seems relatively easy to scrape but an authorization is needed (email sent). Some extra features would be nice to have but there is a way to use the ones available.
- ✅ Got API from OpenWeather
- ✅ Decided to use relational data architecture approach. Not a proper SQL database that would over complicate things but multiple csv files with foreign keys to be merged before ML analysis instead of a huge messy csv file.
- 🟠 Pending reply from FFR and LNR regarding the data that can be provided + authorization to scrap their website. Follow up email + message via contact form sent out on Jan 17th
- 🟠 csv files created but need reshaping and update according to data collection progresses
- 🟠 creation of an ERD on LucidChart in progress. Will be updated along the way during data collection
- ✅ Matches number from round 1 to round 26 for regular season, round 27 for access match, round 28 to 30 for 1/4, 1/2 and final.
- ✅ All venues with their GPS coordinates have been listed in a dedicated csv file
- ✅ Tested Open Meteo as source for collection data about weather: validated
- ✅ Decision was made to drop attendance feature. Too much effort required for minimum relevancy. The core part of the thesis does not lie there
- ✅ fetch_weather.py created