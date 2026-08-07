import os
import logging

logger = logging.getLogger(__name__)

class ProxyManager:
    def __init__(self):
        self.proxy = os.getenv('PROXY_URL', '')

    def get_proxy(self):
        return self.proxy if self.proxy else None
