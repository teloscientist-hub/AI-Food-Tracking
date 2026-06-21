# Test Suite Reference

This document summarizes the automated tests currently configured for the MML Food Tracking app.

Current status:
- command: `.venv/bin/pytest`
- latest result: `67 passed, 1 warning`

Important scope note:
- The suite is strong on route behavior, parsing, resolution, persistence, and server-rendered page wiring.
- It does **not** yet provide full browser automation for every visual interaction.
- That means hover states, drag/drop feel, popup positioning, and some dropdown behavior are only partially covered unless they trigger server-side routes or form submissions.

## Test Configuration

Project test configuration lives in:
- [`/Users/mark/Library/CloudStorage/Dropbox-BPTNB/mark lewis/_GPT Meta/App Development/AI-Food-Tracking/pyproject.toml`](/Users/mark/Library/CloudStorage/Dropbox-BPTNB/mark%20lewis/_GPT%20Meta/App%20Development/AI-Food-Tracking/pyproject.toml)

Pytest is configured to:
- use `tests/` as the test root
- add the project root to `pythonpath`

Shared fixtures live in:
- [`/Users/mark/Library/CloudStorage/Dropbox-BPTNB/mark lewis/_GPT Meta/App Development/AI-Food-Tracking/tests/conftest.py`](/Users/mark/Library/CloudStorage/Dropbox-BPTNB/mark%20lewis/_GPT%20Meta/App%20Development/AI-Food-Tracking/tests/conftest.py)

Those fixtures provide:
- an in-memory SQLite database for each test
- a default daily target row
- a FastAPI `TestClient`
- dependency overrides so tests run without the real local DB or demo seeding

## Test Files

### `tests/test_parser.py`
File:
- [`/Users/mark/Library/CloudStorage/Dropbox-BPTNB/mark lewis/_GPT Meta/App Development/AI-Food-Tracking/tests/test_parser.py`](/Users/mark/Library/CloudStorage/Dropbox-BPTNB/mark%20lewis/_GPT%20Meta/App%20Development/AI-Food-Tracking/tests/test_parser.py)

What it tests:
- conversational parsing of quantities and food phrases
- comma-separated food lists
- default quantity behavior for natural-language entries
- preserving food names that contain `and`
- spelled-out numbers like `Five eggs`
- fraction parsing like `1/32 of a stick of butter`
- branded phrase cleanup
- compound weight tokens like `5-oz banana`
- unit extraction such as `tbsp`, `stick`, `oz`, `containers`

### `tests/test_resolution.py`
File:
- [`/Users/mark/Library/CloudStorage/Dropbox-BPTNB/mark lewis/_GPT Meta/App Development/AI-Food-Tracking/tests/test_resolution.py`](/Users/mark/Library/CloudStorage/Dropbox-BPTNB/mark%20lewis/_GPT%20Meta/App%20Development/AI-Food-Tracking/tests/test_resolution.py)

What it tests:
- exact custom alias resolution
- custom-first behavior before external fallback
- USDA fallback when custom misses
- phrase cleanup before search
- branded phrase variant generation
- branded-food detection heuristics
- preferring Open Food Facts for branded products when USDA is weak
- penalizing generic USDA for strong brand queries
- preferring OFF before USDA branded for product-like branded items
- preferring simple whole foods over irrelevant branded items

This file is the core safeguard for search priority logic.

### `tests/test_off_client.py`
File:
- [`/Users/mark/Library/CloudStorage/Dropbox-BPTNB/mark lewis/_GPT Meta/App Development/AI-Food-Tracking/tests/test_off_client.py`](/Users/mark/Library/CloudStorage/Dropbox-BPTNB/mark%20lewis/_GPT%20Meta/App%20Development/AI-Food-Tracking/tests/test_off_client.py)

What it tests:
- Open Food Facts nutriment parsing from serving-based payloads
- reading plain OFF nutrient keys like:
  - `energy-kcal`
  - `proteins`
  - `carbohydrates`
  - `fat`
  - `fiber`
- scaling `_100g` nutrient payloads to serving size
- deriving net carbs from carbs and fiber when appropriate

### `tests/test_logging_service.py`
File:
- [`/Users/mark/Library/CloudStorage/Dropbox-BPTNB/mark lewis/_GPT Meta/App Development/AI-Food-Tracking/tests/test_logging_service.py`](/Users/mark/Library/CloudStorage/Dropbox-BPTNB/mark%20lewis/_GPT%20Meta/App%20Development/AI-Food-Tracking/tests/test_logging_service.py)

What it tests:
- saving meals with a mix of resolved and unresolved items
- unresolved items contributing zero macros while still being saved
- correction memory / alias creation when `always map` is selected
- persistence of external candidates into the DB
- promoting an external candidate into a custom food
- serving multiplier logic for unit conversions like `oz` against a serving size

### `tests/test_food_service.py`
File:
- [`/Users/mark/Library/CloudStorage/Dropbox-BPTNB/mark lewis/_GPT Meta/App Development/AI-Food-Tracking/tests/test_food_service.py`](/Users/mark/Library/CloudStorage/Dropbox-BPTNB/mark%20lewis/_GPT%20Meta/App%20Development/AI-Food-Tracking/tests/test_food_service.py)

What it tests:
- creating foods with aliases and custom metadata
- updating custom foods through versioned records
- duplicating external foods into custom foods
- search filtering by query and source
- storing uploaded image bytes and content types
- removing custom foods from the active library without hard deletion
- `/foods` ordering for previously logged items

This is the main service-layer coverage for the food library and custom-food lifecycle.

### `tests/test_picker_foods.py`
File:
- [`/Users/mark/Library/CloudStorage/Dropbox-BPTNB/mark lewis/_GPT Meta/App Development/AI-Food-Tracking/tests/test_picker_foods.py`](/Users/mark/Library/CloudStorage/Dropbox-BPTNB/mark%20lewis/_GPT%20Meta/App%20Development/AI-Food-Tracking/tests/test_picker_foods.py)

What it tests:
- picker ordering by recent logged foods
- restoring the last used amount/unit in the picker
- unit option ordering in picker rows
- exposing image URLs from source payloads
- food-library ranking by log count and recency
- promoting newly created custom foods above older logged items in recent-activity style sorting

### `tests/test_summary_service.py`
File:
- [`/Users/mark/Library/CloudStorage/Dropbox-BPTNB/mark lewis/_GPT Meta/App Development/AI-Food-Tracking/tests/test_summary_service.py`](/Users/mark/Library/CloudStorage/Dropbox-BPTNB/mark%20lewis/_GPT%20Meta/App%20Development/AI-Food-Tracking/tests/test_summary_service.py)

What it tests:
- daily macro/calorie totals
- dashboard status text
- streak calculations
- weekly summary generation
- weekly averages
- top foods
- dashboard context for:
  - unresolved count
  - custom food count
  - daily note
  - exercise check-in values

### `tests/test_web_submit.py`
File:
- [`/Users/mark/Library/CloudStorage/Dropbox-BPTNB/mark lewis/_GPT Meta/App Development/AI-Food-Tracking/tests/test_web_submit.py`](/Users/mark/Library/CloudStorage/Dropbox-BPTNB/mark%20lewis/_GPT%20Meta/App%20Development/AI-Food-Tracking/tests/test_web_submit.py)

What it tests:
- parsing selected food values from the review form
- accepted value forms:
  - plain numeric IDs
  - `food:<id>`
  - `external:<index>`
  - `exclude`
- graceful fallback for unknown selection types
- blank quick-log review submissions redirecting back with an error instead of crashing

### `tests/test_app_routes.py`
File:
- [`/Users/mark/Library/CloudStorage/Dropbox-BPTNB/mark lewis/_GPT Meta/App Development/AI-Food-Tracking/tests/test_app_routes.py`](/Users/mark/Library/CloudStorage/Dropbox-BPTNB/mark%20lewis/_GPT%20Meta/App%20Development/AI-Food-Tracking/tests/test_app_routes.py)

What it tests:
- primary page rendering for:
  - dashboard
  - log
  - foods
  - weekly
  - settings
- navigation wiring in rendered HTML
- dashboard date arrows
- week panel axis rendering
- `/foods` source modes:
  - custom
  - USDA
  - Open Food Facts
- external `/foods` search result rendering for USDA and OFF
- external save actions:
  - save
  - save and add
  - save and edit
- food library sort chip wiring
- food detail page actions
- custom food create/update flows
- image endpoint behavior
- custom food removal flow
- review-page save-as-custom flow
- dashboard and daily page meal action rendering
- meal item edit/copy/remove routes
- exercise form submissions
- settings page rendering and save flows
- dashboard/daily log page rendering of meal sections
- meal group actions:
  - copy meal
  - move item
  - remove all

This is the broadest end-to-end server-side test file in the project.

## What Is Covered Well

These areas are well covered by the current suite:
- parser correctness
- custom-first food resolution
- branded search heuristics
- Open Food Facts nutrient normalization
- custom food create/update/duplicate/remove flows
- image persistence endpoints
- quick-log submit handling
- route existence and form wiring
- library sorting and picker recency logic
- dashboard/weekly summary calculations
- meal copy/move/remove server behavior

## What Is Not Yet Fully Covered

These areas would need browser automation for true end-to-end coverage:
- popup open/close behavior in a real browser
- dropdown open state and visual interaction
- drag/drop UX details beyond server route coverage
- modal stacking and positioning
- hover states
- layout regressions and alignment issues
- live client-side preview updates on the `/log` page
- keyboard behavior on every field and control

## Known Warning

The suite currently passes with one warning:
- `tests/test_app_routes.py::test_meal_group_copy_move_and_clear_actions_work`
- SQLAlchemy warns that a delete expected to affect one row affected zero rows

Current location:
- [`/Users/mark/Library/CloudStorage/Dropbox-BPTNB/mark lewis/_GPT Meta/App Development/AI-Food-Tracking/app/routers/web.py`](/Users/mark/Library/CloudStorage/Dropbox-BPTNB/mark%20lewis/_GPT%20Meta/App%20Development/AI-Food-Tracking/app/routers/web.py)

This warning does not currently fail the suite, but it should be cleaned up.

## How To Run

From the project root:

```bash
.venv/bin/pytest
```

Useful narrower runs:

```bash
.venv/bin/pytest tests/test_app_routes.py
.venv/bin/pytest tests/test_parser.py tests/test_resolution.py
.venv/bin/pytest tests/test_food_service.py tests/test_picker_foods.py
```

## Recommended Next Step

If you want literal coverage of “every button, every popup, every dropdown” in the browser, the next step is:
- add browser automation tests for the major UI flows

Best candidates:
- Playwright
- Selenium

That would let us verify:
- popups opening and closing
- dropdown usage
- drag/drop meal movement
- quick-log review interactions
- picker row edits
- menu actions on the dashboard and daily log pages
