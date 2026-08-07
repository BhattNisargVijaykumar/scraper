import os
import sys
import csv
import time
import json
import sqlite3
import threading
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup
from curl_cffi import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger("emma_mason_fetcher")

class ProductFetcher:
    name = "emma_mason_product"

    def __init__(self, *args, **kwargs):
        self.website_url = kwargs.get("website_url", "https://www.emmamason.com").rstrip("/")
        self.input_urls = kwargs.get("input_urls", [])
        self.is_direct_file = kwargs.get("is_direct_file", False)
        self.output_dir = kwargs.get("output_dir", "output")
        self.max_workers = int(kwargs.get("max_workers", os.getenv("MAX_WORKERS", "4")))
        self.request_delay = float(kwargs.get("request_delay", os.getenv("REQUEST_DELAY", "1.0")))
        self.job_id = kwargs.get("job_id", datetime.now().strftime("%Y%m%d_%H%M%S"))
        self.verbose = kwargs.get("verbose", False)

        self.scraped_date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        self.csv_header = [
            "Ref Product URL",
            "Ref Product ID",
            "Ref Category",
            "Ref Category URL",
            "Ref Brand Name",
            "Ref Product Name",
            "Ref SKU",
            "Ref MPN",
            "Ref GTIN",
            "Ref Price",
            "Ref Main Image",
            "Ref Quantity",
            "Ref Group Attr 1",
            "Ref Group Attr 2",
            "Ref Status",
            "Date Scrapped",
        ]

        self.csv_lock = threading.Lock()
        self.seen = set()
        self.processed_successfully_urls = set()
        self.queued_or_processing_urls = set()
        self.success_db_conn = None
        self.success_db_write_counter = 0

        self.stats = {
            "urls_processed": 0,
            "products_fetched": 0,
            "errors": 0,
            "plp_urls_skipped": 0,
        }

        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        })

        self._init_success_store()

    def _get_success_store_path(self):
        os.makedirs(self.output_dir, exist_ok=True)
        return os.path.join(self.output_dir, "success_urls_emmamason.sqlite3")

    def _init_success_store(self):
        try:
            db_path = self._get_success_store_path()
            self.success_db_conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
            cursor = self.success_db_conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS successful_urls (
                    domain TEXT NOT NULL,
                    normalized_url TEXT NOT NULL,
                    first_success_at TEXT NOT NULL,
                    job_id TEXT,
                    PRIMARY KEY (domain, normalized_url)
                )
            """)
            self.success_db_conn.commit()
            cursor.execute("SELECT normalized_url FROM successful_urls WHERE domain = 'emmamason'")
            rows = cursor.fetchall()
            if rows:
                self.processed_successfully_urls.update(row[0] for row in rows if row and row[0])
            logger.info(f"🗂️ Loaded {len(rows)} previously successful Emma Mason URLs from {db_path}")
        except Exception as e:
            logger.error(f"Failed to init sqlite success store: {e}")

    def _persist_success_url(self, normalized_url: str):
        if not self.success_db_conn or not normalized_url:
            return
        try:
            with self.csv_lock:
                self.success_db_conn.execute(
                    """
                    INSERT OR IGNORE INTO successful_urls (domain, normalized_url, first_success_at, job_id)
                    VALUES ('emmamason', ?, ?, ?)
                    """,
                    (normalized_url, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), self.job_id)
                )
                self.success_db_write_counter += 1
                if self.success_db_write_counter >= 20:
                    self.success_db_conn.commit()
                    self.success_db_write_counter = 0
        except Exception as e:
            logger.error(f"Failed to persist success url {normalized_url}: {e}")

    def clean_url(self, url: str) -> str:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"

    def normalize_image(self, url: str) -> str:
        if not url:
            return ""
        if url.startswith("//"):
            return "https:" + url
        if url.startswith("/"):
            return f"{self.website_url}{url}"
        if not url.startswith("http"):
            return f"https://{url}"
        return url

    def http_get(self, url: str) -> Optional[str]:
        for attempt in range(3):
            try:
                r = self.session.get(url, timeout=15, verify=True, impersonate="chrome124", allow_redirects=True)
                if r.status_code == 200:
                    return r.text
                logger.warning(f"Status {r.status_code} for {url}")
                if r.status_code in [429, 503]:
                    time.sleep(3)
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} error for {url}: {e}")
                time.sleep(1)
        return None

    def extract_emmamason_data(self, soup: BeautifulSoup, url: str) -> List[Dict]:
        results: List[Dict] = []
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                raw = script.string
                if not raw:
                    continue
                parsed = json.loads(raw)

                items = parsed if isinstance(parsed, list) else [parsed]
                for data in items:
                    if not isinstance(data, dict):
                        continue

                    data_type = data.get("@type", "")
                    if isinstance(data_type, list):
                        data_type = " ".join(str(t) for t in data_type)

                    name = data.get("name", "")
                    if not name and "Product" not in str(data_type):
                        continue

                    selected_offer = data.get("offers", {})
                    if isinstance(selected_offer, list) and selected_offer:
                        selected_offer = selected_offer[0]
                    if not isinstance(selected_offer, dict):
                        selected_offer = {}

                    images = data.get("image", "")
                    main_image = ""
                    if isinstance(images, list) and images:
                        main_image = images[0]
                    elif isinstance(images, str):
                        main_image = images
                    elif isinstance(images, dict):
                        main_image = images.get("url", "")

                    price = (
                        selected_offer.get("price", "")
                        or selected_offer.get("lowPrice", "")
                        or (data.get("offers", {}).get("price", "") if isinstance(data.get("offers"), dict) else "")
                    )

                    brand_raw = data.get("brand", {})
                    brand = brand_raw.get("name", "") if isinstance(brand_raw, dict) else str(brand_raw)

                    if name:
                        results.append({
                            "competitor_product_id": "",
                            "comp_received_name": name,
                            "comp_received_sku": data.get("sku", ""),
                            "brand": brand,
                            "mpn": data.get("mpn", ""),
                            "category": "",
                            "category_url": "",
                            "gtin": data.get("gtin13", ""),
                            "quantity": 1,
                            "status": "In Stock",
                            "competitor_price": price,
                            "group_attr_1": data.get("description", ""),
                            "group_attr_2": data.get("material", ""),
                            "main_image": self.normalize_image(main_image),
                            "competitor_url": url,
                            "scraped_date": self.scraped_date,
                        })
            except Exception:
                continue

        if results:
            return results

        # Fallback: HTML / Meta tag extraction if JSON-LD block is missing or empty
        h1 = soup.find("h1")
        name = h1.text.strip() if h1 else ""
        if not name:
            og_title = soup.find("meta", property="og:title")
            if og_title and og_title.get("content"):
                name = og_title["content"].strip()

        if name:
            price = ""
            og_price = soup.find("meta", property="product:price:amount") or soup.find("meta", property="og:price:amount")
            if og_price and og_price.get("content"):
                price = og_price["content"].strip()

            main_image = ""
            og_image = soup.find("meta", property="og:image")
            if og_image and og_image.get("content"):
                main_image = og_image["content"].strip()

            results.append({
                "competitor_product_id": "",
                "comp_received_name": name,
                "comp_received_sku": "",
                "brand": "Emma Mason",
                "mpn": "",
                "category": "",
                "category_url": "",
                "gtin": "",
                "quantity": 1,
                "status": "In Stock",
                "competitor_price": price,
                "group_attr_1": "",
                "group_attr_2": "",
                "main_image": self.normalize_image(main_image),
                "competitor_url": url,
                "scraped_date": self.scraped_date,
            })

        return results

    def write_row(self, writer: csv.writer, product: Dict):
        row = [
            product["competitor_url"],
            product["competitor_product_id"],
            product["category"],
            product["category_url"],
            product["brand"],
            product["comp_received_name"],
            product["comp_received_sku"],
            product["mpn"],
            product["gtin"],
            product["competitor_price"],
            product["main_image"],
            product["quantity"],
            product["group_attr_1"],
            product["group_attr_2"],
            product["status"],
            product["scraped_date"],
        ]
        with self.csv_lock:
            writer.writerow(row)

    def process_product(self, product_url: str, writer: csv.writer):
        base_url = self.clean_url(product_url)
        if base_url in self.seen:
            return
        self.seen.add(base_url)

        html = self.http_get(product_url)
        if not html:
            self.stats["errors"] += 1
            return

        soup = BeautifulSoup(html, "html.parser")
        products = self.extract_emmamason_data(soup, product_url)

        if not products:
            self.stats["errors"] += 1
            return

        for product in products:
            if not product.get("comp_received_name"):
                continue
            try:
                self.write_row(writer, product)
                self.stats["products_fetched"] += 1
                self._persist_success_url(base_url)
            except Exception:
                self.stats["errors"] += 1

        time.sleep(self.request_delay)
        self.stats["urls_processed"] += 1

    def run(self, output_file: str):
        os.makedirs(self.output_dir, exist_ok=True)
        logger.info(f"🚀 Starting Emma Mason scraper for {len(self.input_urls)} product URLs...")
        logger.info(f"📁 Output file: {output_file}")

        with open(output_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(self.csv_header)

            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = [
                    executor.submit(self.process_product, url, writer)
                    for url in self.input_urls
                ]
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        logger.error(f"Error in thread: {e}")
                        self.stats["errors"] += 1

        if self.success_db_conn:
            self.success_db_conn.commit()

        logger.info("=" * 60)
        logger.info("SCRAPING COMPLETE")
        logger.info(f"  URLs processed:  {self.stats['urls_processed']}")
        logger.info(f"  Products saved:  {self.stats['products_fetched']}")
        logger.info(f"  Errors:          {self.stats['errors']}")
        logger.info(f"  Output saved to: {output_file}")
        logger.info("=" * 60)
        return output_file
