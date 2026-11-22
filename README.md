# Platform Defaults

**How social apps are set up for teens by default, in each platform's own words. Re-checked every week.**

Live: https://theguysaccount.github.io/supermind-killers-site/

Each platform page answers seven questions: are teen accounts private by default, can strangers message teens, are time and bedtime reminders on, is sensitive content limited, are there parent tools, and can you switch to a feed that isn't based on recommendations. Every answer quotes the platform's own help, safety or transparency page, with a link. How each feed ranks content, autoplay defaults and minimum ages are listed as facts where documented. A weekly job re-reads every document, re-verifies every quote word for word and logs changes to a change page and an RSS feed. It describes products only: no profiles of executives or other people, no accusations, no safety ratings.

Covered: Instagram, Pinterest, Snapchat, TikTok, X, YouTube. Platforms whose documentation can't be read within this project's rules are listed on the home page with the reason.

## Run, test, build

Python 3.9+ with no dependencies; Node 22+ and Google Chrome for the browser checks.

```bash
python3 -m unittest discover -s tests        # unit, data and build tests
python3 -m pipeline.check                    # read every document, verify every quote (network)
python3 -m pipeline.build                    # build the site into dist/
python3 -m pipeline.og dist                  # share cards (needs Chrome)
node scripts/e2e.mjs                         # every page in headless Chrome, desktop and phone
node scripts/e2e.mjs https://theguysaccount.github.io/supermind-killers-site/
python3 scripts/check_live.py https://theguysaccount.github.io/supermind-killers-site
```

Reviewer tools: `python3 -m pipeline.grab --find "default" URL` prints the matching lines of a document as the weekly check reads it; `python3 -m pipeline.check --offline --review` re-verifies every quote against cached copies.

## Deploy

GitHub Actions does everything (see [OPERATIONS.md](OPERATIONS.md)): `deploy.yml` on every push to `main`, `check.yml` twice a week, `selftest.yml` weekly. The public address is one setting, the repository variable `SITE_URL`.

## Layout

| Path | What |
|---|---|
| `data/rubric.json` | The seven questions, answers, points and definitions |
| `data/platforms/<platform>.json` | One reviewed platform page: documents, answers, quotes, facts |
| `data/state.json`, `data/sigs/`, `data/changes.json` | Written by the weekly check |
| `data/not_covered.json` | Platforms not covered, with the reason |
| `pipeline/` | `fetch.py` (polite reader), `check.py` (weekly check), `build.py` (site), `og.py` (share cards), `grab.py` (reviewer tool) |
| `scripts/` | Browser checks, live health check, IndexNow, keep-alive, review issues |

The repository name comes from the original idea's working title; the public site uses the neutral name "Platform Defaults" (see DECISIONS.md). Code MIT; page text and data CC BY 4.0; quotes belong to their publishers.
