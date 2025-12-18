"""HTML to LLM-optimized Markdown converter."""

import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Comment, NavigableString, Tag
from markdownify import MarkdownConverter


class LLMOptimizedConverter(MarkdownConverter):
    """Custom markdown converter optimized for LLM consumption."""

    def __init__(self, base_url: str, **kwargs):
        self.base_url = base_url
        super().__init__(**kwargs)

    def convert_a(self, el: Tag, text: str, convert_as_inline: bool = False, **kwargs) -> str:
        """Convert links, resolving relative URLs."""
        href = el.get("href", "")
        if href and not href.startswith(("http://", "https://", "mailto:", "#")):
            href = urljoin(self.base_url, href)

        title = el.get("title", "")
        text = text.strip()

        if not text or not href:
            return text or ""

        if title:
            return f'[{text}]({href} "{title}")'
        return f"[{text}]({href})"

    def convert_img(self, el: Tag, text: str, convert_as_inline: bool = False, **kwargs) -> str:
        """Convert images to markdown, resolving relative URLs."""
        src = el.get("src", "")
        if src and not src.startswith(("http://", "https://", "data:")):
            src = urljoin(self.base_url, src)

        alt = el.get("alt", "")
        title = el.get("title", "")

        if not src:
            return ""

        if title:
            return f'![{alt}]({src} "{title}")'
        return f"![{alt}]({src})"


# Elements to completely remove (navigation, ads, etc.)
REMOVE_SELECTORS = [
    "nav",
    "header",
    "footer",
    "aside",
    ".sidebar",
    ".navigation",
    ".nav",
    ".menu",
    ".header",
    ".footer",
    ".breadcrumb",
    ".breadcrumbs",
    ".toc",
    ".table-of-contents",
    ".advertisement",
    ".ads",
    ".ad",
    ".social-share",
    ".social-links",
    ".share-buttons",
    ".cookie-banner",
    ".cookie-notice",
    ".popup",
    ".modal",
    "#sidebar",
    "#nav",
    "#navigation",
    "#header",
    "#footer",
    "[role='navigation']",
    "[role='banner']",
    "[role='contentinfo']",
    "[aria-label='breadcrumb']",
    "script",
    "style",
    "noscript",
    "iframe",
    "form",
    "button",
    "input",
    "select",
    "textarea",
]


def clean_html(soup: BeautifulSoup) -> BeautifulSoup:
    """Remove non-content elements from HTML."""
    # Remove comments
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    # Remove unwanted elements
    for selector in REMOVE_SELECTORS:
        for element in soup.select(selector):
            element.decompose()

    # Remove empty elements
    for element in soup.find_all():
        if isinstance(element, Tag):
            # Keep elements that have content or are self-closing
            if element.name not in ["br", "hr", "img"]:
                if not element.get_text(strip=True) and not element.find("img"):
                    element.decompose()

    return soup


def extract_title(soup: BeautifulSoup) -> str:
    """Extract the page title."""
    # Try h1 first
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)

    # Try title tag
    title = soup.find("title")
    if title:
        return title.get_text(strip=True)

    return "Untitled"


def extract_main_content(soup: BeautifulSoup) -> Optional[Tag]:
    """Extract the main content area of the page."""
    # Priority order for main content
    selectors = [
        "main",
        "article",
        "[role='main']",
        ".main-content",
        ".content",
        ".post-content",
        ".article-content",
        ".entry-content",
        "#main",
        "#content",
        "#main-content",
        ".markdown-body",  # GitHub-style
        ".documentation",
        ".docs-content",
    ]

    for selector in selectors:
        content = soup.select_one(selector)
        if content:
            return content

    # Fallback to body
    return soup.body


def html_to_markdown(html: str, url: str) -> str:
    """Convert HTML to LLM-optimized markdown.

    Args:
        html: Raw HTML content
        url: Source URL for resolving relative links

    Returns:
        Clean markdown optimized for LLM consumption
    """
    soup = BeautifulSoup(html, "lxml")

    # Extract title before cleaning
    title = extract_title(soup)

    # Clean the HTML
    soup = clean_html(soup)

    # Extract main content
    main_content = extract_main_content(soup)

    if not main_content:
        return f"# {title}\n\n*No content extracted*"

    # Convert to markdown
    converter = LLMOptimizedConverter(
        base_url=url,
        heading_style="atx",
        bullets="-",
        code_language_callback=lambda el: el.get("class", [""])[0].replace("language-", "") if el.get("class") else "",
    )

    markdown = converter.convert(str(main_content))

    # Post-process markdown
    markdown = clean_markdown(markdown)

    # Add title if not already present
    if not markdown.strip().startswith("#"):
        markdown = f"# {title}\n\n{markdown}"

    return markdown


def clean_markdown(markdown: str) -> str:
    """Clean up the generated markdown."""
    # Remove excessive newlines (more than 2)
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)

    # Remove trailing whitespace from lines
    lines = [line.rstrip() for line in markdown.split("\n")]
    markdown = "\n".join(lines)

    # Remove empty links
    markdown = re.sub(r"\[([^\]]*)\]\(\s*\)", r"\1", markdown)

    # Clean up list formatting
    markdown = re.sub(r"^\s*-\s*$", "", markdown, flags=re.MULTILINE)

    # Remove excessive spaces
    markdown = re.sub(r"  +", " ", markdown)

    # Ensure proper spacing around headers
    markdown = re.sub(r"(\n#)", r"\n\1", markdown)

    return markdown.strip()
