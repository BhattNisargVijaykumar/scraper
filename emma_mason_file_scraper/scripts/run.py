#!/usr/bin/env python3
import os
import sys
import argparse
import logging
import csv
import json
from pathlib import Path

logger = logging.getLogger("emma_mason_runner")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)

sys.path.insert(0, str(Path(__file__).parent.parent))
from fetcher.product_fetcher import ProductFetcher, load_urls_from_file if 'load_urls_from_file' in globals() else None
from utils.sitemap_processor import SitemapProcessor

def load_urls(file_path: str):
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"URLs file not found: {file_path}")

    ext = os.path.splitext(file_path)[1].lower()
    urls = []

    if ext == ".json":
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        raw = data.get("urls", []) if isinstance(data, dict) else data
        return [str(u).strip() for u in raw if str(u).strip().startswith("http")]

    if ext == ".csv":
        priority_cols = [
            "existing_competitor_url", "competitor_url", "ref product url",
            "product url", "product_url", "url", "link", "product_link",
            "target_url", "item_url", "item url"
        ]
        with open(file_path, "r", encoding="utf-8-sig", errors="ignore") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames:
                field_map = {col.strip().lower(): col for col in reader.fieldnames if col}
                target_col = None
                for pcol in priority_cols:
                    if pcol in field_map:
                        target_col = field_map[pcol]
                        break

                if not target_col:
                    for col in reader.fieldnames:
                        if col and ("url" in col.lower() or "link" in col.lower()):
                            target_col = col
                            break

                for row in reader:
                    u_val = ""
                    if target_col:
                        u_val = row.get(target_col, "").strip()
                    else:
                        for val in row.values():
                            if val and str(val).strip().startswith("http"):
                                u_val = str(val).strip()
                                break
                    if u_val and u_val.startswith("http"):
                        urls.append(u_val)
        return urls

    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            u = line.strip()
            if u.startswith("http"):
                urls.append(u)
    return urls

def main():
    parser = argparse.ArgumentParser(description="Run Emma Mason Product File Scraper")
    parser.add_argument("--website-url", default="https://www.emmamason.com", help="Website URL to scrape")
    parser.add_argument("--urls-file", default="", help="Optional CSV/JSON/TXT file with URLs to scrape")
    parser.add_argument("--output-dir", default="output", help="Output directory for scraped CSV files")
    parser.add_argument("--job-id", default="job_id", help="Job identifier")
    parser.add_argument("--max-workers", type=int, default=int(os.getenv("MAX_WORKERS", "4")), help="Concurrency worker threads")

    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    timestamp = os.getenv("GITHUB_RUN_ID", "local")
    output_file = os.path.join(args.output_dir, f"output_emmamason_{args.job_id}_{timestamp}.csv")

    input_urls = []
    urls_file = args.urls_file

    # Auto-detect CSV in input/ folder if --urls-file is not provided
    if not urls_file:
        input_folder = os.path.join(Path(__file__).parent.parent, "input")
        if os.path.exists(input_folder):
            csv_files = [os.path.join(input_folder, f) for f in os.listdir(input_folder) if f.lower().endswith(".csv")]
            if csv_files:
                urls_file = csv_files[0]
                logger.info(f"📂 Auto-detected CSV file in input folder: {urls_file}")

    if urls_file and os.path.exists(urls_file):
        logger.info(f"📄 Loading URLs from file: {urls_file}")
        input_urls = load_urls(urls_file)
        logger.info(f"Found {len(input_urls)} product URLs")

    if not input_urls:
        logger.info("🌐 No input file provided or file empty. Harvesting URLs from Emma Mason Sitemap index...")
        processor = SitemapProcessor()
        sitemaps = processor.extract_all_sitemaps(f"{args.website_url.rstrip('/')}/sitemap.xml")
        logger.info(f"Discovered {len(sitemaps)} sitemaps")
        input_urls = sitemaps

    fetcher = ProductFetcher(
        website_url=args.website_url,
        input_urls=input_urls,
        output_dir=args.output_dir,
        max_workers=args.max_workers,
        job_id=args.job_id
    )

    result_file = fetcher.run(output_file)
    logger.info(f"✅ Scraping completed. Output saved to: {result_file}")
    return result_file

if __name__ == "__main__":
    main()
