# Operations

Platform Defaults runs itself on GitHub: Pages for hosting, Actions for every recurring job. Nobody needs to do anything for it to keep working. This file lists each automated job and how it fails safely, what to watch, and the keys Jack can turn later.

- **Live:** https://theguysaccount.github.io/supermind-killers-site/
- **Repo:** https://github.com/theguysaccount/supermind-killers-site

## Automated jobs

| Job | Workflow | When (UTC) | What it does | How it fails safely |
|---|---|---|---|---|
| Deploy | `deploy.yml` | every push to `main` (not docs-only), after each documentation check, by hand | Unit, data and build tests; builds `dist/`; renders share cards; runs every page in headless Chrome at 1280px and 390px (self-test, no script errors, no sideways scrolling); deploys to Pages; re-runs the browser check on the live site; pings IndexNow | Any failed test or browser check stops before the deploy, so the last good site stays live. IndexNow problems are logged, never fatal. |
| Documentation check | `check.yml` | Tuesdays and Fridays 08:37 | Reads every document on every platform page (robots.txt respected, 2 s between requests to a host, identified reader); verifies every quote word for word; compares each document's sentences with the last read; appends changes to `data/changes.json`; runs the tests; commits; starts `deploy.yml`; lists changed documents and missing quotes in one `needs-review` issue | A page that can't be read keeps its last good record and date; the run still passes. A page that shrinks to a fraction of its words is treated as unreadable, not as a change. Failing tests stop the commit. A change is recorded once per document version, so re-runs are harmless. |
| Self-test | `selftest.yml` | Thursdays 16:19 | Tests; the live site in headless Chrome; every sitemap URL answers 200 with its own canonical URL; the feed and open data parse; the IndexNow key is published; data freshness. If the documentation check last ran more than 9 days ago it starts one; more than 16 days is a failure | On failure it opens (or comments on) one `ops-alert` issue, and GitHub emails the repository owner. It never changes the site. |
| Keep-alive | `check.yml` and `selftest.yml` → `scripts/keepalive.sh` | with each of those runs, even when they fail | Re-enables every scheduled workflow; pushes an empty commit if the repository has been quiet for 45 days | GitHub disables schedules after 60 days without activity; the check normally commits twice a week anyway. |

GitHub skips and delays scheduled runs on this account, which is why the check has two weekly slots, every job is safe to re-run, and the self-test starts a check when the data is stale.

Schedule check at launch: on 22 Nov 2026 the weekly self-test and the documentation check each ran on their own schedule and passed (first runs at 17:15 and 20:00 UTC). The temporary cron lines that made them fire early were then removed.

## How documents are read

- `pipeline/fetch.py` sends `PlatformDefaultsBot/1.0 (+repo URL)`, reads robots.txt for each host and never fetches a disallowed URL (so facebook.com help pages are not read).
- If a site refuses automated readers, the reader uses the newest Internet Archive capture of the same URL under 180 days old and labels it with the capture date. At launch only X's help pages (help.x.com refuses scripts) were read this way. A page read only from the archive stays good while its copy is under 180 days old; a page that was read directly and then starts refusing keeps its last direct read for 14 days. After that the page says the latest check could not read it, and the quotes keep their dates.
- **Pages that differ by country.** GitHub runs jobs in several countries, and some publishers show a page differently by country (on 22 Nov 2026 one check ran in Chile and was shown Chile's versions of Google's and OpenAI's privacy policies). Each check looks up the country its runner reaches the web from and does nothing outside the US; pages known to vary are pinned to their US version in the URL (for example `gl=US`). After pinning a URL, or if a regional read slips through, run `python3 -m pipeline.check --rebaseline` from a US machine: it saves new fingerprints without recording changes. Remove any false entries from `data/changes.json` and note them in `data/corrections.json`.
- Sources are help centers, safety and parent centers, transparency pages and the platforms' own announcements. Marketing pages are avoided because they churn.

## What to watch

- **`needs-review` issues**: a document changed or a quote is no longer found. The page already shows a banner and marks the quote; someone (or the routine below) should re-read the document and update `data/platforms/<platform>.json`.
- **`ops-alert` issues**: the self-test failed.
- **`correction` and `right-of-reply` issues**: check each against the cited document before changing anything; add accepted corrections to `data/corrections.json` (`[{"date": "YYYY-MM-DD", "app": "<slug>", "text": "what changed"}]`).

## Re-reviewing a platform page

1. `python3 -m pipeline.grab --refresh --find "<word>" <document URL>` to see the current text.
2. Edit `data/platforms/<platform>.json`: answers, summaries ("<Platform> says ..."), quotes copied exactly, and set `reviewed` to today.
3. `python3 -m pipeline.check --only <platform>` then `python3 -m pipeline.check --offline --review --only <platform>`.
4. `python3 -m unittest discover -s tests`, commit, push.

The tests reject loaded words in our own prose (addictive, harmful, dangerous, toxic, manipulative and so on). Summaries say what a platform *says*. Pages describe products, never people.

## Keys Jack can turn later

### 1. Custom domain (the domain rollout session's job)

One setting, the repository variable `SITE_URL`, moves canonical URLs, sitemap, feed, share cards, badges and IndexNow; internal links are relative.

1. DNS. Subdomain: `CNAME <name> → theguysaccount.github.io`. Apex: `A @ → 185.199.108.153, 185.199.109.153, 185.199.110.153, 185.199.111.153`, `AAAA @ → 2606:50c0:8000::153, 2606:50c0:8001::153, 2606:50c0:8002::153, 2606:50c0:8003::153`, `CNAME www → theguysaccount.github.io`.
2. `gh api -X PUT repos/theguysaccount/supermind-killers-site/pages -f cname=<domain>`, wait for the certificate, then `gh api -X PUT repos/theguysaccount/supermind-killers-site/pages -F https_enforced=true`.
3. `gh variable set SITE_URL -R theguysaccount/supermind-killers-site --body "https://<domain>"` (no trailing slash).
4. `gh workflow run deploy.yml -R theguysaccount/supermind-killers-site`.

### 2. Money

GitHub Pages is non-commercial, so the site is free and has no checkout. The slot is a "Support this project" link, hidden until set: `gh variable set SUPPORT_URL --body "<url>"` (optionally `SUPPORT_LABEL`), then run `deploy.yml`. GitHub Sponsors needs the account owner's enrollment.

### 3. Analytics

Off by default ("No cookies, no tracking"). Activation = a visitor follows a quote to the platform's own document (`source-click`); also `copy/embed-code`, `share`, `filter/<answer>`. Turn on with a GoatCounter account: `gh variable set GOATCOUNTER_URL --body "https://<code>.goatcounter.com/count"`, then run `deploy.yml`.

### 4. Monthly review routine

AI-written work can't run in Actions (no API key). Schedule a Claude Code routine monthly (first Tuesday) on this repository with this prompt:

> In theguysaccount/supermind-killers-site: read the open `needs-review`, `correction` and `right-of-reply` issues. For each changed document, re-read it with `python3 -m pipeline.grab --refresh`, update `data/platforms/<platform>.json` following OPERATIONS.md ("Re-reviewing a platform page"), and close the issue with a note of what changed. For a correction that the cited document supports, fix the page and add an entry to `data/corrections.json`. Then check each platform's help and safety centers for new default settings for teens and add any you can quote. If there is time, add one platform from the backlog. Neutral wording only; describe products, never people. Run every test and push only if all pass. Never post anywhere else.

Backlog: Discord (safety center), Threads (help.instagram.com), Roblox, Twitch, BeReal, Facebook (only if a robots-allowed source documents its teen defaults).

### 5. Search Console

Google verification needs Jack's Google account (easiest with a custom domain). Bing, Yandex and others get every deploy through IndexNow; the account's host-root robots.txt lists this sitemap daily.
