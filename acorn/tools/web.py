"""Web search and page fetching, using only the standard library.

Deliberately keyless: an open-source CLI shouldn't make people register for a
search API before the agent can look something up. DuckDuckGo's HTML endpoint
needs no credentials, so search works on a fresh install with nothing configured.
"""
import gzip
import html
import io
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

SEARCH_ENDPOINT = "https://html.duckduckgo.com/html/"
LITE_ENDPOINT = "https://lite.duckduckgo.com/lite/"

MAX_PAGE_BYTES = 2_000_000
DEFAULT_TIMEOUT = 20

# Only these schemes — file:// and friends would sidestep the permission system
# that governs local file access.
ALLOWED_SCHEMES = frozenset({"http", "https"})

RESULT_LINK = re.compile(
    r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
    re.DOTALL | re.IGNORECASE,
)
RESULT_SNIPPET = re.compile(
    r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>',
    re.DOTALL | re.IGNORECASE,
)
LITE_LINK = re.compile(
    r'<a[^>]+class="result-link"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
    re.DOTALL | re.IGNORECASE,
)

SCRIPT_STYLE = re.compile(
    r"<(script|style|noscript|svg|head)\b[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE
)
TAG = re.compile(r"<[^>]+>")
BLOCK_BREAK = re.compile(
    r"</(p|div|section|article|li|tr|h[1-6]|blockquote|pre)>", re.IGNORECASE
)
BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
BLANK_LINES = re.compile(r"\n{3,}")
SPACES = re.compile(r"[ \t]{2,}")


def _explain_url_error(error: urllib.error.URLError, target: str) -> str:
    """Turns a URLError into something the user can act on."""
    reason = error.reason
    if isinstance(reason, ssl.SSLCertVerificationError):
        return (
            f"Error: TLS certificate verification failed for {target}. This usually means a "
            f"proxy or corporate network is intercepting HTTPS. Point SSL_CERT_FILE at your "
            f"organisation's CA bundle to fix it."
        )
    return f"Error: Could not reach {target} ({reason})."


def _strip_tags(fragment: str) -> str:
    """Turns an HTML fragment into readable plain text."""
    text = TAG.sub("", fragment)
    return html.unescape(text).strip()


def _unwrap_ddg_url(url: str) -> str:
    """DuckDuckGo wraps results in a redirect; pull the real target out."""
    if "duckduckgo.com/l/" not in url and not url.startswith("//duckduckgo.com/l/"):
        return url
    if url.startswith("//"):
        url = "https:" + url
    try:
        query = urllib.parse.urlparse(url).query
        target = urllib.parse.parse_qs(query).get("uddg")
        if target:
            return urllib.parse.unquote(target[0])
    except ValueError:
        pass
    return url


def _open(url: str, data: bytes | None = None, timeout: int = DEFAULT_TIMEOUT) -> tuple[str, str]:
    """Fetches a URL. Returns (text, final_url). Raises urllib errors."""
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(MAX_PAGE_BYTES)
        if response.headers.get("Content-Encoding") == "gzip":
            try:
                raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
            except (OSError, EOFError):
                pass
        charset = response.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace"), response.geturl()


def web_search(query: str, max_results: int = 6) -> str:
    """Searches the web and returns titles, URLs, and snippets."""
    query = query.strip()
    if not query:
        return "Error: Empty search query."

    max_results = max(1, min(max_results, 15))
    payload = urllib.parse.urlencode({"q": query}).encode()

    try:
        body, _ = _open(SEARCH_ENDPOINT, data=payload)
        results = _parse_results(body, max_results)
        if not results:
            # The HTML endpoint occasionally serves a layout we can't parse;
            # the lite endpoint is plainer and rarely changes.
            body, _ = _open(LITE_ENDPOINT, data=payload)
            results = _parse_lite_results(body, max_results)
    except urllib.error.HTTPError as e:
        return f"Error: Search failed with HTTP {e.code}. The search endpoint may be rate limiting."
    except urllib.error.URLError as e:
        return _explain_url_error(e, "the search service")
    except Exception as e:
        return f"Error performing search: {e}"

    if not results:
        return f"No results found for '{query}'."

    lines = [f"Search results for '{query}':\n"]
    for i, item in enumerate(results, 1):
        lines.append(f"{i}. {item['title']}")
        lines.append(f"   {item['url']}")
        if item["snippet"]:
            lines.append(f"   {item['snippet']}")
        lines.append("")
    lines.append("Use fetch_url on any of these URLs to read the full page.")
    return "\n".join(lines)


def _parse_results(body: str, limit: int) -> list[dict]:
    links = RESULT_LINK.findall(body)
    snippets = RESULT_SNIPPET.findall(body)

    results = []
    for i, (raw_url, raw_title) in enumerate(links[:limit]):
        title = _strip_tags(raw_title)
        if not title:
            continue
        snippet = _strip_tags(snippets[i]) if i < len(snippets) else ""
        if len(snippet) > 300:
            snippet = snippet[:300].rstrip() + "..."
        results.append({
            "title": title,
            "url": _unwrap_ddg_url(html.unescape(raw_url)),
            "snippet": snippet,
        })
    return results


def _parse_lite_results(body: str, limit: int) -> list[dict]:
    results = []
    for raw_url, raw_title in LITE_LINK.findall(body)[:limit]:
        title = _strip_tags(raw_title)
        if not title:
            continue
        results.append({
            "title": title,
            "url": _unwrap_ddg_url(html.unescape(raw_url)),
            "snippet": "",
        })
    return results


def fetch_url(url: str, max_chars: int = 15_000) -> str:
    """Fetches a URL and returns its readable text content."""
    url = url.strip()
    if not url:
        return "Error: No URL provided."
    if "://" not in url:
        url = "https://" + url

    scheme = urllib.parse.urlparse(url).scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        return f"Error: Only http and https URLs can be fetched (got '{scheme}')."

    try:
        body, final_url = _open(url)
    except urllib.error.HTTPError as e:
        return f"Error: HTTP {e.code} {e.reason} for {url}"
    except urllib.error.URLError as e:
        return _explain_url_error(e, url)
    except Exception as e:
        return f"Error fetching {url}: {e}"

    text = html_to_text(body)
    if not text.strip():
        return f"[{final_url}]\n(Page had no extractable text — it may be JavaScript-rendered.)"

    truncated = ""
    if len(text) > max_chars:
        text = text[:max_chars]
        truncated = f"\n\n... [truncated at {max_chars} chars]"

    return f"[{final_url}]\n\n{text}{truncated}"


def html_to_text(body: str) -> str:
    """Strips markup, scripts, and styling down to readable text."""
    text = SCRIPT_STYLE.sub(" ", body)
    text = BR.sub("\n", text)
    text = BLOCK_BREAK.sub("\n", text)
    text = TAG.sub(" ", text)
    text = html.unescape(text)
    text = SPACES.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return BLANK_LINES.sub("\n\n", text).strip()
