# Weekly Thermomix Planner

A local-first web app for planning weekly lunches and dinners cooked via Thermomix. You browse your saved Cookidoo recipe library, assign recipes to meal slots across a two-week rolling window, get a scaled and pantry-subtracted shopping list, and push the week's meals to the Cookidoo calendar so your TM5 or TM6 picks them up for guided cooking. This is a household utility, not a general recipe app, and is not a Vorwerk product.

---

## Features

**Week plan grid** — A Mon–Sun × Lunch/Dinner grid covering the current and next ISO week. Each slot shows the assigned recipe name, a pantry match score (how much of this recipe you already have), and per-slot serving controls. Empty slots have an inline recipe picker. Filled slots can be replaced or cleared. Navigation to weeks outside the current + next window is intentionally blocked.

**Recipe picker and search** — The right panel opens when you click a slot and shows recipes from your cached Cookidoo collections. You can filter by a text search query, by maximum cooking time, and browse by collection. Each recipe card shows cooking time, serving count, pantry match score, and a badge for custom recipes. Clicking a recipe assigns it to the focused slot.

**Pantry manager** — A CRUD list of ingredients you have at home. Items can be added one at a time or bulk-imported as a newline-separated list. The pantry drives both the shopping list subtraction and the suggestion scoring. Matching uses fuzzy string matching (rapidfuzz WRatio ≥ 85) with preposition stripping for Italian and Spanish ingredient names.

**Shopping list** — Aggregated and scaled across all slots in the selected week, with pantry items flagged as owned. Quantities are scaled per slot according to that slot's serving count. A "Sync to Cookidoo" button pushes the ingredient list to your Cookidoo account and marks owned items there too. A warning banner appears if any planned recipe has no cached ingredient data.

**Custom recipes** — You can create recipes locally (name, servings, cooking time, ingredients, optional source URL) for dishes not in your Cookidoo library. Custom recipes appear in the week plan and shopping list. They cannot be pushed to the Cookidoo calendar — see Limitations.

**Thermomix calendar sync** — Sends the current week's Cookidoo recipes to your calendar via the unofficial Cookidoo API. Recipes appear in the Cookidoo app and on the TM6 touchscreen. Local custom recipes are excluded from sync (no Cookidoo API support for this).

**Suggestions tab** — A ranked list of recipes scored by how many of their ingredients you currently have in your pantry. Recipes used in the previous two ISO weeks receive a small penalty to encourage variety. Filterable by maximum cooking time.

---

## How it works

The backend is a Python 3.12 FastAPI app backed by a local SQLite database (via aiosqlite). The frontend is a React/Vite single-page app proxied through Vite's dev server in development, or served by nginx in Docker. Cookidoo integration uses the [cookidoo-api](https://github.com/miaucl/cookidoo-api) library — an unofficial, community-maintained Python client. On first run, a cache refresh fetches recipe details from all your saved collections and stores them locally; with a large library (~1000 recipes) this takes approximately 6 minutes due to rate limiting. Subsequent use is fully local except for calendar/shopping sync and credential login.

---

## Requirements

- Python 3.12 or later
- Node.js 20 or later
- A Cookidoo account with an active subscription
- Thermomix TM5 or TM6 (TM6 has fuller support for Cookidoo-hosted custom recipes)

---

## Installation — local development

1. Clone the repository:
   ```
   git clone https://github.com/teowaits/thermomix-planner.git
   cd thermomix-planner
   ```

2. Create and activate a Python virtual environment:
   ```
   python3 -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   ```

3. Install Python dependencies:
   ```
   pip install -r requirements.txt
   ```

4. Install frontend dependencies:
   ```
   cd frontend && npm install && cd ..
   ```

5. Copy `.env.example` to `.env` and fill in your Cookidoo credentials:
   ```
   cp .env.example .env
   ```
   Edit `.env`:
   ```
   COOKIDOO_EMAIL=your.email@example.com
   COOKIDOO_PASSWORD=your_password
   COOKIDOO_COUNTRY=it        # e.g. it, de, fr, gb
   COOKIDOO_LANGUAGE=it-IT    # e.g. it-IT, de-DE, fr-FR, en-GB
   ```
   Valid `COOKIDOO_COUNTRY` / `COOKIDOO_LANGUAGE` pairs are listed in the [cookidoo-api localisation docs](https://miaucl.github.io/cookidoo-api/localization/).

6. Start the backend:
   ```
   uvicorn backend.main:app --reload --port 8000
   ```
   The server crashes intentionally on bad credentials — check `.env` if it fails at startup.

7. In a separate terminal, start the frontend:
   ```
   cd frontend && npm run dev
   ```

8. Open [http://localhost:5173](http://localhost:5173).

9. Trigger a cache refresh from the app (the banner at the top will prompt you if no recipes are cached). With a library of ~1000 recipes expect roughly 6 minutes.

---

## Installation — Docker (self-hosted / NAS)

1. Copy `.env.docker.example` to `.env` and fill in all variables:
   ```
   cp .env.docker.example .env
   ```
   Set `COOKIDOO_EMAIL`, `COOKIDOO_PASSWORD`, `COOKIDOO_COUNTRY`, `COOKIDOO_LANGUAGE`, `CORS_ORIGINS` (your host's address, e.g. `http://192.168.1.10:8080`), `APP_PORT`, `BASIC_AUTH_USER`, and `BASIC_AUTH_PASS`.

2. Build the images:
   ```
   docker compose build
   ```

3. Start the stack:
   ```
   docker compose up -d
   ```

4. Open `http://localhost:8080` (or the host/port you configured).

5. Log in with the credentials you set in `BASIC_AUTH_USER` / `BASIC_AUTH_PASS`.

6. Trigger a cache refresh from the app.

**Note on Synology NAS:** Synology Container Manager supports `docker-compose.yml` natively. Copy the project to the NAS (e.g. via `scp` or Synology Drive), open Container Manager → Project → Create, and point it at `docker-compose.yml`. The `db_data` named volume is created and managed automatically; recipe cache, pantry, and meal plan data are preserved across container rebuilds.

For external access outside your home network, Synology VPN Server (OpenVPN) is recommended. Do not expose the app port directly to the internet.

---

## Configuration

| Variable | Required | Default | Description |
|---|---|---|---|
| `COOKIDOO_EMAIL` | Yes | — | Cookidoo account email |
| `COOKIDOO_PASSWORD` | Yes | — | Cookidoo account password |
| `COOKIDOO_COUNTRY` | Yes | — | Country code, e.g. `it`, `de`, `fr`, `gb` |
| `COOKIDOO_LANGUAGE` | Yes | — | Language tag, e.g. `it-IT`, `de-DE`, `fr-FR`, `en-GB` |
| `CORS_ORIGINS` | No | `*` | Comma-separated allowed origins; tighten for Docker deployment |
| `APP_PORT` | No | `8080` | Host port for Docker deployment |
| `BASIC_AUTH_USER` | Docker only | — | HTTP Basic Auth username |
| `BASIC_AUTH_PASS` | Docker only | — | HTTP Basic Auth password |

---

## Limitations and known behaviour

- **Recipe discovery is limited to your saved collections.** The app caches only the recipes in your Cookidoo collections. There is no way to browse the full Cookidoo catalogue from this app.

- **The Cookidoo API is unofficial and reverse-engineered.** It may break without notice if Vorwerk changes their backend. Monitor [miaucl/cookidoo-api](https://github.com/miaucl/cookidoo-api) for updates.

- **Local custom recipes cannot be synced to the Cookidoo calendar.** The Cookidoo API has no endpoint for pushing externally created recipes. Custom recipes appear in the shopping list only.

- **Ingredient matching is fuzzy but not perfect.** Matching uses rapidfuzz WRatio ≥ 85 and strips common Italian/Spanish prepositions (`di`, `del`, `della`, `de`, etc.) from ingredient names. Mismatches can happen; pantry overrides are always available.

- **Serving quantity scaling applies to the in-app shopping list only.** When syncing to the Cookidoo shopping list, default recipe servings are used — the Cookidoo API does not support scaled quantities.

- **The cache refresh takes ~6 minutes for a library of ~1000 recipes** due to a 0.5-second delay between recipe detail requests (rate limiting). The app remains usable during refresh; the progress bar shows current status.

- **Unit normalisation is not implemented.** "200 g flour" and "0.2 kg flour" appear as two separate shopping list lines.

- **Single-worker only.** The backend must run with `--workers 1`. In-process state (cache status, Cookidoo session) is not safe to share across worker processes.

---

## Running tests

```
pytest
```

107 tests covering the shopping, suggestions, meal plan, and custom recipe modules. Route-level integration tests require a live Cookidoo account and are not in the test suite.

---

## Credits and prior art

This project was built with reference to and inspired by:

- **cookidoo-api** by miaucl
  https://github.com/miaucl/cookidoo-api
  The Python library that makes Cookidoo integration possible. This project would not exist without it.

- **mcp-cookidoo** by alexandrepa
  https://github.com/alexandrepa/mcp-cookidoo
  Demonstrated connecting Cookidoo to an LLM via MCP and reverse-engineering the custom recipe upload endpoint.

- **cookidoo-recipe-creator** by guimatheus92
  https://github.com/guimatheus92/cookidoo-recipe-creator

- **cookidoo-scraper** by tobim-dev
  https://github.com/tobim-dev/cookidoo-scraper

---

## Disclaimer

This project is not affiliated with, endorsed by, or connected to Vorwerk or Cookidoo in any way. Use of the unofficial Cookidoo API is at your own risk. The developers of cookidoo-api note the same.

---

## License

MIT
