# sauce.ai / news

A user-customizable news aggregator. RSS-driven, MySQL-backed, Flask-served.

This is the **v1 prototype**. It runs on shared cPanel hosting (GoDaddy Web
Hosting Plus). For install instructions see `INSTALL.txt`.

## What it does

- Polls ~135 curated RSS feeds every 15 minutes (rotates so all feeds are hit
  every ~1-2 hours).
- Classifies each article on ten features: political lean, source lean,
  objectivity, reading level, info density, journalist reputation, source
  reputation, category, geography, popularity.
  - Cheap features run as Python rules (Flesch-Kincaid, entity/number density,
    source lookup table).
  - Two judgment features (`political_lean` of the article itself,
    `objectivity`) run via batched Claude Haiku 4.5 calls. If no API key is
    configured, those degrade to source-level defaults.
- Polls Reddit and Hacker News every 30 minutes to estimate `popularity` for
  articles whose URLs are circulating externally.
- Ranks articles per-user via a weighted SQL expression built from the user's
  algorithm (no per-article Python at request time).

## Pages

| Path             | Purpose                                                  |
| ---------------- | -------------------------------------------------------- |
| `/`              | Card grid feed, sorted by your algorithm                 |
| `/firehose`      | Live table of every classified article, newest first     |
| `/algo`          | UI / Code / Presets tabs to edit your algorithm          |
| `/auth/signup`   | Email + password signup                                  |
| `/auth/login`    | Sign in                                                  |
| `/admin/*`       | Admin pages (requires `is_admin = 1`)                    |

## Stack

- Flask 3 served by cPanel Passenger
- Jinja2 templates + HTMX + Alpine (no build step)
- MySQL via PyMySQL
- Anthropic Python SDK
- Cron-driven workers (no Redis, no Celery)

## Project layout

```
news/
├── passenger_wsgi.py        # cPanel entry
├── requirements.txt
├── app/
│   ├── __init__.py          # Flask factory (lazy import)
│   ├── config.py
│   ├── db.py
│   ├── auth.py
│   ├── ranking.py           # weight -> SQL expression
│   ├── classifier/
│   │   ├── rules.py
│   │   ├── schema.py
│   │   └── llm.py
│   ├── routes/              # feed, algo, firehose, admin, auth
│   ├── templates/
│   └── static/
├── jobs/                    # cron scripts
│   ├── fetch_feeds.py
│   ├── classify_pending.py
│   ├── popularity_poll.py
│   └── maintenance.py
├── seed/
│   ├── schema.sql
│   ├── feature_catalog.sql
│   └── source_lean.csv      # curated starter feed list
├── tests/                   # pytest suite, runnable from /admin/tests
├── INSTALL.txt
└── README.md
```

## Running tests

```
$ python -m pytest tests/ -q
```

Or from the admin UI: `/admin/tests` -> "Run tests".
