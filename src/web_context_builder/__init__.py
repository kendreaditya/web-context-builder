"""Web Context Builder - Production-ready async web scraper for LLM context."""

__version__ = "1.0.0"

from .config import CrawlerConfig
from .crawler import WebCrawler

__all__ = ["WebCrawler", "CrawlerConfig", "__version__"]
