"""Command-line interface for Web Context Builder."""

import asyncio
import sys
from pathlib import Path

import click
from rich.console import Console

from . import __version__
from .config import CrawlerConfig
from .crawler import WebCrawler

console = Console()


def print_banner() -> None:
    """Print the application banner."""
    banner = """
[bold cyan]╔══════════════════════════════════════════════════════════════╗
║                    Web Context Builder                        ║
║              Production-Ready Web Scraper for LLMs            ║
╚══════════════════════════════════════════════════════════════╝[/bold cyan]
"""
    console.print(banner)


@click.command()
@click.argument("url")
@click.option(
    "-o",
    "--output",
    default="./output",
    type=click.Path(),
    help="Output directory for scraped content",
)
@click.option(
    "-c",
    "--concurrent",
    default=5,
    type=int,
    help="Maximum concurrent requests (default: 5)",
)
@click.option(
    "-d",
    "--depth",
    default=None,
    type=int,
    help="Maximum crawl depth (default: unlimited)",
)
@click.option(
    "--delay",
    default=0.1,
    type=float,
    help="Delay between requests in seconds (default: 0.1)",
)
@click.option(
    "--timeout",
    default=30,
    type=int,
    help="Request timeout in seconds (default: 30)",
)
@click.option(
    "--cross-subdomain/--same-subdomain",
    default=False,
    help="Allow crawling across subdomains (default: same subdomain only)",
)
@click.option(
    "--no-progress",
    is_flag=True,
    default=False,
    help="Disable live progress visualization",
)
@click.option(
    "--no-merge",
    is_flag=True,
    default=False,
    help="Skip merging into single file",
)
@click.option(
    "-m",
    "--merged-name",
    default=None,
    help="Name of the merged output file (default: <domain>.md)",
)
@click.version_option(version=__version__)
def main(
    url: str,
    output: str,
    concurrent: int,
    depth: int | None,
    delay: float,
    timeout: int,
    cross_subdomain: bool,
    no_progress: bool,
    no_merge: bool,
    merged_name: str | None,
) -> None:
    """Web Context Builder - Scrape websites to LLM-optimized markdown.

    URL is the starting page to crawl. Only pages on the same domain/subdomain
    will be scraped.

    Examples:

        wcb https://docs.example.com

        wcb https://docs.example.com -o ./my-docs -d 3

        wcb https://docs.example.com --cross-subdomain

    """
    print_banner()

    # Validate URL
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    # Create config
    config = CrawlerConfig(
        root_url=url,
        output_dir=Path(output),
        max_concurrent=concurrent,
        max_depth=depth,
        delay_between_requests=delay,
        request_timeout=timeout,
        stay_on_subdomain=not cross_subdomain,
        merged_filename=merged_name,
    )

    console.print(f"[bold]Starting crawl:[/bold] {url}")
    console.print(f"[dim]Output directory: {config.output_dir.absolute()}[/dim]")
    console.print(f"[dim]Max concurrent: {concurrent} | Max depth: {depth or 'unlimited'}[/dim]")
    console.print(f"[dim]Subdomain restriction: {'Same subdomain only' if not cross_subdomain else 'Cross-subdomain allowed'}[/dim]")
    console.print()

    # Run the crawler
    try:
        crawler = WebCrawler(config)
        pages_crawled = asyncio.run(crawler.crawl(show_progress=not no_progress))

        if pages_crawled == 0:
            console.print("[yellow]No pages were successfully crawled.[/yellow]")
            sys.exit(1)

        console.print(f"[green]Successfully crawled {pages_crawled} pages[/green]")

        # Merge results
        if not no_merge:
            console.print("[dim]Merging pages into single file...[/dim]")
            merged_path = asyncio.run(crawler.merge_results())
            console.print(f"[green]Merged file created: {merged_path}[/green]")

        # Print output location
        console.print()
        console.print("[bold]Output files:[/bold]")
        console.print(f"  Individual pages: {config.output_dir / 'pages'}")
        if not no_merge:
            console.print(f"  Merged file: {config.output_dir / config.merged_filename}")

    except KeyboardInterrupt:
        console.print("\n[yellow]Crawl interrupted by user[/yellow]")
        sys.exit(130)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
