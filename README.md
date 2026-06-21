# MML Food Tracking

Local-first nutrition logging web app for a single user, built with FastAPI, SQLAlchemy, SQLite, Jinja templates, and pytest.

## Features

- Conversational logging for inputs like `2 eggs, 3 bacon, 1 Fairlife 42, 1 tbsp butter`
- Resolution pipeline with strict priority:
  1. exact alias lookup
  2. exact custom food name lookup
  3. fuzzy custom food or alias lookup
  4. USDA FoodData Central
  5. Open Food Facts fallback
  6. unresolved confirmation or custom food creation
- First-class custom foods with:
  - manual creation
  - editing through versioned updates
  - aliases
  - authoritative lock flag
  - duplication from external foods
  - historical nutrient snapshots preserved in logs
- Summary-first dashboard with daily targets, weekly chart, streak, and status strip
- Food library and custom food editor
- Daily and weekly analytics

## Stack

- Python 3.12+
- FastAPI
- SQLAlchemy 2.x
- SQLite
- Jinja templates
- HTMX-enhanced server-rendered UI
- pytest

## Project Structure

```text
app/
  main.py
  config.py
  db.py
  models/
  schemas/
  services/
  routers/
  templates/
  static/
tests/
migrations/
Scripts/
```

## Schema Overview

### `foods`

Stores nutrient definitions for both custom and external foods. Custom foods are versioned by creating a new row and marking the old row as no longer current. Key fields:

- `canonical_name`
- `brand`
- `source`
- `source_food_id`
- `serving_description`
- `grams_per_serving`
- `calories`
- `protein_g`
- `carbs_g`
- `fat_g`
- `fiber_g`
- `net_carbs_g`
- `raw_source_payload`
- `food_group_key`
- `version`
- `is_current`
- timestamps

### `food_aliases`

Exact alias mappings for fast resolution. Aliases can point to custom or external foods and are used first in the resolution order.

### `custom_food_metadata`

Custom-food-only metadata for authoritative lock state, notes, and the current version pointer.

### `meal_entries`

Stores the original raw entry text, meal label, and log timestamp.

### `meal_entry_items`

Stores parsed line items and the nutrient snapshot captured at time of entry, preserving history even if a food changes later.

### `daily_targets`

Daily macro and calorie targets used for dashboard remaining calculations.

### `food_resolution_history`

Audit trail of how phrases were resolved, whether confirmation happened, and whether a phrase was saved for future reuse.

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

3. Copy env settings:

```bash
cp .env.example .env
```

4. Add your USDA API key to `.env` if you want USDA lookups enabled.
5. Run the app:

```bash
uvicorn app.main:app --reload
```

6. Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

The app auto-creates the SQLite database and seeds demo foods on startup.

## Run as a Mac App

For day-to-day use on macOS, install the local app wrapper into your Applications folder and enable login auto-start:

```bash
./Scripts/install_mac_app.sh
open "/Applications/MML Food Tracking.app"
```

By default this installs to `/Applications/MML Food Tracking.app` when that folder is writable, otherwise `~/Applications/MML Food Tracking.app`. It also creates `~/Library/LaunchAgents/local.mml-food-tracking.plist`. The login item starts the local FastAPI server quietly at sign-in; double-clicking the app opens the browser to the app. You can move the app between `~/Applications` and `/Applications`; the login launcher checks both locations. To install directly somewhere else, run for example `APP_INSTALL_DIR="$HOME/Applications" ./Scripts/install_mac_app.sh`.

For development-only use, you can still build the wrapper without installing it:

```bash
./Scripts/package_app.sh
open ".build/MML Food Tracking.app"
```

The wrapper creates or reuses `.venv`, installs the app dependencies, starts the FastAPI server on `127.0.0.1:8787`, and opens the browser automatically unless launched with `--server-only` by the login item. It is intentionally a local wrapper around this checkout, not a standalone redistributable binary. If you move the repo, rerun `./Scripts/install_mac_app.sh`.

The wrapper stores its user database at `~/Library/Application Support/MML Food Tracking/mml_food_tracking.db` and writes startup logs to `~/Library/Logs/MML Food Tracking/server.log`. On first launch only, it will copy `mml_food_tracking.db` from the repo if that file exists locally; cloned repos normally start with a fresh database and seed data.

To share the app with another Mac user, have them clone the repository, install Python 3.12+, run `./Scripts/install_mac_app.sh`, and open the installed `MML Food Tracking.app`. Each user keeps their own private SQLite database, `.env`, and virtual environment outside of git.

## Test Instructions

Run:

```bash
pytest
```

The test suite covers the parser and the resolution order logic with mocked external lookups.

## API Endpoints

- `POST /api/foods`
- `PUT /api/foods/{food_id}`
- `GET /api/foods/search`
- `POST /api/foods/{food_id}/aliases`
- `POST /api/foods/{food_id}/duplicate`
- `POST /api/resolve`
- `POST /api/logs`
- `GET /api/summaries/daily`
- `GET /api/summaries/weekly`
- `GET /api/unresolved`

## Deferred Enhancements

- true unit conversion beyond serving-count assumptions
- background caching for USDA and Open Food Facts results
- authentication and multi-user support
- Alembic migration history instead of startup `create_all`
- richer charts with client-side interactivity
