# SDOH Data Ontology Repo

> Lastly updated by Pengyin Shan, March 16 2026 for keyword_extraction tool

This repository contains tools and resources for creating an ontology for social determinants of health (SDOH)

## PubMed Keyword Extractor

Searches PubMed for a query term and extracts author keywords and MeSH terms from the top articles. Outputs two CSV files: one with keyword frequencies and one with full article details including citations. A text file with the raw search results is also saved for reference.

---

### Option 1: Google Colab (recommended for most users)

No installation required.

1. Open the notebook in Google Colab:
   - Go to [colab.research.google.com](https://colab.research.google.com) → File → Open notebook → GitHub tab
   - Paste this repository URL and select `pubmed_keyword_extractor.ipynb`

2. Edit the configuration cell at the top:
   ```python
   QUERY = "food security"   # your search term
   LIMIT = 100               # number of articles to retrieve
   YEARS = 5                 # restrict to last N years (set to 0 for no date filter)
   OUTPUT_PREFIX = "pubmed_results"
   ```

3. Run all cells: **Runtime → Run all**

4. Two CSV files will automatically download when complete:
   - `<prefix>_keywords.csv` — keyword and MeSH term frequencies
   - `<prefix>_articles.csv` — full article list with metadata
   - `<prefix>_summary.txt` — raw search statistics for reference
---

## Option 2: Run Locally

**Requirements:** Python 3.10+. No external packages needed (stdlib only).

```bash
git clone https://github.com/<your-username>/sdohplace-data-ontology.git
cd sdohplace-data-ontology
python pubmed_keyword_extractor.py "food security" --limit 100 --years 5
```

**Common options:**

| Flag | Description |
|------|-------------|
| `-l`, `--limit N` | Number of articles to retrieve (default: 100) |
| `-y`, `--years N` | Restrict to last N years |
| `--min-date YYYY/MM/DD` | Minimum publication date |
| `--max-date YYYY/MM/DD` | Maximum publication date |
| `-t`, `--article-types` | Filter by type (e.g. `Review`, `Clinical Trial`) |
| `--free-full-text` | Only articles with free full text |
| `--has-abstract` | Only articles with abstracts |
| `-o`, `--output PREFIX` | Output file prefix (default: `pubmed_results`) |
| `--no-mesh` | Exclude MeSH terms from analysis |

**Example:**
```bash
python pubmed_keyword_extractor.py "SDOH" --limit 200 --years 3 --output sdoh_keywords
```

Output files will be saved in the current directory.
