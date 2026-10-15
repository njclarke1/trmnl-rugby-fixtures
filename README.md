# trmnl-rugby-fixtures

The next fixture for a rugby club, across every competition, on a TRMNL
(LaraPaper BYOS) e-ink display. It is the rugby sibling of
[trmnl-football-fixtures](https://github.com/njclarke1/trmnl-football-fixtures).
One codebase serves one stack per team:

| Stack | Host port | Container | Source adapter |
|---|---|---|---|
| Bristol Bears | 3459 | `trmnl-bristol-api` | `club_wp` (club website feed) |
| England | 3460 | `trmnl-england-api` | `world_rugby` (World Rugby data API) |

**Status:** Bristol: Phases 2–5 done (sidecar, rights map, crests, `full.liquid`); Phase 6 (hardening) to come.
England: Phase 2 done (World Rugby adapter + dispatcher, stub-tested). Dormant mode, the England rights map,
the plugin branch and the 3460 deployment are still to come — **do not deploy the England stack yet**.

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
   - PREM Cup: Pool game 1–8, then Semi-final and Final. The cup has two pools of five playing home and away over ten rounds, so each team has byes, and "Pool game *n*" is used rather than a round number.
   
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
10. **Broadcast comes from a rights map, not listings.** See [Broadcast](#broadcast):
    - PREM is resolved as "TNT Sports". The specific TNT channel isn't known in advance, and some PREM games are on HBO Max only.
    - ITV's free-to-air picks and televised PREM Cup games only appear once added as overrides.

## England: data source and its risk

**Source:** World Rugby's own data API (Pulselive, the API behind world.rugby), keyless:
`GET https://api.wr-rims-prod.pulselive.com/rugby/v3/match?teams=34&startDate=…&endDate=…`.
England men's XV is team **34**, pinned in `WR_TEAM_ID` and never searched at runtime
(England Women / A / U20 have other ids). One call returns every England fixture in a
400-days-back / 550-days-forward window.

**Why this source:** in Phase 1 (15 Oct 2026) it was the only free source that carried every
row of the coverage matrix: Six Nations 2026 *and 2027*, Nations Championship July and
November, RWC 2027 pool. ESPN has no 2027 Six Nations; englandrugby.com blocks non-browser
clients (HTTP 403). Every kickoff present in both World Rugby and ESPN agreed to the minute.
Decision record: project doc `rugby/phase1-england-source-decision.md`.

**Protections** (same model as Bristol's):

1. **Ignored team filter is caught.** World Rugby silently ignores `teamId=` and returns 100
   unrelated matches; only `teams=` filters. Any match without team 34 refuses the whole
   response → DATA CHECK.
2. **Per-competition shape checks** (counts keyed by competition-year, e.g. `Six Nations 2027`).
   A competition may only disappear once its last match has aged out of the query window.
3. **Last good persisted**, outage → stale, as for Bristol.
4. **Tests pin the format:** `tests/fixtures/england/` holds the real probe responses.

**Fallbacks:** ESPN core API (England = team 1; no 2027 Six Nations at probe time),
TheSportsDB premium.

## England: known limitations

1. **Undocumented API.** See above.
2. **Finals weekend is derived, not listed.** The Nations Championship finals (27–29 Nov 2026,
   positional play-offs) are not in any source until pairings are known after round 6.
   Every team plays, so an all-day **"Opponent TBC"** fixture is derived from the
   competition's end date (`WR_FINAL_ROUND_COMPS`, `WR_FINAL_ROUND_SPAN_DAYS=3`) and held
   for the whole weekend. It assumes the final round fills the last 3 days of the
   competition; the real fixture replaces it as soon as World Rugby lists it.
3. **No round numbers for Six Nations / Nations Championship** (World Rugby gives "Match 15").
   RWC carries its phase ("Pool F"). Round labels for national competitions arrive in Phase 3.
4. **No crests:** World Rugby serves no logo URLs. Ovals show the team abbreviation.
5. **Venue string:** "Stadium, City", with the city dropped when it is already in the name
   (*Brisbane Stadium*) and dual names trimmed ("Brisbane | Meeanjin" → Brisbane).
6. **Event status is unreliable** (the finished 2026 Six Nations still says "Scheduled");
   only per-match status is used.

## Broadcast

Rugby rights are sold per competition, so `app/rights.py` is a static map. Every line was checked against the rights holder's own announcement on 15 Oct 2026, and the sources are listed in the file.

| Competition | UK broadcaster (2026/27) | State for this install |
|---|---|---|
| Gallagher PREM | TNT Sports, all 93 games, also on HBO Max. ITV simulcasts 7 games incl. the Final | `available` |
| PREM Rugby Cup | TNT Sports shows 13 selected games | `tbc` until a game is named in an override |
| Champions Cup | Premier Sports, all 63 games | `unavailable` (a normal state on European nights) |
| Challenge Cup | Premier Sports, selected games | `unavailable` |
| Friendly | — | `tbc` ("check the club's own stream") |

The four states are `available`, `unavailable`, `tbc` and `none` (confirmed not televised). There is no `blackout`; that is football-only.

**Rights expire on purpose.** Each entry has a `valid_until` (end of June 2027). A fixture after that date shows `tbc` ("rights not yet verified") rather than silently assuming last season's deal still applies. The Premier Sports EPCR deal ends with 2026/27.

**Per-fixture overrides** live in `app/broadcast_overrides.json`, plus the env `BROADCAST_OVERRIDES` (same JSON shape; the env wins). They are keyed by the fixture `id` from `/fixtures`:

```json
{"294928": {"channels": ["ITV1", "ITVX", "TNT Sports 1"], "note": "ITV pick"}}
```

`"channels": []` marks a game as confirmed not televised. Use overrides for ITV's free-to-air PREM picks, which are announced in blocks, and for televised PREM Cup games. As of 15 Oct 2026, no Bristol game has been picked by ITV.

**Unverified, so not encoded:** "Challenge Cup — selected games on the BBC". No rights-holder source was found for this.

**HBO Max:** it is a separate channel family (`hbomax`). Add it to `OWNED_CHANNELS` if you have TNT through HBO Max; then HBO Max-only games are also counted as yours.

## Crests

Crest URLs come from the club feed's JSON, for both teams. During each upstream refresh, `app/crests.py` turns each crest into a 1-bit **90×68 oval**: the inside of the mock's 96×74 oval, less its 3px border. Each crest is processed once and cached on the volume. The steps are:

1. Composite onto white and convert to greyscale.
2. Trim to the crest. For a transparent PNG, the alpha channel defines the crest's edges.
3. Fit to 78% of the oval, then apply UnsharpMask.
4. Convert to black and white with **Otsu**, a threshold chosen automatically for each crest from its own opaque pixels, measured before sharpening.
5. Apply the oval mask.

Two variants are produced:

- `crest`: black on white.
- `crest_inv`: white on black, which is the mock's `.crest.inv` style for your own side.

**Polarity.** A crest is inverted only when it sits on its own opaque dark background, i.e. all four corners of the crest box are black. Even then, only the crest box is inverted. A dark shield on a transparent background is never flipped.

**Pale crests.** Transparent crests get a silhouette outline drawn from their alpha channel, so a white or pale crest still shows its shape on white paper.

**Fallback.** The payload names a crest only once its file exists. Until then, or if fetching it failed, the template shows the 3-letter initials from the mock.

**Checking by eye:** open `http://192.168.68.111:3459/crests` in a browser. It shows each original crest next to both variants at 1× and 3×. If a crest reads badly, list it in `CREST_DITHER` to dither it instead (team names, comma-separated), or set `CREST_THRESHOLD`. The cache key includes the render mode, so changing either re-renders on the next refresh. To re-render everything, bump `PIPELINE_VERSION`.

Club crests are trademarks. The cache is git-ignored, and the tests use synthetic images.

## Plugin (LaraPaper)

`plugin/full.liquid` is built from mock panels 1–2. What marks it as rugby rather than football:

- a black left spine carrying the competition, the round and the team badge (football has a top bar);
- oval crests, with your side's crest inverted;
- an H goalpost divider between the two teams.

The rest follows the football screen on purpose: venue strip, kickoff panel, countdown chip, the four-state *Watch on* band, and the next-up rail with filled (on your TV) or hollow chips. The strip also shows a **DATA CHECK** tag when the feed has changed shape, or **CACHED** when it is serving last-good data. When there are no fixtures, an idle screen takes over.

Set-up:

1. In LaraPaper, create a polling plugin:
   - polling URL `http://192.168.68.111:3459/fixtures`, method GET;
   - `data_stale_minutes: 15`;
   - markup: paste `plugin/full.liquid`.
2. The device's width and height must be set by hand to **960 × 540**.
3. To force an immediate poll and render, or to force a demo state, use tinker. `polling_url` and `updateDataPayload()` are LaraPaper's own `Plugin` model, and the plugin's `name` is whatever you called it (here `trmnl-bristol`):
   ```bash
   docker exec -it larapaper php artisan tinker
   ```
   ```php
   $p = App\Models\Plugin::where('name', 'trmnl-bristol')->first();
   $d = App\Models\Device::find(1);
   $show = function ($path) use ($p, $d) { $p->polling_url = "http://192.168.68.111:3459$path"; $p->save(); $p->updateDataPayload(); app(App\Actions\Api\RunDeviceDisplayCycle::class)->handle($d); };
   $show('/fixtures');               // live
   $show('/demo/available.json');    // then any state below; finish with $show('/fixtures')
   ```
   If the device's playlist rotates through several plugins, the display cycle may land on another one. Keep this plugin current while testing.

**Forcing each state on the panel.** Use `$show('/demo/<state>.json')` above, or edit the polling URL in the UI. These are canned payloads built from the bundled real responses, so crests appear once they are cached. `/demo` lists the states:

| State | What it shows |
|---|---|
| `available` | the TNT state |
| `unavailable` | Champions Cup / Premier Sports |
| `tbc` | PREM Cup |
| `none` | a game confirmed as not televised |
| `itv` | an override for an ITV free-to-air pick |
| `provisional` | a TBC kickoff in the rail |
| `long_name` | Newcastle Red Bulls (tests long team names) |
| `kicked_off` | a match in its hold window after kickoff |
| `friendly` | an exhibition match |
| `data_check` | the DATA CHECK tag |
| `empty` | the idle screen |

**Always finish with `$show('/fixtures')`.** A demo URL left in place freezes the panel on canned data.

**Preview without the panel:** `python plugin/demo/render_demo.py` writes HTML (and PNGs if Playwright is installed) for every state into `plugin/demo/out/`. Chromium approximates the renderer; the panel has the final say.

## Maintenance

| When | What |
|---|---|
| Routine | **Nothing.** Kickoff times update themselves within 6 hours of the club editing them, and the TBC marker clears itself. |
| As announced (optional) | Add ITV free-to-air picks and televised PREM Cup games involving your team to `broadcast_overrides.json`, or to `BROADCAST_OVERRIDES` in Portainer, which needs no commit. |
| Once a season (summer) | Re-verify `app/rights.py` against the rights holders' own announcements, then move each `valid_until` forward. Until you do, next season's fixtures show `tbc`. Set `EURO_TIER`. The season ID rolls over automatically on 1 July (`SEASON_CUTOVER_MONTH`), and both the current and next season are always fetched. |
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
| `OWNED_CHANNELS` | `sky,tnt,bbc,itv,channel4,channel5,s4c` | channel families you have; `hbomax` and `premiersports` also exist |
| `OWNED_LABEL` | `Sky / TNT / terrestrial` | wording for "Not in your … package" |
| `BROADCAST_OVERRIDES` | — | per-fixture JSON, see [Broadcast](#broadcast) |
| `PREMCUP_POOL_GAMES` | `8` | |
| `ENABLE_CRESTS` | `1` | |
| `CREST_DITHER` | — | team names to dither rather than threshold |
| `CREST_THRESHOLD` | `0` | `0` = Otsu per crest; `1–254` fixed |
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
pip install -r requirements-dev.txt
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
- outage → last good → recovery, including a restart mid-outage
- all four broadcast states, overrides, rights expiry, and owned-channel filtering
- crests: polarity, pale crests, mid-tones, the oval mask, caching, fallback to initials, and route safety
- `full.liquid` rendered against every demo state, plus the `/demo` endpoints.
