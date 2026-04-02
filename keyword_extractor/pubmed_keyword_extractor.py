#!/usr/bin/env python3
"""
PubMed Keyword Extractor
Searches PubMed for a term and extracts keywords from top articles.

Usage:
    python pubmed_keyword_extractor.py "search term" [options]
    
Options:
    --exact-phrase          Wrap the query as an exact phrase
    -l, --limit N              Maximum number of articles to retrieve (default: 100
    -y, --years N              Limit to articles from the last N years
    --min-date YYYY/MM/DD      Minimum publication date
    --max-date YYYY/MM/DD      Maximum publication date
    -t, --article-types TYPES  Filter by article types (e.g., "Review", "Clinical Trial")
    --languages LANGS          Filter by languages (e.g., English, French)
    --journals JOURNALS       Filter by specific journals
    --mesh MESH_TERMS         Filter by MeSH terms
    --free-full-text          Only include articles with free full text
    --has-abstract           Only include articles with abstracts
    --sort SORT_OPTION        Sort order: relevance, pub_date, author, journal (default: relevance)
    -o, --output PREFIX       Output file prefix (default: pubmed_results)
    --format FORMAT           Output format: all, csv, txt (default: csv)
    --no-mesh                Exclude MeSH terms from analysis
    -q, --quiet              Suppress detailed output

Example:
    python pubmed_keyword_extractor.py "food security" --limit 100 --years 5
    python pubmed_keyword_extractor.py "food retail" --exact-phrase
"""

import argparse
import time
import csv
import json
from datetime import datetime, timedelta
from collections import Counter
from xml.etree import ElementTree as ET
import urllib.request
import urllib.parse
import urllib.error


BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

SORT_OPTIONS = {
    "relevance": "relevance",
    "pub_date": "pub_date",
    "author": "Author",
    "journal": "JournalName",
}


def prepare_query(query: str, exact_phrase: bool = False) -> str:
    query = query.strip()

    if exact_phrase:
        query = query.strip('"')
        return f'"{query}"'

    return query


def search_pubmed(query: str, limit: int = 100, filters: dict = None, sort: str = "relevance", exact_phrase: bool = False) -> list[str]:
    query = prepare_query(query, exact_phrase=exact_phrase)
    filter_parts = []

    if filters:
        if filters.get("min_date") and filters.get("max_date"):
            filter_parts.append(f'("{filters["min_date"]}"[Date - Publication] : "{filters["max_date"]}"[Date - Publication])')

        if filters.get("article_types"):
            type_queries = [f'"{atype}"[Publication Type]' for atype in filters["article_types"]]
            filter_parts.append(f"({' OR '.join(type_queries)})")

        if filters.get("languages"):
            lang_queries = [f'"{lang}"[Language]' for lang in filters["languages"]]
            filter_parts.append(f"({' OR '.join(lang_queries)})")

        if filters.get("journals"):
            journal_queries = [f'"{journal}"[Journal]' for journal in filters["journals"]]
            filter_parts.append(f"({' OR '.join(journal_queries)})")

        if filters.get("mesh_terms"):
            mesh_queries = [f'"{mesh}"[MeSH Terms]' for mesh in filters["mesh_terms"]]
            filter_parts.append(f"({' OR '.join(mesh_queries)})")

        if filters.get("free_full_text"):
            filter_parts.append("free full text[Filter]")

        if filters.get("has_abstract"):
            filter_parts.append("hasabstract[text]")

    full_query = query
    if filter_parts:
        full_query = f"({query}) AND {' AND '.join(filter_parts)}"

    params = {
        "db": "pubmed",
        "term": full_query,
        "retmax": limit,
        "retmode": "json",
        "sort": SORT_OPTIONS.get(sort, "relevance"),
    }

    url = f"{BASE_URL}/esearch.fcgi?{urllib.parse.urlencode(params)}"

    print(f"Searching PubMed for: {full_query}")
    print(f"Requesting up to {limit} results, sorted by: {sort}")

    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            data = json.loads(response.read().decode())
    except urllib.error.URLError as e:
        print(f"Error connecting to PubMed: {e}")
        return []

    result = data.get("esearchresult", {})
    pmids = result.get("idlist", [])
    total_count = result.get("count", "0")

    print(f"Found {total_count} total results, retrieved {len(pmids)} PMIDs")

    return pmids


def fetch_citation_counts(pmids: list[str], batch_size: int = 50) -> dict[str, int]:
    citation_counts = {}

    for i in range(0, len(pmids), batch_size):
        batch = pmids[i:i + batch_size]
        print(f"Fetching citation counts for articles {i + 1}-{min(i + batch_size, len(pmids))}...")

        params = {
            "dbfrom": "pubmed",
            "linkname": "pubmed_pubmed_citedin",
            "retmode": "xml",
        }
        id_params = "&".join(f"id={pmid}" for pmid in batch)
        url = f"{BASE_URL}/elink.fcgi?{urllib.parse.urlencode(params)}&{id_params}"

        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                xml_data = response.read().decode()
        except urllib.error.URLError as e:
            print(f"Error fetching citation batch: {e}")
            for pmid in batch:
                citation_counts[pmid] = 0
            continue

        try:
            root = ET.fromstring(xml_data)
        except ET.ParseError as e:
            print(f"Error parsing citation XML: {e}")
            for pmid in batch:
                citation_counts[pmid] = 0
            continue

        for linkset in root.findall(".//LinkSet"):
            id_elem = linkset.find(".//IdList/Id")
            if id_elem is None:
                continue
            pmid = id_elem.text
            count = 0
            for linksetdb in linkset.findall(".//LinkSetDb"):
                linkname_elem = linksetdb.find("LinkName")
                if linkname_elem is not None and linkname_elem.text == "pubmed_pubmed_citedin":
                    count = len(linksetdb.findall("Link"))
                    break
            citation_counts[pmid] = count

        for pmid in batch:
            if pmid not in citation_counts:
                citation_counts[pmid] = 0

        time.sleep(0.34)

    return citation_counts


def fetch_article_details(pmids: list[str], batch_size: int = 50) -> list[dict]:
    articles = []

    for i in range(0, len(pmids), batch_size):
        batch = pmids[i:i + batch_size]
        print(f"Fetching details for articles {i + 1}-{min(i + batch_size, len(pmids))}...")

        params = {
            "db": "pubmed",
            "id": ",".join(batch),
            "retmode": "xml",
        }

        url = f"{BASE_URL}/efetch.fcgi?{urllib.parse.urlencode(params)}"

        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                xml_data = response.read().decode()
        except urllib.error.URLError as e:
            print(f"Error fetching batch: {e}")
            continue

        try:
            root = ET.fromstring(xml_data)
        except ET.ParseError as e:
            print(f"Error parsing XML: {e}")
            continue

        for article_elem in root.findall(".//PubmedArticle"):
            article = parse_article(article_elem)
            if article:
                articles.append(article)

        time.sleep(0.34)

    return articles


def parse_article(article_elem) -> dict:
    article = {
        "pmid": "",
        "title": "",
        "authors": [],
        "journal": "",
        "pub_date": "",
        "year": "",
        "doi": "",
        "pubmed_url": "",
        "keywords": [],
        "mesh_terms": [],
        "abstract": "",
        "citations": 0,
    }

    pmid_elem = article_elem.find(".//PMID")
    if pmid_elem is not None:
        article["pmid"] = pmid_elem.text
        article["pubmed_url"] = f"https://pubmed.ncbi.nlm.nih.gov/{pmid_elem.text}/"

    title_elem = article_elem.find(".//ArticleTitle")
    if title_elem is not None:
        article["title"] = "".join(title_elem.itertext())

    for author in article_elem.findall(".//Author"):
        last_name = author.find("LastName")
        first_name = author.find("ForeName")
        if last_name is not None:
            name = last_name.text
            if first_name is not None:
                name = f"{first_name.text} {name}"
            article["authors"].append(name)

    journal_elem = article_elem.find(".//Journal/Title")
    if journal_elem is not None:
        article["journal"] = journal_elem.text

    pub_date = article_elem.find(".//PubDate")
    if pub_date is not None:
        year = pub_date.find("Year")
        month = pub_date.find("Month")
        day = pub_date.find("Day")
        date_parts = []
        if year is not None:
            article["year"] = year.text
            date_parts.append(year.text)
        if month is not None:
            date_parts.append(month.text)
        if day is not None:
            date_parts.append(day.text)
        article["pub_date"] = " ".join(date_parts)

    for id_elem in article_elem.findall(".//ArticleId"):
        if id_elem.get("IdType") == "doi":
            article["doi"] = id_elem.text
            break

    for keyword in article_elem.findall(".//Keyword"):
        if keyword.text:
            article["keywords"].append(keyword.text.strip())

    for mesh in article_elem.findall(".//MeshHeading/DescriptorName"):
        if mesh.text:
            article["mesh_terms"].append(mesh.text.strip())

    abstract_parts = []
    for abstract_text in article_elem.findall(".//AbstractText"):
        if abstract_text.text:
            label = abstract_text.get("Label", "")
            text = "".join(abstract_text.itertext())
            if label:
                abstract_parts.append(f"{label}: {text}")
            else:
                abstract_parts.append(text)
    article["abstract"] = " ".join(abstract_parts)

    return article


def analyze_keywords(articles: list[dict], include_mesh: bool = True) -> dict:
    all_keywords = []
    all_mesh = []

    for article in articles:
        all_keywords.extend(article.get("keywords", []))
        if include_mesh:
            all_mesh.extend(article.get("mesh_terms", []))

    keyword_counts = Counter(all_keywords)
    mesh_counts = Counter(all_mesh)
    combined_counts = Counter(all_keywords + all_mesh) if include_mesh else keyword_counts

    return {
        "total_articles": len(articles),
        "articles_with_keywords": sum(1 for a in articles if a.get("keywords")),
        "articles_with_mesh": sum(1 for a in articles if a.get("mesh_terms")),
        "unique_keywords": len(keyword_counts),
        "unique_mesh_terms": len(mesh_counts),
        "keyword_frequency": keyword_counts.most_common(),
        "mesh_frequency": mesh_counts.most_common(),
        "combined_frequency": combined_counts.most_common(),
    }


def save_articles_csv(articles: list[dict], output_prefix: str):
    csv_file = f"{output_prefix}_articles.csv"
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Rank",
            "PID",
            "Title",
            "Authors",
            "Journal",
            "Year",
            "Publication Date",
            "DOI",
            "DOI URL",
            "PubMed URL",
            "Citations",
            "Keywords",
            "MeSH Terms",
            "Abstract",
        ])
        for rank, article in enumerate(articles, start=1):
            doi = article.get("doi", "")
            doi_url = f"https://doi.org/{doi}" if doi else ""
            writer.writerow([
                rank,
                article.get("pmid", ""),
                article.get("title", ""),
                "; ".join(article.get("authors", [])),
                article.get("journal", ""),
                article.get("year", ""),
                article.get("pub_date", ""),
                doi,
                doi_url,
                article.get("pubmed_url", ""),
                article.get("citations", 0),
                "; ".join(article.get("keywords", [])),
                "; ".join(article.get("mesh_terms", [])),
                article.get("abstract", ""),
            ])
    print(f"Saved article list to: {csv_file}")


def save_results(articles: list[dict], analysis: dict, output_prefix: str, output_format: str = "all"):
    if output_format in ["all", "csv"]:
        keywords_csv_file = f"{output_prefix}_keywords.csv"
        with open(keywords_csv_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Keyword/MeSH Term", "Frequency", "Type"])

            for keyword, count in analysis["keyword_frequency"]:
                writer.writerow([keyword, count, "Author Keyword"])

            for mesh, count in analysis["mesh_frequency"]:
                writer.writerow([mesh, count, "MeSH Term"])

        print(f"Saved keyword frequencies to: {keywords_csv_file}")
        save_articles_csv(articles, output_prefix)

    if output_format in ["all", "txt"]:
        txt_file = f"{output_prefix}_summary.txt"
        with open(txt_file, "w", encoding="utf-8") as f:
            f.write("PubMed Keyword Extraction Summary\n")
            f.write("=" * 50 + "\n\n")
            f.write(f"Total articles analyzed: {analysis['total_articles']}\n")
            f.write(f"Articles with author keywords: {analysis['articles_with_keywords']}\n")
            f.write(f"Articles with MeSH terms: {analysis['articles_with_mesh']}\n")
            f.write(f"Unique author keywords: {analysis['unique_keywords']}\n")
            f.write(f"Unique MeSH terms: {analysis['unique_mesh_terms']}\n\n")

            f.write("Top 30 Author Keywords:\n")
            f.write("-" * 30 + "\n")
            for keyword, count in analysis["keyword_frequency"][:30]:
                f.write(f"  {keyword}: {count}\n")

            f.write("\nTop 30 MeSH Terms:\n")
            f.write("-" * 30 + "\n")
            for mesh, count in analysis["mesh_frequency"][:30]:
                f.write(f"  {mesh}: {count}\n")

            f.write("\nTop 30 Combined (Keywords + MeSH):\n")
            f.write("-" * 30 + "\n")
            for term, count in analysis["combined_frequency"][:30]:
                f.write(f"  {term}: {count}\n")

        print(f"Saved summary to: {txt_file}")


def print_summary(analysis: dict):
    print("\n" + "=" * 60)
    print("KEYWORD ANALYSIS SUMMARY")
    print("=" * 60)
    print(f"Total articles analyzed: {analysis['total_articles']}")
    print(f"Articles with author keywords: {analysis['articles_with_keywords']}")
    print(f"Articles with MeSH terms: {analysis['articles_with_mesh']}")
    print(f"Unique author keywords: {analysis['unique_keywords']}")
    print(f"Unique MeSH terms: {analysis['unique_mesh_terms']}")

    print("\nTop 20 Author Keywords:")
    print("-" * 40)
    for keyword, count in analysis["keyword_frequency"][:20]:
        print(f"  {count:4d} | {keyword}")

    print("\nTop 20 MeSH Terms:")
    print("-" * 40)
    for mesh, count in analysis["mesh_frequency"][:20]:
        print(f"  {count:4d} | {mesh}")


def main():
    parser = argparse.ArgumentParser(
        description="Search PubMed and extract keywords from top articles",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s "machine learning"
  %(prog)s "SDOH" --limit 200 --years 3
  %(prog)s "cancer treatment" --article-types "Review" "Clinical Trial"
  %(prog)s "COVID-19" --free-full-text --has-abstract --output covid_keywords
  %(prog)s "diabetes" --sort pub_date
        """
    )

    parser.add_argument("query", help="Search term or query")

    parser.add_argument("-l", "--limit", type=int, default=100,
                        help="Maximum number of articles to retrieve (default: 100)")
    parser.add_argument("--exact-phrase", action="store_true",
                        help="Wrap the query as an exact phrase; leave off to use raw PubMed advanced syntax")

    parser.add_argument("-y", "--years", type=int,
                        help="Limit to articles from the last N years")
    parser.add_argument("--min-date", type=str,
                        help="Minimum publication date (YYYY/MM/DD)")
    parser.add_argument("--max-date", type=str,
                        help="Maximum publication date (YYYY/MM/DD)")

    parser.add_argument("-t", "--article-types", nargs="+",
                        help="Filter by article types (e.g., 'Review', 'Clinical Trial', 'Meta-Analysis')")
    parser.add_argument("--languages", nargs="+",
                        help="Filter by languages (e.g., English, French)")
    parser.add_argument("--journals", nargs="+",
                        help="Filter by specific journals")
    parser.add_argument("--mesh", nargs="+",
                        help="Filter by MeSH terms")

    parser.add_argument("--free-full-text", action="store_true",
                        help="Only include articles with free full text")
    parser.add_argument("--has-abstract", action="store_true",
                        help="Only include articles with abstracts")

    parser.add_argument("--sort", choices=list(SORT_OPTIONS.keys()), default="relevance",
                        help="Sort order: relevance (best match), pub_date (newest first), author (first author A-Z), journal (journal name A-Z) (default: relevance)")

    parser.add_argument("-o", "--output", type=str, default="pubmed_results",
                        help="Output file prefix (default: pubmed_results)")
    parser.add_argument("--format", choices=["all", "csv", "txt"], default="csv",
                        help="Output format (default: csv)")
    parser.add_argument("--no-mesh", action="store_true",
                        help="Exclude MeSH terms from analysis")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="Suppress detailed output")

    args = parser.parse_args()

    filters = {}

    if args.years:
        today = datetime.now()
        min_date = today - timedelta(days=args.years * 365)
        filters["min_date"] = min_date.strftime("%Y/%m/%d")
        filters["max_date"] = today.strftime("%Y/%m/%d")
    elif args.min_date or args.max_date:
        if args.min_date:
            filters["min_date"] = args.min_date
        if args.max_date:
            filters["max_date"] = args.max_date

    if args.article_types:
        filters["article_types"] = args.article_types

    if args.languages:
        filters["languages"] = args.languages

    if args.journals:
        filters["journals"] = args.journals

    if args.mesh:
        filters["mesh_terms"] = args.mesh

    if args.free_full_text:
        filters["free_full_text"] = True

    if args.has_abstract:
        filters["has_abstract"] = True

    pmids = search_pubmed(
        args.query,
        limit=args.limit,
        filters=filters if filters else None,
        sort=args.sort,
        exact_phrase=args.exact_phrase,
    )

    if not pmids:
        print("No results found. Try adjusting your search terms or filters.")
        return

    articles = fetch_article_details(pmids)

    if not articles:
        print("Could not retrieve article details.")
        return

    citation_counts = fetch_citation_counts(pmids)
    for article in articles:
        article["citations"] = citation_counts.get(article["pmid"], 0)
    articles_by_pmid = {a.get("pmid"): a for a in articles if a.get("pmid")}
    articles = [articles_by_pmid[pmid] for pmid in pmids if pmid in articles_by_pmid]

    analysis = analyze_keywords(articles, include_mesh=not args.no_mesh)

    if not args.quiet:
        print_summary(analysis)

    save_results(articles, analysis, args.output, args.format)

    print(f"\nDone! Processed {len(articles)} articles.")


if __name__ == "__main__":
    main()
