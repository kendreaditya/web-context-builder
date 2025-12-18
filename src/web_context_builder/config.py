"""Configuration management for the web crawler."""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse


def url_to_clean_filename(url: str) -> str:
    """Convert a URL to a clean filename.

    Examples:
        https://tinker-docs.thinkingmachines.ai/ -> tinker-docs.thinkingmachines.ai.md
        https://docs.example.com/api -> docs.example.com.md
    """
    parsed = urlparse(url)
    hostname = parsed.netloc or parsed.path.split("/")[0]

    # Remove port if present
    hostname = hostname.split(":")[0]

    # Clean any remaining invalid characters
    hostname = re.sub(r"[^\w\-.]", "-", hostname)

    return f"{hostname}.md"


@dataclass
class CrawlerConfig:
    """Configuration for the web crawler."""

    # Target configuration
    root_url: str

    # Crawling behavior
    max_concurrent: int = 5
    max_depth: Optional[int] = None  # None = unlimited
    delay_between_requests: float = 0.1  # seconds
    request_timeout: int = 30  # seconds
    max_retries: int = 3

    # URL filtering
    stay_on_subdomain: bool = True  # Only crawl same subdomain

    # Output configuration
    output_dir: Path = field(default_factory=lambda: Path("./output"))
    merged_filename: Optional[str] = None  # Auto-generated from URL if None

    # Content filtering
    exclude_patterns: list[str] = field(default_factory=lambda: [
        r".*\.(pdf|zip|tar|gz|exe|dmg|pkg|deb|rpm)$",
        r".*\.(png|jpg|jpeg|gif|svg|ico|webp)$",
        r".*\.(css|js|woff|woff2|ttf|eot)$",
        r".*\.(mp3|mp4|wav|avi|mov|webm)$",
    ])

    # User agent
    user_agent: str = "WebContextBuilder/1.0 (LLM Context Scraper)"

    def __post_init__(self) -> None:
        """Validate and normalize configuration."""
        if isinstance(self.output_dir, str):
            self.output_dir = Path(self.output_dir)

        # Ensure root_url has protocol
        if not self.root_url.startswith(("http://", "https://")):
            self.root_url = f"https://{self.root_url}"

        # Remove trailing slash for consistency
        self.root_url = self.root_url.rstrip("/")

        # Auto-generate merged filename from URL if not specified
        if self.merged_filename is None:
            self.merged_filename = url_to_clean_filename(self.root_url)
