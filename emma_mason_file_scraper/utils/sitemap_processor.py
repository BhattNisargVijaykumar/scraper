import requests
import xml.etree.ElementTree as ET
import gzip
import re
from typing import List
from urllib.parse import urljoin
import logging
import time

logger = logging.getLogger(__name__)

class SitemapProcessor:
    def __init__(self):
        pass

    def get_sitemap_from_robots(self, site_url: str) -> str:
        site_url = site_url.rstrip('/')
        robots_url = urljoin(site_url + '/', 'robots.txt')
        logger.info(f"Checking robots.txt at: {robots_url}")
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        }
        try:
            r = requests.get(robots_url, headers=headers, timeout=15)
            if r.status_code == 200:
                for line in r.text.split('\n'):
                    line = line.strip()
                    if line.lower().startswith('sitemap:'):
                        sitemap_url = line.split(':', 1)[1].strip()
                        logger.info(f"Found sitemap in robots.txt: {sitemap_url}")
                        return sitemap_url
        except Exception as e:
            logger.warning(f"Could not fetch robots.txt: {e}")

        default_sitemap = f"{site_url}/sitemap.xml"
        logger.info(f"Fallback to default sitemap URL: {default_sitemap}")
        return default_sitemap

    def extract_all_sitemaps(self, main_sitemap_url: str) -> List[str]:
        logger.info(f"Extracting sitemaps from: {main_sitemap_url}")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        }
        r = requests.get(main_sitemap_url, headers=headers, timeout=15)
        if r.status_code != 200:
            raise Exception(f"Failed to fetch {main_sitemap_url}: status {r.status_code}")

        content = r.text
        # Strip inline scripts that break XML parsing for Emma Mason
        content = re.sub(r'<script[^>]*/>', '', content)
        content = re.sub(r'<script[^>]*>.*?</script>', '', content, flags=re.DOTALL)

        if "<?xml" not in content[:100]:
            content = '<?xml version="1.0" encoding="UTF-8"?>\n' + content

        root = ET.fromstring(content)
        ns = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}

        sitemaps = []
        for sitemap in root.findall('ns:sitemap/ns:loc', ns):
            if sitemap.text:
                sitemaps.append(sitemap.text.strip())

        if not sitemaps:
            for path in ['.//sitemap/loc', './/loc']:
                for el in root.findall(path):
                    if el.text and el.text.strip().startswith('http'):
                        sitemaps.append(el.text.strip())

        if not sitemaps:
            sitemaps = [main_sitemap_url]

        logger.info(f"Extracted {len(sitemaps)} child sitemaps")
        return sitemaps

    @staticmethod
    def get_sitemap_chunks(all_sitemaps: List[str], offset: int, limit: int) -> List[str]:
        if not all_sitemaps:
            return []
        if limit == 0:
            return all_sitemaps[offset:]
        return all_sitemaps[offset:offset + limit]
