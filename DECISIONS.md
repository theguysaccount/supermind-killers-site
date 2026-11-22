# Decisions

1. **Neutral name and scope.** The working title ("Supermind Killers", profiles of social-media CEOs) invites defamation claims and reads as activism. Following the brief's machine loop, the public site is "Platform Defaults": a sourced comparison of product defaults, with no CEO profiles and no statements about any person. The repository keeps its original name only because the brief fixed it.

2. **Facts and quotes only.** Every answer quotes the platform's own documentation and links to it; quotes must appear word for word (checked by code every week). Summaries say "<Platform> says ...". Tests reject loaded words (addictive, harmful, dangerous, toxic, manipulative, killer and similar) in our prose. Every page has a correction link and a right-of-reply link.

3. **Seven questions, defined in advance.** Five teen defaults (private accounts, contact from strangers, time reminders, night-time quiet, sensitive content), parent tools, and a feed not based on recommendations. Each answer is "on by default" (2), "available" (1) or "not documented" (0). The count is labelled "defaults and controls documented", never a safety score. "Not documented" means we found no statement in the documents read, and pages say so.

4. **Ranking, autoplay and minimum age are facts, not points.** Platforms document them unevenly; scoring them would reward documentation style. Infinite scroll is not covered because no document read describes it as a setting.

5. **Sources.** Help centers, safety and parent centers, transparency pages, and the platforms' own announcements (for Instagram, the Teen Accounts announcement, because Instagram's help pages for teens are assembled by scripts). Polite reading only: identified reader, robots.txt respected (facebook.com is therefore not read), Internet Archive copies under 180 days old when a site refuses scripts (X), labelled with the capture date.

6. **Shared engine with the AI Privacy Scorecard** (same fetcher, quote checker, change detector, build and workflows), copied rather than shared as a package so each repository stays standalone.

7. **Six platforms at launch**: Instagram, Pinterest, Snapchat, TikTok, X, YouTube. Facebook and Reddit are listed as not covered, with reasons.

## Open question for Jack (doesn't block the site)

- A standalone site or a section of an existing brand? Built standalone; the domain rollout session can put it on any domain with one setting.
