# CLAUDE.md

Working notes for this repository.

## Announcing changes to Telegram

Two audiences, and they must not be mixed up.

| Change | Who hears about it | How |
|---|---|---|
| **New feature** users can act on | **everyone** | `broadcast.py --key <name> --send` |
| **Bug fix**, correction, wording change, internal work | **admin only** | `broadcast.py --key <name> --admin --send` |

**Never broadcast a bug fix to all subscribers.** People do not want a message
every time something they never noticed was repaired — it reads as noise and
costs goodwill. The admin (`ADMIN_CHAT_ID`, already configured) gets those.

A change counts as a **new feature** only if a subscriber has to *do* something
new because of it — a new command, a new filter, a new button. If the bot simply
behaves correctly where it previously misbehaved, that is a **fix**, admin only.

Borderline cases go to the admin. It is easy to follow a quiet fix with a louder
announcement later; an unwanted broadcast cannot be taken back.

### Sending

```bash
# admin only - bug fixes
docker exec ev-hunter python /app/broadcast.py --key fix_note --admin --send

# everyone - new features
docker exec ev-hunter python /app/broadcast.py --key announce_filters --send
```

Both default to a dry run; `--send` is what actually delivers. Message bodies live
in `bot.T` in `app/bot.py`, in Uzbek Cyrillic, so they can be reviewed before they go out.

## Language

Every subscriber-facing string is **Uzbek Cyrillic** and lives in the `T` table in
`app/bot.py`. A test in `bottest.py` walks that table and fails the build if any
string is still Latin, so untranslated text cannot reach users. Proper nouns
(brand names, `/commands`) are allowlisted.

## Deploying

```bash
bash /opt/ev-hunter/deploy.sh      # on the server, idempotent
```

Pulls `main`, rebuilds, runs both suites inside the image, restarts. It only ever
touches `/opt/ev-hunter`, the `ev-hunter` container and the `ev-hunter-data`
volume — the host runs several unrelated projects that must not be disturbed.

`/data/config.json` is seeded once and **never overwritten**, so changing a default
in `app/config.default.json` does not change the live config. Patch the live file
explicitly when a default needs to move.

## Testing

```bash
python app/selftest.py    # scanner: parsers, filters, dedup, rendering
python app/bottest.py     # bot: registration, subscriptions, buckets, keyboards
```

Both must pass in the container before deploying. Verify filters against the real
catalogue on the server too — unit tests use fixtures, and the bugs that have
actually shipped here came from live data, not from fixtures.

## Filters

`app/carfilters.py` is the single definition of the mileage and year buckets. The
SQL filter, the Telegram pickers and the message grouping all read it, so a listing
cannot be grouped under one heading and filtered by another. Bucket keys are
interpolated into SQL, so they are validated against that whitelist on write.

Subscriber filters are all **opt-in**: an empty selection means "everything". Any
new filter must keep that property, or existing subscribers silently stop receiving
listings when it ships.
