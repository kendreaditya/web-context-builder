"""Storage management for scraped content."""

import asyncio
import hashlib
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import aiofiles


def url_to_filename(url: str) -> str:
    """Convert a URL to a safe filename.

    Args:
        url: The URL to convert

    Returns:
        A safe filename with .md extension
    """
    parsed = urlparse(url)
    path = parsed.path.strip("/") or "index"

    # Replace path separators with underscores
    filename = path.replace("/", "_")

    # Remove or replace unsafe characters
    filename = re.sub(r"[^\w\-_.]", "_", filename)

    # Add hash suffix for uniqueness (handles query params, etc.)
    url_hash = hashlib.md5(url.encode()).hexdigest()[:8]

    # Truncate if too long
    if len(filename) > 200:
        filename = filename[:200]

    return f"{filename}_{url_hash}.md"


class StorageManager:
    """Manages storage of scraped content."""

    def __init__(self, output_dir: Path, merged_filename: str = "merged_content.md"):
        self.output_dir = output_dir
        self.pages_dir = output_dir / "pages"
        self.merged_path = output_dir / merged_filename
        self._lock = asyncio.Lock()
        self._saved_files: list[tuple[str, Path]] = []  # (url, path) pairs

    async def initialize(self) -> None:
        """Create output directories."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.pages_dir.mkdir(parents=True, exist_ok=True)

    async def save_page(self, url: str, markdown: str) -> Path:
        """Save a single page's markdown content.

        Args:
            url: Source URL
            markdown: Markdown content

        Returns:
            Path to the saved file
        """
        filename = url_to_filename(url)
        filepath = self.pages_dir / filename

        # Add source URL header
        content = f"<!-- Source: {url} -->\n\n{markdown}"

        async with aiofiles.open(filepath, "w", encoding="utf-8") as f:
            await f.write(content)

        async with self._lock:
            self._saved_files.append((url, filepath))

        return filepath

    async def merge_all(self, separator: str = "\n\n---\n\n") -> Path:
        """Merge all saved pages into a single file.

        Args:
            separator: String to place between pages

        Returns:
            Path to the merged file
        """
        async with self._lock:
            files = list(self._saved_files)

        # Sort by URL for consistent ordering
        files.sort(key=lambda x: x[0])

        merged_content = []
        merged_content.append("# Merged Documentation\n")
        merged_content.append(f"**Total Pages:** {len(files)}\n")
        merged_content.append("\n## Table of Contents\n")

        # Build table of contents
        for i, (url, _) in enumerate(files, 1):
            safe_anchor = re.sub(r"[^\w\-]", "-", url)
            merged_content.append(f"{i}. [{url}](#{safe_anchor})\n")

        merged_content.append(separator)

        # Add each page
        for url, filepath in files:
            async with aiofiles.open(filepath, "r", encoding="utf-8") as f:
                content = await f.read()

            # Add anchor for TOC linking
            safe_anchor = re.sub(r"[^\w\-]", "-", url)
            merged_content.append(f'<a id="{safe_anchor}"></a>\n\n')
            merged_content.append(f"## Source: {url}\n\n")
            merged_content.append(content)
            merged_content.append(separator)

        async with aiofiles.open(self.merged_path, "w", encoding="utf-8") as f:
            await f.write("".join(merged_content))

        return self.merged_path

    @property
    def saved_count(self) -> int:
        """Return the number of saved files."""
        return len(self._saved_files)

    def get_saved_files(self) -> list[tuple[str, Path]]:
        """Return list of saved files."""
        return list(self._saved_files)
