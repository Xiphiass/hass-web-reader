# Extended Web Search for Home Assistant

A custom Home Assistant integration that provides **extended web search** capabilities to the LLM integration. Unlike basic search tools that only return snippets from search metadata, this integration **fetches the actual content from result web pages** and provides the full extracted text to your LLM.

## How It Works

1. **Search**: Queries your SearXNG instance with the user's search query
2. **Fetch**: Retrieves the full HTML content from each result URL
3. **Extract**: Parses the HTML and extracts clean, readable text (using BeautifulSoup)
4. **Return**: Provides the full page content to the LLM, not just search snippets

This two-step approach (search + fetch content) gives the LLM significantly more context to answer questions accurately — the same approach used by advanced tools like the Open WebUI extended web search.

## Tools Provided

| Tool | Description |
|------|-------------|
| `search_web` | Performs a SearXNG search and fetches full page content from each result |
| `open_url` | Fetches and extracts text content from a specific URL |

## Requirements

- A running [SearXNG](https://github.com/searxng/searxng-docker) instance with JSON responses enabled
- Home Assistant 2024.6 or newer (for LLM API support)

### SearXNG Configuration

Make sure your SearXNG instance has JSON format enabled in `settings.yml`:

```yaml
search:
  formats:
    - html
    - json
```

## Installation

### Manual Install

1. Copy the `custom_components/extended_web_search` folder into your Home Assistant `custom_components` directory.
2. Restart Home Assistant.

### HACS (Custom Repository)

1. In HACS, go to **Integrations** → **⋮** (three dots) → **Custom repositories**.
2. Add this repository URL and select **Integration** as the category.
3. Click **Install** on the "Extended Web Search" integration.
4. Restart Home Assistant.

## Configuration

1. Go to **Settings** → **Devices & Services**.
2. Click **Add Integration** and search for **Extended Web Search**.
3. Configure:
   - **SearXNG Server URL**: The URL of your SearXNG instance (e.g., `http://192.168.1.100:8080`)
   - **Number of search results**: How many result pages to fetch (default: 5)
   - **Max content length**: Maximum total characters of extracted content (default: 8000)
   - **Request timeout**: Timeout per HTTP request in seconds (default: 10)

## Conversation Agent Setup

After installation, enable the "Extended Web Search" API in your conversation agent:

1. Go to **Settings** → **Devices & Services**.
2. Open your conversation agent integration (e.g., OpenAI, Ollama, Google Generative AI).
3. In the agent's options, under **Control Home Assistant** / **LLM APIs**, enable **Extended Web Search**.

The LLM will now have access to `search_web` and `open_url` tools.

## Settings Explained

| Setting | Default | Description |
|---------|---------|-------------|
| SearXNG Server URL | — | URL of your SearXNG server |
| Number of results | 5 | Number of search result pages to fetch and extract content from |
| Max content length | 8000 | Total character budget for all page content combined (split evenly across results) |
| Request timeout | 10 | Timeout in seconds for each HTTP request (search query + page fetches) |

### Content Length Tips

- **8000** (default): Good for most queries, balances detail with token usage
- **16000–20000**: Better for research-heavy queries where you need more detail
- **4000**: More conservative, reduces token usage at the cost of less detail
- The budget is split evenly across results. With 5 results and 8000 chars, each page gets ~1600 chars

## Comparison with llm_intents SearXNG Search

| Feature | llm_intents SearXNG | Extended Web Search |
|---------|---------------------|---------------------|
| Search engine | SearXNG | SearXNG |
| Returns snippets | ✅ | ✅ (as fallback) |
| Fetches full page content | ❌ | ✅ |
| Dedicated URL fetching tool | ❌ | ✅ (`open_url`) |
| Content extraction | Metadata only | Full HTML → text via BeautifulSoup |

## License

MIT
