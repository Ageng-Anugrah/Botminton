# Botminton

Discord bot for checking badminton court (GOR) availability from
[ayo.co.id](https://ayo.co.id) and for managing badminton event attendance and
payments.

## Features

- `/jadwal place:<GOR> date:<YYYY-MM-DD>` — shows merged available time slots for
  a venue and date.
- `/event create ...` — posts an event card with two side-by-side lists:
  **Attendance** and **Sudah Bayar**. The lists overlap: someone who has paid
  remains in **Attendance** and also appears in **Sudah Bayar**.
- Event card buttons:
  - **✅ Ikut** — add yourself to attendance.
  - **💰 Saya sudah bayar** — mark yourself as paid; you stay in attendance.
  - **➕ Tambah nama** — add someone else by free-text name (useful for friends
    outside the server).
  - **💸 Tandai lunas** — pick an attendance entry and mark them as paid. The
    card records who marked the payment; the person stays in attendance.
  - **↩️ Batalkan lunas** — clear a paid mark, leaving the person in attendance.
    Allowed for the user who marked it paid or the event creator.
  - **✏️ Edit** / **🗑️ Hapus** — creator-only event management.
- Payment trace: every paid entry shows `oleh @user`, and the person who made
  the change is stored in the data file.
- `/hello` — simple health check.
- Supports **Kukusan** and **Sima** venues for `/jadwal`.
- Async HTTP calls, request timeouts, and friendly error replies when the
  upstream service is unavailable.

## Requirements

- Python 3.11+
- A Discord bot token with the `applications.commands` and `bot` scopes

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill in `.env`:

| Variable | Required | Description |
| --- | --- | --- |
| `DISCORD_TOKEN` | yes | Bot token from the Discord Developer Portal |
| `GUILD_ID` | no | Server ID for instant slash-command sync while developing |
| `LOG_LEVEL` | no | `DEBUG`, `INFO` (default), `WARNING`, `ERROR`, `CRITICAL` |
| `EVENTS_FILE` | no | JSON data file, default `data/events.json` |
| `TIMEZONE` | no | Timezone for event times, default `Asia/Jakarta` |

If you set `GUILD_ID`, commands are synced to that server only. Leave it empty
to sync globally; global command propagation can take up to an hour.

## Run

```bash
python main.py
```

or:

```bash
python -m botminton
```

## Deploy with Docker

The repository includes a `Dockerfile` and a `docker-compose.yml` for running the
bot on a VPS. The image runs as an unprivileged user (UID 10001), and event data
is kept in the named volume `botminton-data` at `/app/data`, so rebuilding the
container does not lose events.

On the server:

```bash
git clone git@github.com:Ageng-Anugrah/Botminton.git
cd Botminton
cp .env.example .env
# edit .env and set at least DISCORD_TOKEN
docker compose up -d --build
```

Useful commands:

```bash
docker compose logs -f          # follow logs
docker compose restart          # restart the bot
docker compose down             # stop (the data volume is kept)
docker compose up -d --build    # rebuild and restart after a git pull
```

The Compose file sets `EVENTS_FILE=/app/data/events.json`, so data always lands in
the volume even if `.env` leaves it empty. To back up or copy existing data from a
local run, copy your `data/events.json` into the volume:

```bash
docker compose cp data/events.json botminton:/app/data/events.json
```

Without Compose:

```bash
docker build -t botminton .
docker run -d --name botminton --restart unless-stopped \
  --env-file .env \
  -e EVENTS_FILE=/app/data/events.json \
  -v botminton-data:/app/data \
  botminton
```

## Event attendance and payments

Create an event in a server channel:

```text
/event create judul:"Petojo Berbulu 7 Nov 2026" tempat:"Petojo Arena" lapangan:"Lap 2" tanggal:2026-11-07 mulai:17:00 selesai:19:00 harga:40000 peta:"https://maps.app.goo.gl/..." catatan:"Newbie friendly"
```

The bot posts a card with the event details and the two lists. **Attendance**
lists everyone who signed up, while **Sudah Bayar** is the subset who has paid;
a name can appear in both columns. Anyone can use the attendance and payment
buttons. Only the event creator can edit or delete the event, and only the
person who marked a payment (or the event creator) can undo it.

Data is stored in the JSON file configured by `EVENTS_FILE`. Writes are atomic
and serialized per bot process. The storage layer is kept behind a small
repository (`EventStore`) so it can be replaced by a database later.

## Project structure

```
main.py                        # compatibility entrypoint
Dockerfile                     # container image
docker-compose.yml             # VPS deployment with a data volume
.env.example                   # environment template
botminton/
├── main.py                    # loads settings, starts the bot
├── bot.py                     # BotmintonBot: session, store, command sync
├── config.py                  # environment parsing and validation
├── errors.py                  # typed errors
├── logging_setup.py           # logging configuration
├── models.py                  # Event and Participant domain models
├── venues.py                  # venue registry (key, label, ayo.co.id ID)
├── cogs/
│   ├── event.py               # /event create and the interactive event card
│   └── schedule.py            # /jadwal and /hello
└── services/
    ├── attendance.py          # attendance/payment rules and card rendering
    ├── ayo.py                 # async ayo.co.id client and payload parsing
    ├── availability.py        # time-slot parsing, merging, and rendering
    └── event_store.py         # JSON persistence for events
```

To add a venue, add an entry to `VENUES` in `botminton/venues.py`; the slash
command choices and API lookup update automatically.
