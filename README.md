# framemine

Extract structured data from social media reels, TikToks, and video posts using AI vision — without paying the AI to watch full videos.

## How it works

```
Saved posts / local files / URLs
  → Download from platform (instaloader / yt-dlp)
  → ffmpeg extracts keyframes locally (free)
  → AI sees only distilled frames (cheap)
  → Structured JSON + Excel output
```

Most AI video analysis tools send entire videos to cloud APIs. framemine preprocesses locally with ffmpeg's scene detection, sending only the frames that matter. You get the same results at a fraction of the token cost.

## Quick start

```bash
git clone https://github.com/ronit111/framemine.git
cd framemine
bash setup.sh
source .venv/bin/activate
```

Set your Gemini API key (free at [aistudio.google.com/apikey](https://aistudio.google.com/apikey)):

```bash
export GEMINI_API_KEY="your-key-here"
```

Extract books from your saved Instagram reels:

```bash
framemine extract instagram:myusername -s books -o my_books
```

That's it. framemine logs into Instagram, downloads your saved posts, extracts keyframes, sends them to Gemini, deduplicates, enriches with book metadata, and writes JSON + Excel output.

### More examples

```bash
# Extract recipes from a list of URLs (requires yt-dlp)
framemine extract urls.txt -s recipes -o my_recipes

# Extract products from a single TikTok (requires yt-dlp)
framemine extract "https://tiktok.com/@user/video/123" -s products

# Process a local folder of already-downloaded reels
framemine extract ./my_reels/ -s books -o my_books

# Limit to first 20 saved posts
framemine extract instagram:myusername -s books --max-posts 20
```

## What you get

- **JSON** file with all extracted items
- **Excel** file with formatted headers, auto-filter, frozen panes, and hyperlinked sources

## Schemas

framemine ships with three extraction schemas:

| Schema | What it extracts | Output fields |
|--------|-----------------|---------------|
| `books` | Book, essay, article, newsletter recommendations | title, author, type, genre, source |
| `recipes` | Recipes from cooking content | name, cuisine, difficulty, key_ingredients, source |
| `products` | Product recommendations from hauls/reviews | name, brand, category, price_range, source |

The `books` schema also enriches results with author and genre metadata via Google Books and Open Library.

```bash
framemine schemas  # List all available schemas
```

## Input modes

| Input | Example | Requirements |
|-------|---------|--------------|
| Instagram saved | `framemine extract instagram:user -s books` | instaloader |
| TikTok user videos | `framemine extract tiktok:user -s products --cookies chrome` | yt-dlp |
| YouTube playlist | `framemine extract youtube:PLAYLIST_URL -s recipes` | yt-dlp |
| Local directory | `framemine extract ./reels/ -s books` | ffmpeg (for videos) |
| Single file | `framemine extract video.mp4 -s books` | ffmpeg (for videos) |
| URL list (.txt) | `framemine extract urls.txt -s recipes` | yt-dlp, ffmpeg |
| Single URL | `framemine extract "https://..." -s products` | yt-dlp, ffmpeg |

Images (screenshots, photos) are sent directly to the AI without ffmpeg.

### Platform authentication

**Instagram**: instaloader handles login interactively. On first use it prompts for your password, then caches the session for subsequent runs.

**TikTok / YouTube**: Use `--cookies chrome` (or firefox, etc.) to pass your browser session cookies to yt-dlp for accessing private or liked content.

## Configuration

Copy and edit the example config:

```bash
cp config.example.yaml framemine.yaml
```

```yaml
ai:
  backend: gemini          # or "openai" for any OpenAI-compatible API
  gemini:
    models:                # Rotates through models to avoid per-model rate limits
      - gemini-2.5-flash
      - gemini-2.5-flash-lite
      - gemini-2.0-flash
      - gemini-2.0-flash-lite
    delay_seconds: 4.0

extraction:
  scene_threshold: 0.3     # Scene detection sensitivity (lower = more frames)
  max_keyframes: 15        # Max frames per video
```

See [config.example.yaml](config.example.yaml) for all options including OpenAI backend configuration.

The config file is optional. Without it, framemine uses Gemini with default settings and reads `GEMINI_API_KEY` from the environment.

### AI backends

**Gemini (default)** — Free tier available. Rotates across 4 models for rate-limit resilience. Set `GEMINI_API_KEY` env var or add `api_key` to config.

**OpenAI-compatible** — Works with OpenAI, Ollama, vLLM, or any API that speaks the OpenAI chat completions format. Set `OPENAI_API_KEY` env var or add `api_key` to config.

```yaml
ai:
  backend: openai
  openai:
    base_url: http://localhost:11434/v1  # Ollama example
    model: llava
```

### Config file locations

framemine looks for config in this order:
1. `--config path/to/config.yaml` (explicit flag)
2. `./framemine.yaml` (current directory)
3. `~/.config/framemine/config.yaml` (user home)

## Requirements

- **Python 3.10+**
- **ffmpeg** — for video frame extraction ([ffmpeg.org](https://ffmpeg.org/))
- **yt-dlp** (optional) — for downloading from URLs ([github.com/yt-dlp/yt-dlp](https://github.com/yt-dlp/yt-dlp))
- **instaloader** (optional) — for downloading Instagram saved posts (`pip install instaloader`)

```bash
framemine check  # Verify all dependencies
```

## CLI reference

```
framemine extract SOURCE -s SCHEMA [OPTIONS]

  SOURCE is a local directory, .txt file of URLs, single URL, media file,
  or platform:username (e.g. instagram:myuser, tiktok:myuser).

Options:
  -s, --schema TEXT       Extraction schema (required): books, recipes, products
  -o, --output TEXT       Output filename stem (default: schema name)
  -c, --config TEXT       Path to config YAML
  --cookies TEXT          Browser for yt-dlp/platform cookies (chrome, firefox, etc.)
  --max-posts INT         Max posts to download from saved collections
  --no-enrich             Skip metadata enrichment
  --json-only             Output JSON only, skip Excel
  --output-dir TEXT       Directory for output files (default: current directory)

framemine schemas         List available extraction schemas
framemine check           Verify all dependencies are installed
framemine --version       Show version
framemine -v ...          Enable debug logging (goes before any command)
```

## License

MIT
