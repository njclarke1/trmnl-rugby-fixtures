# trmnl-rugby-fixtures

The next fixture for a rugby club, across every competition, on a TRMNL
(LaraPaper BYOS) e-ink display. It is the rugby sibling of
[trmnl-football-fixtures](https://github.com/njclarke1/trmnl-football-fixtures).
One codebase serves one stack per team:

| Stack | Host port | Container | Source adapter |
|---|---|---|---|
| Bristol Bears | 3459 | `trmnl-bristol-api` | `club_wp` (club website feed) |
| England | 3460 | `trmnl-england-api` | *later* |

**Status:** Phase 2 (sidecar core) is done. Still to come:

- Phase 3: broadcast rights map. Until then every fixture reports `tbc`.
- Phase 4: crests.
- Phase 5: `full.liquid`.
- Phase 6: hardening.

## Architecture

```
bristolbearsrugby.com/wp-json/afz/v1
  ├─ fixtures/ical/{season}/men   (iCal, CORE)        ┐  3–4 calls / 6 h
  └─ fixtures?seasonId=&category=men (JSON, extras)   ┘
                    ▼
trmnl-bristol-api (Flask, :3459)
  • parse + shape-check → last-good on any failure
  • rounds, TBC kickoffs, hold window, all date maths (zoneinfo)
  • GET /fixtures → flat JSON      GET /healthz
                    ▼
LaraPaper polling plugin (15 min) → M5Stack PaperS3 960×540
```

## Data source and its risk

**Source:** Bristol Bears' own website feed, which is a WordPress plugin namespace (`afz/v1`).

**Why this source:** in Phase 1 it was the only free, keyless source that carried every Bristol first-team competition, past and upcoming: Gallagher PREM, PREM Rugby Cup and the Champions Cup, including a knockout tie. The alternatives that were ruled out, and why, are in the project doc `rugby/phase1-source-decision.md`.

**Risk:** the feed is undocumented. It is part of the club's website, not a published API, so a site redesign could change or remove it without notice. Five protections are in place:

1. **The calendar is the core contract.** The fixture list comes from the iCal feed, which is RFC 5545 and Europe/London. It uses the same route as the fans' "ADD ALL" calendar button, so the club can't reshape it without breaking subscribers' calendars.
2. **The JSON adds extras only:** crest URLs, scores and result status. It also adds any of our fixtures the calendar lacks, flagged `source: club_json`, because a fixture missing from the core feed is not proof there is no fixture. If the JSON breaks, crests fall back to initials and every fixture still shows.
3. **Every fetch is shape-checked** (`app/validate.py`). Any of the following refuses the new data, keeps the last good list, and sets `data_check: true` with a reason. The panel then shows **DATA CHECK** within one refresh:
   - a season loses more than max(3, 25%) of its fixtures
   - more than 20% of events are unparseable
   - a season calendar that previously had fixtures disappears or stops being iCal.
4. **Last-good persistence.** The last good list is kept on a named volume, so an outage or a container restart never blanks the screen. An outage sets `stale: true` and retries every 10 minutes.
5. **Tests pin the format.** `tests/fixtures/` holds real feed responses saved from the NAS on 14–15 Oct 2026, so any change in what the code depends on fails the tests.

**Fallbacks** if the feed dies for good:

- **TheSportsDB premium** (about $9 a month): documented, and covers all three competitions.
- **Highlightly free** (100 requests a day): PREM Cup coverage unverified.
- **ESPN:** no PREM Cup, and its team schedule endpoint is broken for rugby.

## Known limitations

Each limitation is listed here and in the chat summary, not just in a docstring:

1. **Undocumented feed.** See above.
2. **No round in the feed.** Rounds are derived from the order of our fixtures within each competition this season:
   - PREM: Round 1–18, then Semi-final and Final. This relies on PREM having 10 teams and no byes.
   - Champions Cup: Pool · R1–R4, then Round of 16 through to Final.
   - PREM Cup: Round *n*. Its knockout stage, if Bristol reach one, would show as a higher round number.
   
   A postponed game re-staged out of order mislabels the games around it until it has been played.
3. **PREM play-offs not yet observed in the feed.** Bristol finished 2025/26 without a play-off game: the 6 Jun 2026 game at Sale was Round 18, with 18 played. Play-off ties are expected to appear like any other fixture, but this is unverified until it happens.
4. **"European Cup" covers both EPCR tiers.** Set `EURO_TIER` (`champions` or `challenge`) once a season. A team that drops from the Champions Cup pool into the Challenge Cup knockouts will show the configured tier's name.
5. **Provisional kickoffs.** The feed has no TBC flag. A Saturday or Sunday 15:00 kickoff more than `TBC_HORIZON_DAYS` (42) days away is shown as provisional (`15:00 TBC`):
   - A genuine 3pm game shows "TBC" until it is inside the horizon.
   - A placeholder that is never confirmed shows without "TBC" once inside it.
   - Either way the time shown is the club's.
6. **Exhibitions appear**, shown as *Friendly* with the round line *Exhibition*.
7. **The venue can be "TBD"**, shown as "Venue TBC". Home and away come from the fixture's team order, so a home game at a neutral ground still reads Home (e.g. Gloucester at the Principality Stadium, 17 Apr 2027).
8. **The club is the authority.** Where aggregators disagree on a kickoff, e.g. Newcastle 26 Dec 2026 is 15:05 here and 15:00 on Sky, the club's time is used.
9. **The hold window is time-based.** The current fixture stays up for 150 minutes after kickoff (rugby runs longer than football), even if a result is posted sooner. The countdown reads "Kicked off".
10. **Broadcast is pending (Phase 3).** Every fixture currently reports `tbc`.

## Maintenance

| When | What |
|---|---|
| Routine | **Nothing.** Kickoff times update themselves within 6 hours of the club editing them, and the TBC marker clears itself. |
| Once a season (summer) | Re-verify the broadcast rights map (Phase 3) against the rights holders' own announcements. Set `EURO_TIER`. The season ID rolls over automatically on 1 July (`SEASON_CUTOVER_MONTH`), and both the current and next season are always fetched. |
| Panel shows DATA CHECK | The feed changed shape. Read the reason at `/healthz`; the display keeps the last good list meanwhile. |

## Configuration

| Env | Default | Notes |
|---|---|---|
| `TEAM_NAME` | `Bristol Bears` | matched against fixture team names |
| `TEAM_BADGE` | word initials | spine badge, e.g. `BB` |
| `FIXTURES_SOURCE` | `club_wp` | `stub` serves `tests/fixtures/` (offline renders; enables `?now=`) |
| `CLUB_FEED_BASE` | Bristol's `wp-json/afz/v1` | |
| `CLUB_FEED_CATEGORY` | `men` | |
| `SEASON_IDS` | *(derived)* | e.g. `202601,202701` to override |
| `EURO_TIER` | `champions` | `champions` or `challenge` |
| `TBC_HORIZON_DAYS` | `42` | provisional-kickoff window |
| `HOLD_PAST_KICKOFF_MIN` | `150` | |
| `CACHE_TTL` | `21600` | 6 h |
| `OWNED_CHANNELS` | `sky,tnt,bbc,itv,channel4,channel5,s4c` | used from Phase 3 |
| `PUBLIC_BASE_URL` | `http://192.168.68.111:3459` | crest URLs (Phase 4) |
| `COMP_LABELS`, `TEAM_DISPLAY`, `TEAM_RAIL` | — | JSON overrides for labels and names |

## Deploy (Portainer git stack)

1. Go to Stacks → Add stack → Repository: `https://github.com/njclarke1/trmnl-rugby-fixtures`, compose path `docker-compose.yml`.
2. Copy the environment variables from `.env.example`. There are no secrets.
3. Deploy. To ship new code later, use **Pull and redeploy with "Re-pull image" OFF**. The image is built locally (`pull_policy: build`); re-pull would look for it on Docker Hub and fail.
4. Check the new code is live, then the data:
   ```bash
   docker exec trmnl-bristol-api ls /app/app/
   curl -s http://192.168.68.111:3459/healthz
   curl -s http://192.168.68.111:3459/fixtures
   ```

Never run `docker compose` by hand in `/data/compose/<id>`. It starts a separate project, which collides on the container name.

## Tests

```bash
pip install -r requirements.txt pytest
python -m pytest -q
```

The tests are stub-driven and use the real Phase 1 responses. They cover:

- the coverage matrix
- iCal parsing: time zones, UTC, all-day events, line folding
- enrichment and gap-filling from the JSON
- round labels
- the 150-minute hold window
- the BST→GMT change (25 Oct 2026)
- provisional kickoffs and friendlies
- season rollover and an empty season
- every shape check
- outage → last good → recovery, including a restart mid-outage.
