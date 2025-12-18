"""Core async web crawler implementation."""

import asyncio
import re
from typing import Optional, Set
from urllib.parse import urljoin, urlparse

import aiohttp
import tldextract
from bs4 import BeautifulSoup

from .config import CrawlerConfig
from .parser import html_to_markdown
from .storage import StorageManager
from .visualizer import CrawlerVisualizer, PageStatus


class WebCrawler:
    """Production-ready async web crawler."""

    def __init__(self, config: CrawlerConfig):
        self.config = config
        self.storage = StorageManager(config.output_dir, config.merged_filename)
        self.visualizer: Optional[CrawlerVisualizer] = None

        # URL tracking
        self._seen_urls: Set[str] = set()
        self._url_lock = asyncio.Lock()

        # Domain extraction for filtering
        self._root_extract = tldextract.extract(config.root_url)
        self._root_parsed = urlparse(config.root_url)

        # Compile exclude patterns
        self._exclude_patterns = [
            re.compile(pattern, re.IGNORECASE)
            for pattern in config.exclude_patterns
        ]

        # Semaphore for concurrent requests
        self._semaphore = asyncio.Semaphore(config.max_concurrent)

        # Queue for BFS crawling
        self._queue: asyncio.Queue[tuple[str, int, Optional[str]]] = asyncio.Queue()

        # Crawling state
        self._active_tasks = 0
        self._active_lock = asyncio.Lock()
        self._finished = asyncio.Event()

    def _normalize_url(self, url: str) -> str:
        """Normalize URL for deduplication."""
        parsed = urlparse(url)

        # Remove fragment
        normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

        # Remove trailing slash unless it's the root
        if normalized.endswith("/") and parsed.path != "/":
            normalized = normalized[:-1]

        # Handle query params (keep them but sorted for consistency)
        if parsed.query:
            params = sorted(parsed.query.split("&"))
            normalized = f"{normalized}?{'&'.join(params)}"

        return normalized.lower()

    def _is_same_domain(self, url: str) -> bool:
        """Check if URL is on the same domain/subdomain."""
        try:
            parsed = urlparse(url)
            extract = tldextract.extract(url)

            # Must match registered domain
            if extract.registered_domain != self._root_extract.registered_domain:
                return False

            # If stay_on_subdomain is True, also check subdomain
            if self.config.stay_on_subdomain:
                if extract.subdomain != self._root_extract.subdomain:
                    return False

            return True
        except Exception:
            return False

    def _should_crawl(self, url: str) -> bool:
        """Determine if a URL should be crawled."""
        # Must be HTTP(S)
        if not url.startswith(("http://", "https://")):
            return False

        # Must be same domain
        if not self._is_same_domain(url):
            return False

        # Check exclude patterns
        for pattern in self._exclude_patterns:
            if pattern.match(url):
                return False

        return True

    def _extract_links(self, html: str, base_url: str) -> list[str]:
        """Extract all links from HTML content."""
        soup = BeautifulSoup(html, "lxml")
        links = []

        for a in soup.find_all("a", href=True):
            href = a["href"]

            # Skip empty, javascript, and anchor links
            if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
                continue

            # Convert relative URLs to absolute
            absolute_url = urljoin(base_url, href)

            # Normalize
            normalized = self._normalize_url(absolute_url)

            if self._should_crawl(normalized):
                links.append(normalized)

        return list(set(links))  # Deduplicate

    async def _fetch_page(self, session: aiohttp.ClientSession, url: str) -> Optional[str]:
        """Fetch a single page with retries."""
        for attempt in range(self.config.max_retries):
            try:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=self.config.request_timeout),
                    allow_redirects=True,
                    headers={"User-Agent": self.config.user_agent},
                ) as response:
                    # Only process HTML content
                    content_type = response.headers.get("Content-Type", "")
                    if "text/html" not in content_type.lower():
                        return None

                    if response.status == 200:
                        return await response.text()
                    elif response.status in (404, 410):
                        return None  # Page doesn't exist
                    else:
                        # Retry on server errors
                        if response.status >= 500:
                            await asyncio.sleep(2**attempt)
                            continue
                        return None

            except asyncio.TimeoutError:
                if attempt < self.config.max_retries - 1:
                    await asyncio.sleep(2**attempt)
                continue
            except aiohttp.ClientError:
                if attempt < self.config.max_retries - 1:
                    await asyncio.sleep(2**attempt)
                continue
            except Exception:
                return None

        return None

    async def _process_page(
        self,
        session: aiohttp.ClientSession,
        url: str,
        depth: int,
        parent_url: Optional[str],
    ) -> None:
        """Process a single page: fetch, parse, save, and queue links."""
        async with self._semaphore:
            # Update visualizer status
            if self.visualizer:
                await self.visualizer.update_page(url, PageStatus.CRAWLING)

            try:
                # Fetch the page
                html = await self._fetch_page(session, url)

                if html is None:
                    if self.visualizer:
                        await self.visualizer.update_page(
                            url, PageStatus.SKIPPED, error="Not HTML or fetch failed"
                        )
                    return

                # Extract links
                links = self._extract_links(html, url)

                # Convert to markdown
                markdown = html_to_markdown(html, url)

                # Extract title from markdown
                title = None
                for line in markdown.split("\n"):
                    if line.startswith("# "):
                        title = line[2:].strip()
                        break

                # Save the page
                await self.storage.save_page(url, markdown)

                # Update visualizer
                if self.visualizer:
                    await self.visualizer.update_page(
                        url, PageStatus.SUCCESS, title=title, links_found=len(links)
                    )

                # Queue new links (if within depth limit)
                if self.config.max_depth is None or depth < self.config.max_depth:
                    for link in links:
                        await self._maybe_queue_url(link, depth + 1, url)

                # Rate limiting delay
                if self.config.delay_between_requests > 0:
                    await asyncio.sleep(self.config.delay_between_requests)

            except Exception as e:
                if self.visualizer:
                    await self.visualizer.update_page(
                        url, PageStatus.FAILED, error=str(e)
                    )

    async def _maybe_queue_url(
        self, url: str, depth: int, parent_url: Optional[str]
    ) -> bool:
        """Queue a URL if not already seen."""
        async with self._url_lock:
            if url in self._seen_urls:
                return False
            self._seen_urls.add(url)

        # Register with visualizer
        if self.visualizer:
            await self.visualizer.add_page(url, depth, parent_url)

        # Add to queue
        await self._queue.put((url, depth, parent_url))
        return True

    async def _worker(self, session: aiohttp.ClientSession) -> None:
        """Worker coroutine that processes URLs from the queue."""
        while True:
            try:
                # Wait for URL with timeout
                try:
                    url, depth, parent_url = await asyncio.wait_for(
                        self._queue.get(), timeout=2.0
                    )
                except asyncio.TimeoutError:
                    # Check if we should stop
                    async with self._active_lock:
                        if self._active_tasks == 0 and self._queue.empty():
                            return
                    continue

                async with self._active_lock:
                    self._active_tasks += 1

                try:
                    await self._process_page(session, url, depth, parent_url)
                finally:
                    self._queue.task_done()
                    async with self._active_lock:
                        self._active_tasks -= 1

            except asyncio.CancelledError:
                return

    async def crawl(self, show_progress: bool = True) -> int:
        """Start crawling from the root URL.

        Args:
            show_progress: Whether to show the live progress visualization

        Returns:
            Number of pages successfully crawled
        """
        # Initialize storage
        await self.storage.initialize()

        # Initialize visualizer
        if show_progress:
            self.visualizer = CrawlerVisualizer(
                self.config.root_url, self.config.max_depth
            )
            await self.visualizer.start()

        # Queue the root URL
        normalized_root = self._normalize_url(self.config.root_url)
        await self._maybe_queue_url(normalized_root, 0, None)

        # Create HTTP session
        connector = aiohttp.TCPConnector(limit=self.config.max_concurrent * 2)
        async with aiohttp.ClientSession(connector=connector) as session:
            # Start workers
            workers = [
                asyncio.create_task(self._worker(session))
                for _ in range(self.config.max_concurrent)
            ]

            # Wait for queue to be processed
            await self._queue.join()

            # Cancel workers
            for worker in workers:
                worker.cancel()

            await asyncio.gather(*workers, return_exceptions=True)

        # Stop visualizer
        if self.visualizer:
            await self.visualizer.stop()
            await self.visualizer.print_summary()

        return self.storage.saved_count

    async def merge_results(self) -> str:
        """Merge all scraped pages into a single file.

        Returns:
            Path to the merged file
        """
        merged_path = await self.storage.merge_all()
        return str(merged_path)


async def run_crawler(
    root_url: str,
    output_dir: str = "./output",
    max_concurrent: int = 5,
    max_depth: Optional[int] = None,
    delay: float = 0.1,
    show_progress: bool = True,
) -> tuple[int, str]:
    """Convenience function to run the crawler.

    Args:
        root_url: Starting URL to crawl
        output_dir: Directory to save output
        max_concurrent: Maximum concurrent requests
        max_depth: Maximum crawl depth (None for unlimited)
        delay: Delay between requests in seconds
        show_progress: Show live progress visualization

    Returns:
        Tuple of (pages_crawled, merged_file_path)
    """
    from pathlib import Path

    config = CrawlerConfig(
        root_url=root_url,
        output_dir=Path(output_dir),
        max_concurrent=max_concurrent,
        max_depth=max_depth,
        delay_between_requests=delay,
    )

    crawler = WebCrawler(config)
    pages_crawled = await crawler.crawl(show_progress=show_progress)
    merged_path = await crawler.merge_results()

    return pages_crawled, merged_path
