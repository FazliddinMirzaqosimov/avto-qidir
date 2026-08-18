# 🔋 EV Hunter

A multi-user Telegram bot that watches **olx.uz, avtoelon.uz and avto.uz** and pushes new
car listings to every subscriber, filtered by the brands they picked.

Python standard library only — no third-party packages anywhere in the image.

---

## The Telegram bot

**For subscribers**

| Command | What it does |
|---|---|
| `/start` | registers you, asks for your phone number, shows the newest listings and the brand picker |
| `/brands` | pick which brands to follow — 113 of them, paginated, tap to toggle |
| `/latest` | the newest listings matching your brands |
| `/stop` | pause notifications (`/start` resumes) |
| `/help` | command list |

On `/start` the bot asks for the phone number with a `request_contact` button, so the
number comes from Telegram itself rather than being typed. Registration only completes
once it is shared.

Picking **no** brands means you get everything.

**For the admin**

Whenever someone registers, the admin chat receives a formatted card:

> 👤 **New user joined**
> **Name** Alice A · **Username** @alice
> **Phone** `+998901234567` · **ID** `111`
> **Language** en · **Premium** ⭐ yes
> **Joined** 2026-08-18 02:14 · **Status** ✅ active
>
> [ 🚫 Block ]

The **Block / Unblock** button flips that user's access and edits the card in place. A
blocked user receives no listings and is told their access is disabled. `/admin` prints
subscriber stats and the roster.

The admin id comes from `ADMIN_CHAT_ID` (falling back to `TELEGRAM_CHAT_ID`).

---

## Deploy on a server

```bash
ssh root@YOUR_SERVER
curl -fsSL https://raw.githubusercontent.com/FazliddinMirzaqosimov/avto-qidir/main/deploy.sh -o deploy.sh
bash deploy.sh
```

The first run creates `/opt/ev-hunter/.env` and stops. Fill it in:

```bash
nano /opt/ev-hunter/.env      # TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID
bash /opt/ev-hunter/deploy.sh # run it again — this time it starts
```

`deploy.sh` is idempotent: re-run it any time to pull the latest code and rebuild. It
installs Docker only if the host doesn't already have it, and touches nothing outside
`/opt/ev-hunter`, the `ev-hunter` container and the `ev-hunter-data` volume.

### Staying up

- `restart: unless-stopped` brings the container back after a crash, a `docker` daemon
  restart, or a host reboot.
- `deploy.sh` runs `systemctl enable docker`, so the daemon itself starts at boot.
- A `HEALTHCHECK` marks the container **unhealthy** if no scan has completed in three
  cycles — visible in `docker ps`.

### It cannot collide with your other projects

No published ports (the scanner only makes outbound requests), its own compose project
name, its own bridge network, its own named volume, `mem_limit: 512m`, and
`no-new-privileges`.

---

## Day-to-day

| Task | Command |
|---|---|
| Watch it work | `docker logs -f ev-hunter` |
| Is it running? | `docker ps --filter name=ev-hunter` |
| How many ads remembered | `docker exec ev-hunter python /app/ev_hunter.py --stats` |
| Test the Telegram link | `docker exec ev-hunter python /app/ev_hunter.py --test-telegram` |
| One scan, print only | `docker exec ev-hunter python /app/ev_hunter.py --dry-run` |
| Offline test suite | `docker exec ev-hunter python /app/selftest.py` |
| Stop | `cd /opt/ev-hunter && docker compose down` |
| Start | `cd /opt/ev-hunter && docker compose up -d` |
| Update | `bash /opt/ev-hunter/deploy.sh` |

---

## Configuration

Two places, and they do different jobs:

**`.env`** — secrets and the scan interval. Injected by compose, never committed.

| Key | Meaning |
|---|---|
| `TELEGRAM_BOT_TOKEN` | from @BotFather |
| `TELEGRAM_CHAT_ID` | your numeric chat id |
| `ADMIN_CHAT_ID` | who receives new-user cards and can block/unblock (defaults to `TELEGRAM_CHAT_ID`) |
| `EV_HUNTER_INTERVAL_MINUTES` | minutes between scans (default 60) |

**`/data/config.json`** inside the `ev-hunter-data` volume — the search rules. Seeded from
[`app/config.default.json`](app/config.default.json) on first start and never overwritten
after that, so your tuning survives every redeploy.

```bash
# edit the live config
docker run --rm -v ev-hunter-data:/data -it busybox vi /data/config.json
cd /opt/ev-hunter && docker compose restart
```

| Rule | Default |
|---|---|
| Powertrain | electric (BEV) or plug-in hybrid (DM-i / PHEV) |
| Price | ≤ **$17,000** (so'm converted at the live CBU rate) |
| Year | **2022** or newer |
| Mileage | < 50,000 km = top match · 50,000–100,000 km = "also worth a look" · above = dropped |
| Location | Tashkent city and region |
| Small EVs | **included** — BYD Seagull and similar city EVs are sent, not filtered out |
| `min_mileage_km` | **0** — "0 km" dealer/import ads are sent too |
| Excluded | Changan **Ben Ben / Benni / E-Star**, plus scooters, mopeds, bikes, quads, golf carts |

Two of these are deliberate reversals of the original behaviour, because the old settings
were silently swallowing cars:

- `seagull` used to sit in `exclude_keywords`, so every BYD Seagull on OLX was dropped
  before it could be sent. It is gone from the list.
- `min_mileage_km` used to be `1`, which discarded roughly **120 listings per scan** whose
  odometer read 0 — exactly the new-import EVs worth seeing. It is now `0` (check disabled).

### Sources

| Source | Default | Why |
|---|---|---|
| `olx` | ✅ on | the workhorse — ~1,900 listings a scan |
| `avtoelon` | ✅ on | ~50 listings a scan |
| `avtouz` | ✅ on | ~20 listings via schema.org JSON-LD |
| `avtobozor` | ❌ off | its TLS certificate doesn't match `www.avtobozor.uz` |
| `uzumavto` | ❌ off | no working public API endpoint found |
| `mashina` | ❌ off | serves the same catalogue as `avtouz` |

The three off by default produced **zero** results and only triggered daily "source is
quiet" warnings. Flip any of them back to `true` in `config.json` if they come back.

### Why the image needs `curl`

OLX sits behind a CloudFront WAF that now rejects **HTTP/1.1 outright** — every such
request comes back `403 Request blocked`. Measured from a Linux container:

| Transport | Result |
|---|---|
| `curl` over **HTTP/2** | **200** — 6/6, full result set |
| `curl` over HTTP/1.1 | 403 — 4/4 |
| Python `urllib` (HTTP/1.1 only) | 403 — 12/12 |

Python's standard library cannot speak HTTP/2 at all, so on Linux `urllib` alone gets
**nothing** from OLX — the source that supplies ~1,900 of the ~1,940 listings per scan.
`http_get()` therefore prefers `curl --http2` when the binary is present and falls back to
`urllib` otherwise; some hosts answer `urllib` but block `curl`, so both are tried before a
URL is called dead. This is the one reason `curl` is installed in the image.

---

## How it avoids repeats

Delivery is tracked **per user**, so two subscribers following the same brand each get the
ad exactly once:

1. **`listings`** is the shared catalogue — every ad that ever passed the filters.
2. **`user_sent`** records which subscriber received which listing.
3. A failed send is simply not recorded, so it is retried on the next cycle rather than lost.

Upgrading from the old single-chat version migrates the previous `seen` table into the
catalogue and marks it delivered to the admin, so nobody gets a flood of repeats.

Because the volume is separate from the code, `deploy.sh` can rebuild the image as often
as you like without the bot forgetting anything or re-sending old ads.

---

## Repository layout

```
app/
  ev_hunter.py          the scanner (single file, stdlib only)
  selftest.py           97 offline tests — filters, dedup, parsers, rendering
  analyze_debug.py      replays saved debug/ dumps and explains every rejection
  healthcheck.py        backs the container HEALTHCHECK
  entrypoint.sh         seeds /data/config.json, then execs the scanner
  config.default.json   seed config, no secrets
Dockerfile
docker-compose.yml
deploy.sh               server-side install / update
.env.example
```

---

## Running it locally

```bash
cd app
python ev_hunter.py --dry-run    # scan and print, send nothing, save nothing
python selftest.py               # offline tests
```

Without `EV_HUNTER_DATA_DIR` set, config, database and logs sit next to the code, exactly
as they did before containerisation.

---

## Troubleshooting

**Container is `unhealthy`** — no scan has completed in three cycles.
`docker logs --tail 100 ev-hunter` will show whether it's a Telegram failure or a source
crash. The loop survives crashes, so it will usually recover on its own.

**A site stops returning results** — marketplaces change their markup regularly. Run
`docker exec ev-hunter python /app/ev_hunter.py --diag`, then copy `/data/debug/` off the
volume; those raw responses are what's needed to repair that source's parser.

**Rotating the Telegram token** — edit `/opt/ev-hunter/.env`, then
`cd /opt/ev-hunter && docker compose up -d --force-recreate`.
