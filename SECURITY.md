# Security & privacy

This project is a **Home Assistant custom integration**. There is no server operated by
the maintainers and no telemetry phoning home. Everything below describes what the
integration does on _your_ Home Assistant instance.

## What data the integration touches

| Data                                 | Stored                             | Leaves your machine?                                                           |
| ------------------------------------ | ---------------------------------- | ------------------------------------------------------------------------------ |
| CarLinko email + password            | Home Assistant config entry        | Only to **CarLinko's own cloud** over HTTPS, to log in — like the official app |
| Auth token                           | HA storage (`CarlinkoStore`)       | To CarLinko's cloud: HTTPS on each request, **unencrypted** on the live stream |
| Live telemetry                       | In-memory (coordinator / entities) | No (unless you log or export it yourself)                                      |
| Cost knobs (tariff, petrol price, …) | HA storage                         | No                                                                             |

**Optional `engine/` CLI** (dev / debugging only): email/password/region in a gitignored
`.env`; token and vehicle ids via the same `CarlinkoStore` class, file-backed to
`data/config.json` (also gitignored). Same outbound destinations as the integration.

**No analytics, no tracking, no third-party backend.** Outbound traffic is to CarLinko's
cloud only (WebSocket + REST for login and remote control).

## The live stream is not encrypted

REST calls (login, vehicle list, remote control, charge limit, charge schedule) go over HTTPS. The live
status stream does not have to: CarLinko's cloud hands out the stream address (the
official app asks for it the same way), and the address documented for this project is
plain `ws://…:4002`. The built-in fallback address is also `ws://`.

When the stream address is `ws://`:

- The **auth token** is sent unencrypted in the stream's login message every time the
  stream connects.
- **Live telemetry** (battery, doors, lock state, speed, odometer) is sent unencrypted.
- Anyone on the network path between Home Assistant and CarLinko's cloud can read both.
  A captured token is enough to send remote-control commands for as long as that token
  stays valid, because the request signing key is public (see below).

The integration follows the scheme CarLinko returns: an `https://` stream address is
connected as `wss://`. It does not try to upgrade a `ws://` address; no encrypted
stream endpoint is known. Your password is never sent on the stream, and location is
fetched by a separate HTTPS call rather than from the stream.

This cannot be fixed from Home Assistant's side. Running Home Assistant on a network
you trust removes local eavesdroppers; the path across the internet to CarLinko stays
exposed.

## Your responsibilities

- **Never commit** `.env`, `config.json`, tokens, passwords, VIN, or plate.
- Prefer a **second CarLinko account** when possible so a shared session isn’t tied to
  your primary phone login (CarLinko often allows only one active session).
- With one shared account, the phone app and Home Assistant can log each other out:
  a new login can end the other session, and the integration logs in again when its
  token is rejected.
- Remote control is **real actuation** — use only on a vehicle you own.
- **Charge limit** is a saved cloud setting, not a live command, but it changes how far
  your car charges. Check the value in the CarLinko app after the first change.

## How auth works (for the curious)

- The CarLinko request signing key is an **app-global constant** (identical in every
  install of the official app), so bundling it exposes nothing your own APK doesn't
  already contain.

## Reporting a vulnerability

Found something? **Please report it privately first** — don't open a public issue with
exploit details. Use
[GitHub private vulnerability reporting](https://github.com/elad-bar/ha-carlinko/security/advisories/new)
(Security tab → _Report a vulnerability_).

This is a hobby project with no warranty — see [LICENSE](LICENSE).
