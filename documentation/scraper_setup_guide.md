# Compensation Scraper Setup Guide

This guide walks through registering for the free API keys needed to get full coverage from the
compensation data scraper. Without keys, several sources are skipped or rate-limited. With both
keys configured, all government data sources (FRED, BLS) are available at full rate.

Glassdoor and ZipRecruiter are covered by **JobSpy** (`python-jobspy`), an open-source Python
library that requires no API key or paid account.

---

## Summary of Keys

| Key    | Provider                      | Required  | Free Tier   | What It Unlocks                                      |
| ------ | ----------------------------- | --------- | ----------- | ---------------------------------------------------- |
| FRED   | Federal Reserve Economic Data | **Yes**   | Unlimited   | FRED median earnings time series source              |
| BLS v2 | Bureau of Labor Statistics    | No        | 500 req/day | Upgrades BLS from 25 req/day (v1) to 500 req/day (v2)|

---

## Step 1 — FRED API Key (Required)

FRED (Federal Reserve Economic Data) provides median earnings time series data. The source is
skipped entirely without a key.

**Registration steps:**

1. Go to: https://fred.stlouisfed.org/docs/api/api_key.html
2. Click **"Request or view your API keys"**
3. Log in or create a free account (no credit card needed)
4. Your API key will be shown immediately — it is a 32-character alphanumeric string

**Example key format:** `abcdef1234567890abcdef1234567890`

**What you get:** Access to the FRED REST API, which provides historical median weekly earnings
data by occupation and education level. The scraper queries series for aerospace/engineering
categories.

---

## Step 2 — BLS API Key (Optional, Recommended)

The BLS OEWS (Occupational Employment and Wage Statistics) source works without a key but is
rate-limited to 25 requests per day on the unauthenticated v1 endpoint. With a free v2 key,
the limit increases to 500 requests per day and you gain access to multi-series queries.

**Registration steps:**

1. Go to: https://data.bls.gov/registrationEngine/
2. Fill in the registration form (name, organization, email) — no credit card needed
3. Click **"Register"**
4. Check your email for your API key (arrives within a few minutes)

**Example key format:** `a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4`

**What you get:** BLS v2 API access, which supports up to 50 series per request (vs. 25/day
without a key). The scraper queries national and state-level wage percentiles (10th, 25th, 50th,
75th, 90th) for SOC codes 17-2011 (Aerospace), 17-2141 (Mechanical), and 17-2071 (Electrical).

---

## Step 3 — JobSpy (No Key Required)

Glassdoor and ZipRecruiter are scraped via [python-jobspy](https://github.com/Bunsly/JobSpy),
an open-source Python library. No API key, account, or paid subscription is needed.

**Install with:**

```txt
pip install python-jobspy
```

JobSpy handles bot-detection evasion internally using browser emulation. It returns individual
job listings (company, title, salary range, location, URL) rather than aggregate salary estimates.
This provides richer per-listing data compared to the aggregate salary pages previously scraped.

**Note:** JobSpy results depend on the current availability of Glassdoor and ZipRecruiter. If
either site changes its response format, JobSpy's maintainers typically release an update within
a few days. Glassdoor in particular has strict bot detection; if it returns 0 rows, check for a
`python-jobspy` update.

---

## Step 4 — Storing Keys

Keys are stored in `documentation/APIKeys.md` — a plain markdown file that is listed in
`.gitignore` and never committed to the repository. Edit it directly to add or update keys.

**Format:**

```markdown
## FRED
<your-fred-key>

## BLS
<your-bls-key>
```

The section headers must be exactly `## FRED` and `## BLS` (case-insensitive).
The key goes on the first non-blank line after each header. Extra whitespace and trailing
newlines are ignored.

**How the app reads them:**

On startup, `ScraperConfig` calls `loadApiKeys()` which checks in this order:

1. `tools/apiKeys.json` — a cached copy written automatically the first time `APIKeys.md` is
   parsed (also gitignored). Subsequent loads use this file for speed.
2. `documentation/APIKeys.md` — parsed on first run or if `apiKeys.json` is absent.

The app never asks you to enter keys through the UI. If both files are missing, affected sources
are silently skipped or rate-limited.

**To update a key:** edit `documentation/APIKeys.md`, then delete `tools/apiKeys.json` so the
cache is rebuilt from the updated markdown on the next app start.

---

## Step 5 — Verifying Coverage

When you navigate to **Market Tools → Scraper**, the app automatically validates both keys
once per session and displays a compact status banner at the top:

```txt
API Keys:  ✓ FRED   ✓ BLS
```

Each badge is green (valid), red (invalid or missing), or yellow (not provided — optional key).
If any key fails validation, a collapsible warning appears with the error message. Contact your
site administrator if keys were previously working and have stopped.

Expected status with both keys configured:

| Source       | Status           | Notes                                         |
| ------------ | ---------------- | --------------------------------------------- |
| Data USA     | Active           | No key needed                                 |
| BLS OEWS     | Active           | Full v2 access with key; v1 (limited) without |
| FRED         | Active           | Requires key                                  |
| H1B Data     | Active           | No key needed                                 |
| Levels.fyi   | Active (limited) | JS-heavy; partial data via direct request     |
| Glassdoor    | Active           | Via python-jobspy (no key needed)             |
| PayScale     | Active           | No key needed                                 |
| ZipRecruiter | Active           | Via python-jobspy (no key needed)             |
| Comparably   | Active           | No key needed                                 |
| Indeed       | Active           | No key needed                                 |
| Salary.com   | Active           | No key needed                                 |
| Career Pages | Active           | Greenhouse/Lever via JSON API; Workday limited|

---

## Troubleshooting

### FRED: "Invalid API key" or no data returned

- Double-check the key is exactly 32 characters with no extra spaces
- Confirm it was activated — FRED sometimes requires clicking an activation link in the
  confirmation email

### BLS: Still hitting 25/day rate limit

- Delete `tools/apiKeys.json` and restart the app so the cache is rebuilt from the updated
  `APIKeys.md`
- Confirm the key line in `APIKeys.md` immediately follows the `## BLS` header with no blank
  lines between them

### Glassdoor/ZipRecruiter returning 0 rows

- Check that `python-jobspy` is installed: `pip install python-jobspy`
- Update to the latest version: `pip install --upgrade python-jobspy`
- Glassdoor frequently changes bot detection; a JobSpy update usually fixes it within a few days
- ZipRecruiter tends to return 0 rows for very niche search terms — broad terms like
  "aerospace engineer" work better

### Key status banner shows red but keys look correct

- The banner validates against live APIs; a temporary network issue can cause false negatives
- Reload the page to force a re-validation (validation runs once per browser session)
- If the error persists, check the error message in the collapsible warning for the specific
  failure reason

### Career page sources returning no data

- Greenhouse and Lever (SpaceX, Rocket Lab) use a free public JSON API — no configuration needed
- Workday-hosted pages (Blue Origin, Northrop Grumman, GE Aerospace, Relativity) are JavaScript
  SPAs; a direct HTTP request returns a minimal HTML shell. Most of the job card content is
  injected by JS at runtime, so results from Workday companies will be sparse

### General: A source returns 0 rows

- Check the Errors & Warnings section in the Results view after a scrape
- Many sources return empty for specific search terms without indicating an error — this is
  expected for niche aerospace roles

---

## Key Storage Details

| File                         | Purpose                                                          | Committed       |
| ---------------------------- | ---------------------------------------------------------------- | --------------- |
| `documentation/APIKeys.md` | Human-maintained key file — edit this to add/update keys        | No (gitignored) |
| `tools/apiKeys.json`       | Auto-generated cache from `APIKeys.md` — do not edit manually | No (gitignored) |

**To add keys for the first time:** create `documentation/APIKeys.md` using the format above
and start the app. The cache file is written automatically.

**To update a key:** edit `APIKeys.md`, delete `tools/apiKeys.json`, restart the app.

**To remove all keys:** delete both files. Affected sources will be skipped or rate-limited.
