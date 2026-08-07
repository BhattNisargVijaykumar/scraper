#!/usr/bin/env python3
import os
import sys
import argparse
import logging
import csv
import json
import tempfile
import ftplib
from pathlib import Path
from typing import List

logger = logging.getLogger("fetch_input_urls")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)

sys.path.insert(0, str(Path(__file__).parent.parent))

def save_urls_to_csv(urls: List[str], output_file: str):
    """Writes a list of URLs to the standard remaining_merged.csv structure."""
    out_dir = os.path.dirname(output_file)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    clean_urls = []
    seen = set()
    for u in urls:
        u_str = str(u).strip()
        if u_str and u_str.startswith("http") and u_str not in seen:
            seen.add(u_str)
            clean_urls.append(u_str)

    header = ["url", "status", "error_type", "error_message", "failed_at", "job_id", "chunk_id"]
    with open(output_file, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for u in clean_urls:
            writer.writerow([u, "", "", "", "", "", ""])

    logger.info(f"Successfully saved {len(clean_urls)} unique URLs to {output_file}")
    return len(clean_urls)

def fetch_from_ftp(host: str, port: int, user: str, pass_: str, remote_dir: str, target_filename: str = "") -> List[str]:
    logger.info(f"Connecting to FTP {host}:{port} as user '{user}'...")
    ftp = ftplib.FTP()
    ftp.connect(host, port, timeout=30)
    ftp.login(user, pass_)

    if target_filename:
        target_filename = target_filename.strip()
        if "/" in target_filename or "\\" in target_filename:
            parts = target_filename.replace("\\", "/").lstrip("/").split("/")
            sub_dir = "/".join(parts[:-1])
            target_filename = parts[-1]
            if remote_dir:
                remote_dir = remote_dir.rstrip("/") + "/" + sub_dir
            else:
                remote_dir = "/" + sub_dir

    if remote_dir:
        ftp.cwd(remote_dir)
        logger.info(f"Changed directory to remote path: {remote_dir}")

    items = ftp.nlst()
    logger.info(f"Found {len(items)} items in remote FTP directory.")

    target_file = ""
    if target_filename and target_filename in items:
        target_file = target_filename
    elif target_filename:
        for it in items:
            if it.lower() == target_filename.lower():
                target_file = it
                break
        if not target_file:
            raise FileNotFoundError(f"Specified file '{target_filename}' not found in FTP folder '{remote_dir}'. Available: {items[:20]}...")
    else:
        csv_files = [it for it in items if it.lower().endswith(".csv")]
        if not csv_files:
            raise FileNotFoundError(f"No .csv files found in FTP directory '{remote_dir}'.")
        target_file = csv_files[0]
        logger.info(f"Auto-selected CSV file from FTP: {target_file}")

    logger.info(f"Downloading '{target_file}' from FTP...")
    urls = []
    tmp_fd, tmp_name = tempfile.mkstemp(suffix=".csv")
    try:
        with os.fdopen(tmp_fd, "wb") as tmp:
            ftp.retrbinary(f"RETR {target_file}", tmp.write)
        ftp.quit()

        with open(tmp_name, "r", encoding="utf-8-sig", errors="ignore") as f:
            reader = csv.reader(f)
            header = None
            url_idx = -1

            priority_cols = [
                "existing_competitor_url", "competitor_url", "ref product url",
                "product url", "product_url", "url", "link", "product_link",
                "target_url", "item_url", "item url"
            ]

            for row in reader:
                if not row:
                    continue
                if header is None:
                    header = [c.strip().lower() for c in row]
                    for pcol in priority_cols:
                        for idx, col in enumerate(header):
                            if col == pcol:
                                url_idx = idx
                                break
                        if url_idx != -1:
                            break

                    if url_idx == -1:
                        for idx, col in enumerate(header):
                            if "url" in col or "link" in col:
                                url_idx = idx
                                break

                    if url_idx != -1:
                        logger.info(f"Selected column index {url_idx} ('{header[url_idx]}') for product URLs")
                    else:
                        if row[0].strip().startswith("http"):
                            urls.append(row[0].strip())
                            url_idx = 0
                    continue

                if url_idx != -1 and len(row) > url_idx:
                    u = row[url_idx].strip()
                    if u.startswith("http"):
                        urls.append(u)
                else:
                    for cell in row:
                        c = cell.strip()
                        if c.startswith("http"):
                            urls.append(c)
                            break
    finally:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)

    logger.info(f"Extracted {len(urls)} URLs from FTP file '{target_file}'")
    return urls

def fetch_from_sitemap(sitemap_url: str) -> List[str]:
    from utils.sitemap_processor import SitemapProcessor
    logger.info(f"Fetching sitemap from: {sitemap_url}")
    processor = SitemapProcessor()

    all_sitemaps = processor.extract_all_sitemaps(sitemap_url)
    product_urls = []
    for sm in all_sitemaps:
        if sm.startswith("http"):
            if "sitemap" in sm.lower():
                try:
                    sub_urls = processor.extract_all_sitemaps(sm)
                    for u in sub_urls:
                        if u.startswith("http"):
                            product_urls.append(u)
                except Exception as e:
                    logger.warning(f"Error extracting sub-sitemap {sm}: {e}")
            else:
                product_urls.append(sm)

    logger.info(f"Extracted total {len(product_urls)} product URLs from sitemap")
    return product_urls

def fetch_from_direct(urls_str: str, urls_file: str = "") -> List[str]:
    urls = []
    if urls_file and os.path.exists(urls_file):
        logger.info(f"Reading direct URLs from file: {urls_file}")
        ext = os.path.splitext(urls_file)[1].lower()
        if ext == ".json":
            with open(urls_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            raw = data.get("urls", []) if isinstance(data, dict) else data
            return [str(u).strip() for u in raw if str(u).strip().startswith("http")]

        if ext == ".csv":
            priority_cols = [
                "existing_competitor_url", "competitor_url", "ref product url",
                "product url", "product_url", "url", "link", "product_link",
                "target_url", "item_url", "item url"
            ]
            with open(urls_file, "r", encoding="utf-8-sig", errors="ignore") as f:
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

        with open(urls_file, "r", encoding="utf-8") as f:
            for line in f:
                u = line.strip()
                if u.startswith("http"):
                    urls.append(u)

    elif urls_str:
        for raw in urls_str.replace("\n", ",").split(","):
            u = raw.strip()
            if u.startswith("http"):
                urls.append(u)
    return urls

def main():
    parser = argparse.ArgumentParser(description="Fetch Emma Mason product URLs from FTP, Sitemap, or Direct file inputs")
    parser.add_argument("--source-type", default="direct", type=str.lower,
                        choices=["ftp", "sitemap", "direct", "urls", "csv"],
                        help="Input source type (ftp, sitemap, direct, csv)")

    # FTP args
    parser.add_argument("--ftp-host", default=os.getenv("FTP_HOST", ""), help="FTP Hostname")
    parser.add_argument("--ftp-port", type=int, default=21, help="FTP Port")
    parser.add_argument("--ftp-user", default=os.getenv("FTP_USER", ""), help="FTP Username")
    parser.add_argument("--ftp-pass", default=os.getenv("FTP_PASS", ""), help="FTP Password")
    parser.add_argument("--ftp-path", default=os.getenv("FTP_PATH", "/scrap/"), help="FTP directory path")
    parser.add_argument("--ftp-filename", default="", help="Specific CSV filename on FTP server")

    # Sitemap args
    parser.add_argument("--sitemap-url", default="https://www.emmamason.com/sitemap.xml", help="Sitemap XML URL")

    # Direct args
    parser.add_argument("--urls", default="", help="Comma or newline separated URLs")
    parser.add_argument("--urls-file", default="", help="Path to file containing URLs (CSV/JSON/TXT)")

    # Output file
    parser.add_argument("--output-file", default="remaining_input/remaining_merged.csv", help="Target output CSV file path")

    args = parser.parse_args()

    source = args.source_type.lower()
    logger.info(f"=== Starting Emma Mason URL collection mode: {source.upper()} ===")

    urls = []
    if source == "ftp":
        urls = fetch_from_ftp(
            host=args.ftp_host, port=args.ftp_port, user=args.ftp_user,
            pass_=args.ftp_pass, remote_dir=args.ftp_path, target_filename=args.ftp_filename
        )
    elif source == "sitemap":
        urls = fetch_from_sitemap(sitemap_url=args.sitemap_url)
    elif source in ["direct", "urls", "csv"]:
        urls = fetch_from_direct(urls_str=args.urls, urls_file=args.urls_file)

    if not urls:
        logger.error(f"No URLs collected using source_type '{source}'!")
        sys.exit(1)

    count = save_urls_to_csv(urls, args.output_file)
    logger.info(f"Finished processing. Total {count} URLs written to {args.output_file}")

if __name__ == "__main__":
    main()
