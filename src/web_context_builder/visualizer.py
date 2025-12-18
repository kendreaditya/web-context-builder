"""Rich CLI visualization for the web crawler."""

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from urllib.parse import urlparse

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.text import Text
from rich.tree import Tree


class PageStatus(Enum):
    """Status of a page being crawled."""

    PENDING = "pending"
    CRAWLING = "crawling"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PageInfo:
    """Information about a crawled page."""

    url: str
    depth: int
    status: PageStatus = PageStatus.PENDING
    title: Optional[str] = None
    links_found: int = 0
    error: Optional[str] = None
    parent_url: Optional[str] = None


@dataclass
class CrawlStats:
    """Statistics for the crawl operation."""

    pages_discovered: int = 0
    pages_crawled: int = 0
    pages_failed: int = 0
    pages_skipped: int = 0
    total_links_found: int = 0
    current_depth: int = 0
    max_depth_reached: int = 0

    @property
    def pages_remaining(self) -> int:
        return self.pages_discovered - self.pages_crawled - self.pages_failed - self.pages_skipped


class CrawlerVisualizer:
    """Rich CLI visualization for web crawling progress."""

    def __init__(self, root_url: str, max_depth: Optional[int] = None):
        self.console = Console()
        self.root_url = root_url
        self.max_depth = max_depth
        self.stats = CrawlStats()
        self.pages: dict[str, PageInfo] = {}
        self._lock = asyncio.Lock()
        self._live: Optional[Live] = None

        # Progress tracking
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("({task.completed}/{task.total})"),
            TimeElapsedColumn(),
        )
        self._main_task: Optional[TaskID] = None

        # URL tree for visualization
        self._url_tree: dict[str, list[str]] = {}  # parent -> children

    async def start(self) -> None:
        """Start the live display."""
        self._main_task = self._progress.add_task(
            "[cyan]Crawling pages...", total=None
        )
        self._live = Live(
            self._generate_display(),
            console=self.console,
            refresh_per_second=4,
            transient=False,
        )
        self._live.start()

    async def stop(self) -> None:
        """Stop the live display."""
        if self._live:
            self._live.stop()

    async def add_page(self, url: str, depth: int, parent_url: Optional[str] = None) -> None:
        """Register a new page to be crawled."""
        async with self._lock:
            if url not in self.pages:
                self.pages[url] = PageInfo(
                    url=url, depth=depth, parent_url=parent_url
                )
                self.stats.pages_discovered += 1
                self.stats.max_depth_reached = max(self.stats.max_depth_reached, depth)

                # Track tree structure
                if parent_url:
                    if parent_url not in self._url_tree:
                        self._url_tree[parent_url] = []
                    self._url_tree[parent_url].append(url)
                else:
                    self._url_tree[url] = []

                self._update_progress()
                self._refresh_display()

    async def update_page(
        self,
        url: str,
        status: PageStatus,
        title: Optional[str] = None,
        links_found: int = 0,
        error: Optional[str] = None,
    ) -> None:
        """Update the status of a page."""
        async with self._lock:
            if url in self.pages:
                page = self.pages[url]
                page.status = status
                page.title = title
                page.links_found = links_found
                page.error = error

                if status == PageStatus.SUCCESS:
                    self.stats.pages_crawled += 1
                    self.stats.total_links_found += links_found
                elif status == PageStatus.FAILED:
                    self.stats.pages_failed += 1
                elif status == PageStatus.SKIPPED:
                    self.stats.pages_skipped += 1

                self._update_progress()
                self._refresh_display()

    def _update_progress(self) -> None:
        """Update the progress bar."""
        if self._main_task is not None:
            completed = (
                self.stats.pages_crawled
                + self.stats.pages_failed
                + self.stats.pages_skipped
            )
            self._progress.update(
                self._main_task,
                completed=completed,
                total=self.stats.pages_discovered,
            )

    def _refresh_display(self) -> None:
        """Refresh the live display."""
        if self._live:
            self._live.update(self._generate_display())

    def _generate_display(self) -> Panel:
        """Generate the display panel."""
        # Stats table
        stats_table = Table(show_header=False, box=None, padding=(0, 2))
        stats_table.add_column("Metric", style="cyan")
        stats_table.add_column("Value", style="green")

        stats_table.add_row("Discovered", str(self.stats.pages_discovered))
        stats_table.add_row("Crawled", str(self.stats.pages_crawled))
        stats_table.add_row("Failed", str(self.stats.pages_failed))
        stats_table.add_row("Skipped", str(self.stats.pages_skipped))
        stats_table.add_row("Remaining", str(self.stats.pages_remaining))
        stats_table.add_row("Max Depth", str(self.stats.max_depth_reached))
        stats_table.add_row("Links Found", str(self.stats.total_links_found))

        # Build URL tree (limited depth for display)
        tree = self._build_url_tree()

        # Recent activity
        recent = self._get_recent_activity()

        # Combine all elements
        content = Group(
            self._progress,
            Text(),
            stats_table,
            Text(),
            Panel(tree, title="[bold]Crawl Tree[/bold]", border_style="blue"),
            Text(),
            Panel(recent, title="[bold]Recent Activity[/bold]", border_style="green"),
        )

        depth_str = f"/{self.max_depth}" if self.max_depth else ""
        return Panel(
            content,
            title=f"[bold cyan]Web Context Builder[/bold cyan] - Crawling {self._truncate_url(self.root_url)}",
            subtitle=f"Depth: {self.stats.max_depth_reached}{depth_str}",
            border_style="cyan",
        )

    def _build_url_tree(self, max_items: int = 15) -> Tree:
        """Build a Rich tree showing URL hierarchy."""
        tree = Tree(f"[bold]{self._truncate_url(self.root_url)}[/bold]")

        def add_children(parent_tree: Tree, parent_url: str, depth: int = 0, count: int = 0) -> int:
            if depth > 3 or count >= max_items:  # Limit depth and items
                return count

            children = self._url_tree.get(parent_url, [])
            for child_url in children[:5]:  # Max 5 children per node
                if count >= max_items:
                    break

                page = self.pages.get(child_url)
                if page:
                    status_icon = self._get_status_icon(page.status)
                    label = f"{status_icon} {self._truncate_url(child_url, 50)}"

                    if page.title and page.status == PageStatus.SUCCESS:
                        label = f"{status_icon} {page.title[:40]}"

                    child_tree = parent_tree.add(label)
                    count = add_children(child_tree, child_url, depth + 1, count + 1)

            if len(children) > 5:
                parent_tree.add(f"[dim]... and {len(children) - 5} more[/dim]")

            return count

        add_children(tree, self.root_url)
        return tree

    def _get_recent_activity(self, limit: int = 5) -> Table:
        """Get recent crawl activity."""
        table = Table(show_header=True, box=None, padding=(0, 1))
        table.add_column("Status", width=8)
        table.add_column("URL", overflow="ellipsis")
        table.add_column("Links", justify="right", width=6)

        # Get pages sorted by some recent activity indicator
        recent_pages = sorted(
            self.pages.values(),
            key=lambda p: (p.status != PageStatus.CRAWLING, p.depth),
        )[:limit]

        for page in recent_pages:
            status_text = self._get_status_text(page.status)
            links = str(page.links_found) if page.links_found else "-"
            table.add_row(status_text, self._truncate_url(page.url, 60), links)

        return table

    def _get_status_icon(self, status: PageStatus) -> str:
        """Get icon for page status."""
        icons = {
            PageStatus.PENDING: "[yellow]○[/yellow]",
            PageStatus.CRAWLING: "[cyan]◉[/cyan]",
            PageStatus.SUCCESS: "[green]✓[/green]",
            PageStatus.FAILED: "[red]✗[/red]",
            PageStatus.SKIPPED: "[dim]○[/dim]",
        }
        return icons.get(status, "○")

    def _get_status_text(self, status: PageStatus) -> str:
        """Get colored status text."""
        texts = {
            PageStatus.PENDING: "[yellow]Pending[/yellow]",
            PageStatus.CRAWLING: "[cyan]Crawling[/cyan]",
            PageStatus.SUCCESS: "[green]Done[/green]",
            PageStatus.FAILED: "[red]Failed[/red]",
            PageStatus.SKIPPED: "[dim]Skipped[/dim]",
        }
        return texts.get(status, "Unknown")

    def _truncate_url(self, url: str, max_len: int = 40) -> str:
        """Truncate URL for display."""
        parsed = urlparse(url)
        path = parsed.path or "/"

        if len(path) > max_len:
            return f"...{path[-(max_len-3):]}"
        return path

    async def print_summary(self) -> None:
        """Print final summary."""
        self.console.print()
        self.console.print("[bold green]✓ Crawl Complete![/bold green]")
        self.console.print()

        table = Table(title="Crawl Summary", show_header=True)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green", justify="right")

        table.add_row("Pages Discovered", str(self.stats.pages_discovered))
        table.add_row("Pages Crawled", str(self.stats.pages_crawled))
        table.add_row("Pages Failed", str(self.stats.pages_failed))
        table.add_row("Pages Skipped", str(self.stats.pages_skipped))
        table.add_row("Total Links Found", str(self.stats.total_links_found))
        table.add_row("Max Depth Reached", str(self.stats.max_depth_reached))

        self.console.print(table)
        self.console.print()
