"""Browser-based fetcher using Playwright for JavaScript-rendered content."""

import asyncio
from typing import Optional

# Playwright is an optional dependency
try:
    from playwright.async_api import async_playwright, Browser, Page, Playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


class BrowserFetcher:
    """Fetches pages using a headless browser for JS-rendered content."""

    def __init__(
        self,
        headless: bool = True,
        timeout: int = 30000,
        wait_for_idle: bool = True,
    ):
        if not PLAYWRIGHT_AVAILABLE:
            raise ImportError(
                "Playwright is not installed. Install it with:\n"
                "  pip install 'web-context-builder[browser]'\n"
                "  playwright install chromium"
            )

        self.headless = headless
        self.timeout = timeout
        self.wait_for_idle = wait_for_idle
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None

    async def start(self) -> None:
        """Start the browser instance."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
        )

    async def stop(self) -> None:
        """Stop the browser instance."""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def fetch(self, url: str) -> Optional[str]:
        """Fetch a page and return the rendered HTML.

        Args:
            url: URL to fetch

        Returns:
            Rendered HTML content or None if failed
        """
        if not self._browser:
            raise RuntimeError("Browser not started. Call start() first.")

        page: Optional[Page] = None
        try:
            page = await self._browser.new_page()

            # Navigate to the page
            response = await page.goto(
                url,
                timeout=self.timeout,
                wait_until="domcontentloaded",
            )

            if not response:
                return None

            # Check if it's HTML content
            content_type = response.headers.get("content-type", "")
            if "text/html" not in content_type.lower():
                return None

            # Wait for network to be idle (JS finished loading)
            if self.wait_for_idle:
                try:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    # Timeout waiting for idle is okay, page might have polling
                    pass

            # Get the fully rendered HTML
            html = await page.content()
            return html

        except Exception:
            return None

        finally:
            if page:
                await page.close()

    async def __aenter__(self) -> "BrowserFetcher":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.stop()


def check_playwright_available() -> bool:
    """Check if Playwright is available."""
    return PLAYWRIGHT_AVAILABLE
