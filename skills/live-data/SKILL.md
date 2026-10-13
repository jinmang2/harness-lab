---
name: live-data
description: Look up current real-world data (weather, exchange rates, time) from free public JSON APIs that need no API key. Use when a question depends on today's or live values.
---

# Live data lookup

Prefer a direct JSON API over searching web pages: it is faster, cheaper in tokens, and unambiguous.

| Need | Endpoint (GET, no key) |
|---|---|
| Current/hourly/daily weather | `https://api.open-meteo.com/v1/forecast?latitude=37.5665&longitude=126.9780&current=temperature_2m,weather_code,wind_speed_10m&daily=temperature_2m_max,temperature_2m_min,precipitation_sum&timezone=Asia%2FSeoul` |
| Past days of weather | add `&past_days=1` to the forecast URL |
| City coordinates | `https://geocoding-api.open-meteo.com/v1/search?name=Seoul&count=1` |
| Exchange rates | `https://open.er-api.com/v6/latest/USD` (`rates.KRW`, `time_last_update_utc`) |
| Current time in a zone | `date` in the shell with `TZ=Asia/Seoul` |

Steps:

1. Fetch once with `curl -s <url>` (or the `fetch_url` tool). Do not fetch the same URL twice.
2. Read only the fields you need (`python3 -c 'import json,sys; ...'` or `jq` if present).
3. In the answer, state the source URL and the timestamp the API reported.

WMO weather codes: 0 clear, 1-3 partly cloudy/overcast, 45/48 fog, 51-57 drizzle, 61-67 rain, 71-77 snow, 80-82 showers, 95-99 thunderstorm.
