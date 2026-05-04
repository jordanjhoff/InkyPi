import logging
import os
import io
import json
import base64
import random
from datetime import datetime, timedelta, date

import pytz
import requests
import icalendar
import recurring_ical_events
from PIL import Image, ImageColor, ImageOps

from plugins.base_plugin.base_plugin import BasePlugin
from utils.app_utils import resolve_path

_sprite_cache = {}  # {filepath: [(col, row), ...]}

logger = logging.getLogger(__name__)

OPEN_METEO_URL = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude={lat}&longitude={lon}"
    "&current=temperature_2m,apparent_temperature,weather_code,is_day,relative_humidity_2m"
    "&hourly=precipitation_probability"
    "&temperature_unit=fahrenheit&forecast_days=1"
)

WMO_DESCRIPTIONS = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy", 48: "Icy fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
    56: "Light freezing drizzle", 57: "Freezing drizzle",
    61: "Slight rain", 63: "Rain", 65: "Heavy rain",
    66: "Light freezing rain", 67: "Freezing rain",
    71: "Slight snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Slight showers", 81: "Showers", 82: "Violent showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm w/ hail", 99: "Thunderstorm w/ heavy hail",
}


class CustomCalendar(BasePlugin):

    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params['style_settings'] = True
        return template_params

    def generate_image(self, settings, device_config):
        dimensions = device_config.get_resolution()
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]

        timezone = device_config.get_config("timezone", default="America/New_York")
        tz = pytz.timezone(timezone)
        now = datetime.now(tz)

        weather = self.fetch_weather(settings, now)

        time_mode = settings.get("timeMode", "fixed")
        now_half = now.hour + (now.minute // 15) * 0.25

        if time_mode == "rolling":
            hours_display = max(4, min(24, int(settings.get("hoursDisplay") or 16)))
            start_hour = max(0, int(now_half) - hours_display // 2)
            end_hour = start_hour + hours_display
            if end_hour > 24:
                end_hour = 24
                start_hour = max(0, 24 - hours_display)
        else:
            start_hour = max(0, min(23, int(settings.get("startHour") or 6)))
            end_hour = max(start_hour + 1, min(24, int(settings.get("endHour") or 22)))

        days = self.build_days(settings, now, tz)

        cat_sprite = self.get_cat_sprite_b64(settings)

        template_params = {
            "day_name": now.strftime("%A"),
            "full_date": now.strftime("%B %-d, %Y"),
            "weather": weather,
            "cat_sprite": cat_sprite,
            "days": days,
            "start_hour": start_hour,
            "end_hour": end_hour,
            "total_hours": end_hour - start_hour,
            "now_hour": now_half,
            "today_iso": now.date().isoformat(),
            "plugin_settings": settings,
        }

        image = self.render_image(dimensions, "custom_calendar.html", "custom_calendar.css", template_params)
        if not image:
            raise RuntimeError("Failed to render custom calendar.")
        return image

    def fetch_weather(self, settings, now):
        lat = settings.get("latitude", "").strip()
        lon = settings.get("longitude", "").strip()
        if not lat or not lon:
            return None
        try:
            resp = requests.get(OPEN_METEO_URL.format(lat=lat, lon=lon), timeout=15)
            resp.raise_for_status()
            data = resp.json()
            current = data.get("current", {})
            weather_code = current.get("weather_code", 0)
            is_day = current.get("is_day", 1)
            icon_name = self._weather_code_to_icon(weather_code, is_day)
            icon_path = os.path.join(resolve_path("plugins"), "weather", "icons", f"{icon_name}.png")

            hourly = data.get("hourly", {})
            times = hourly.get("time", [])
            probs = hourly.get("precipitation_probability", [])
            rain_hours = []
            for t, p in zip(times, probs):
                hour = int(t.split("T")[1].split(":")[0])
                if hour >= now.hour and len(rain_hours) < 8:
                    rain_hours.append({"label": self._fmt_hour(hour), "pct": p or 0})

            return {
                "temp_f": round(current.get("temperature_2m", 0)),
                "feels_like_f": round(current.get("apparent_temperature", 0)),
                "humidity": round(current.get("relative_humidity_2m", 0)),
                "condition_text": WMO_DESCRIPTIONS.get(weather_code, ""),
                "icon_path": icon_path,
                "rain_hours": rain_hours,
            }
        except Exception as e:
            logger.error(f"OpenMeteo weather request failed: {e}")
            return None

    def _fmt_hour(self, hour):
        if hour == 0:    return "12am"
        elif hour < 12:  return f"{hour}am"
        elif hour == 12: return "12pm"
        else:            return f"{hour - 12}pm"

    def _weather_code_to_icon(self, code, is_day):
        if code == 0:             icon = "01d"
        elif code == 1:           icon = "022d"
        elif code == 2:           icon = "02d"
        elif code == 3:           icon = "04d"
        elif code in (51,61,80):  icon = "51d"
        elif code in (53,63,81):  icon = "53d"
        elif code in (55,65,82):  icon = "09d"
        elif code == 45:          icon = "50d"
        elif code == 48:          icon = "48d"
        elif code in (56,66):     icon = "56d"
        elif code in (57,67):     icon = "57d"
        elif code in (71,85):     icon = "71d"
        elif code == 73:          icon = "73d"
        elif code in (75,86):     icon = "13d"
        elif code == 77:          icon = "77d"
        elif code in (95,96,99):  icon = "11d"
        else:                     icon = "01d"

        if is_day == 0:
            if icon == "01d":   icon = "01n"
            elif icon == "022d": icon = "022n"
            elif icon == "02d": icon = "02n"
        return icon

    def build_days(self, settings, now, tz):
        today = now.date()
        start_dt = tz.localize(datetime(today.year, today.month, today.day))
        end_dt = start_dt + timedelta(days=5)

        calendar_urls = settings.get("calendarURLs[]") or []
        calendar_colors = settings.get("calendarColors[]") or []
        if isinstance(calendar_urls, str):
            calendar_urls = [calendar_urls]
        if isinstance(calendar_colors, str):
            calendar_colors = [calendar_colors]

        urls_and_colors = [
            (url.strip(), color)
            for url, color in zip(calendar_urls, calendar_colors)
            if url.strip()
        ]

        all_events = self.fetch_all_events(urls_and_colors, tz, start_dt, end_dt)

        days = []
        for offset in range(5):
            day_date = today + timedelta(days=offset)
            day_start = tz.localize(datetime(day_date.year, day_date.month, day_date.day))
            day_end = day_start + timedelta(days=1)

            all_day_events = []
            timed_events = []

            for ev in all_events:
                if ev["all_day"]:
                    ev_start = date.fromisoformat(ev["start_date"])
                    ev_end = date.fromisoformat(ev["end_date"]) if ev["end_date"] else ev_start + timedelta(days=1)
                    if ev_start <= day_date < ev_end:
                        all_day_events.append(ev)
                else:
                    ev_start_dt = datetime.fromisoformat(ev["start_iso"])
                    ev_end_dt = (
                        datetime.fromisoformat(ev["end_iso"])
                        if ev["end_iso"]
                        else ev_start_dt + timedelta(hours=1)
                    )
                    if ev_start_dt < day_end and ev_end_dt > day_start:
                        clipped_start = max(ev_start_dt, day_start)
                        clipped_end = min(ev_end_dt, day_end)
                        if clipped_end <= clipped_start:
                            continue
                        start_frac = clipped_start.hour + clipped_start.minute / 60.0
                        end_frac = clipped_end.hour + clipped_end.minute / 60.0
                        timed_events.append({
                            **ev,
                            "start_frac": start_frac,
                            "end_frac": end_frac,
                            "start_label": clipped_start.strftime("%-I:%M %p"),
                            "end_label": clipped_end.strftime("%-I:%M %p"),
                        })

            days.append({
                "date_iso": day_date.isoformat(),
                "is_today": day_date == today,
                "header": day_date.strftime("%a %-m/%-d"),
                "all_day_events": all_day_events,
                "timed_events": timed_events,
            })

        return days

    def fetch_all_events(self, urls_and_colors, tz, start_dt, end_dt):
        events = []
        for url, color in urls_and_colors:
            try:
                cal = self.fetch_calendar(url)
                raw_events = recurring_ical_events.of(cal).between(start_dt, end_dt)
                text_color = self.get_contrast_color(color)
                for ev in raw_events:
                    parsed = self.parse_event(ev, tz, color, text_color)
                    if parsed:
                        events.append(parsed)
            except Exception as e:
                logger.error(f"Failed to fetch/parse calendar {url}: {e}")
        return events

    def parse_event(self, event, tz, color, text_color):
        try:
            title = str(event.get("summary", "Untitled"))
            dtstart = event.decoded("dtstart")
            if isinstance(dtstart, datetime):
                dtstart_aware = dtstart.astimezone(tz)
                end_iso = None
                if "dtend" in event:
                    end_iso = event.decoded("dtend").astimezone(tz).isoformat()
                elif "duration" in event:
                    end_iso = (dtstart + event.decoded("duration")).astimezone(tz).isoformat()
                return {
                    "title": title,
                    "all_day": False,
                    "start_iso": dtstart_aware.isoformat(),
                    "end_iso": end_iso,
                    "start_date": None,
                    "end_date": None,
                    "color": color,
                    "text_color": text_color,
                }
            else:
                end_date = None
                if "dtend" in event:
                    dtend = event.decoded("dtend")
                    end_date = dtend.isoformat() if hasattr(dtend, "isoformat") else str(dtend)
                return {
                    "title": title,
                    "all_day": True,
                    "start_iso": None,
                    "end_iso": None,
                    "start_date": dtstart.isoformat(),
                    "end_date": end_date,
                    "color": color,
                    "text_color": text_color,
                }
        except Exception as e:
            logger.warning(f"Failed to parse event: {e}")
            return None

    def fetch_calendar(self, url):
        if url.startswith("webcal://"):
            url = url.replace("webcal://", "https://")
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return icalendar.Calendar.from_ical(response.text)

    # (x, y, type) — type is "furniture" or "floor"
    _POSITIONS = [
        (250, 215, "furniture"),  # in the bed
        (75,  215, "furniture"),  # on top of shelf
        (410, 225, "furniture"),  # on top of cat tree
        (210, 260, "floor"),
        (270, 275, "floor"),
        (195, 310, "floor"),
        (250, 328, "floor"),
        (315, 300, "floor"),
        (150, 345, "floor"),
        (345, 352, "floor"),
    ]

    _SLEEP_ROWS = {2, 6}
    _BOX_ROWS   = {9, 10, 11}
    _ANY_ROWS   = {0, 1, 3, 4, 5, 7, 8, 12, 14, 15, 16, 17}

    def _catalog_sprites(self, sheet_path):
        if sheet_path not in _sprite_cache:
            sheet = Image.open(sheet_path).convert("RGBA")
            cols = sheet.width // 32
            rows = sheet.height // 32
            valid_by_row = {}
            for row in range(rows):
                for col in range(cols):
                    tile = sheet.crop((col*32, row*32, col*32+32, row*32+32))
                    non_white = sum(
                        1 for r, g, b, a in tile.getdata()
                        if a > 30 and (r < 230 or g < 230 or b < 230)
                    )
                    if non_white > 30:
                        valid_by_row.setdefault(row, []).append(col)
            _sprite_cache[sheet_path] = (sheet, valid_by_row)
        return _sprite_cache[sheet_path]

    def _pick_sprite(self, sheet_path, state_path, pos_type, allow_box=True):
        sheet, valid_by_row = self._catalog_sprites(sheet_path)

        if pos_type == "furniture":
            allowed = self._SLEEP_ROWS | self._ANY_ROWS
        elif allow_box:
            allowed = self._BOX_ROWS | self._ANY_ROWS
        else:
            allowed = self._ANY_ROWS

        valid_rows = [r for r in valid_by_row if r in allowed]
        if not valid_rows:
            valid_rows = list(valid_by_row.keys())

        last_row = None
        if os.path.exists(state_path):
            try:
                with open(state_path) as f:
                    last_row = json.load(f).get("row")
            except Exception:
                pass

        candidates = [r for r in valid_rows if r != last_row] or valid_rows
        chosen_row = random.choice(candidates)
        chosen_col = random.choice(valid_by_row[chosen_row])

        with open(state_path, "w") as f:
            json.dump({"row": chosen_row}, f)

        sprite = sheet.crop((chosen_col*32, chosen_row*32, chosen_col*32+32, chosen_row*32+32))
        if random.random() < 0.5:
            sprite = ImageOps.mirror(sprite)
        return sprite

    def _remove_background(self, img, tolerance=40):
        bg = img.getpixel((0, 0))[:3]
        data = list(img.getdata())
        img.putdata([
            (r, g, b, 0)
            if abs(r-bg[0]) <= tolerance and abs(g-bg[1]) <= tolerance and abs(b-bg[2]) <= tolerance
            else (r, g, b, a)
            for r, g, b, a in data
        ])
        return img

    _IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}

    def _get_album_image_b64(self, folder):
        images = sorted(
            f for f in os.listdir(folder)
            if os.path.splitext(f)[1].lower() in self._IMAGE_EXTS
        )
        if not images:
            return None
        state_path = os.path.join(folder, ".album_state.json")
        index = 0
        if os.path.exists(state_path):
            try:
                with open(state_path) as f:
                    index = json.load(f).get("index", 0)
            except Exception:
                pass
        index = index % len(images)
        with open(state_path, "w") as f:
            json.dump({"index": (index + 1) % len(images)}, f)
        img = Image.open(os.path.join(folder, images[index])).convert("RGBA")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

    def get_cat_sprite_b64(self, settings):
        asset_dir = os.path.join(os.path.dirname(__file__), "assets")
        cat_mode  = settings.get("catMode", "sprite")
        room_path = os.path.join(asset_dir, "cat_room.png")

        try:
            if cat_mode == "album":
                folder = settings.get("albumPath", "").strip()
                if not folder or not os.path.isdir(folder):
                    return None
                return self._get_album_image_b64(folder)
            elif cat_mode == "room" and os.path.exists(room_path):
                room = Image.open(room_path).convert("RGBA")
                room = self._remove_background(room)
                cat_size = 48
                positions = random.sample(self._POSITIONS, min(3, len(self._POSITIONS)))
                box_used = False
                for (x, y, pos_type), color in zip(positions, ["white", "grey", "orange"]):
                    sheet_path = os.path.join(asset_dir, f"cat_{color}.png")
                    state_path = os.path.join(asset_dir, f"cat_state_{color}.json")
                    if not os.path.exists(sheet_path):
                        continue
                    sprite = self._pick_sprite(sheet_path, state_path, pos_type, allow_box=not box_used)
                    with open(state_path) as f:
                        chosen_row = json.load(f).get("row")
                    if chosen_row in self._BOX_ROWS:
                        box_used = True
                    sprite_scaled = sprite.resize((cat_size, cat_size), Image.NEAREST)
                    room.paste(sprite_scaled, (x - cat_size // 2, y - cat_size), sprite_scaled)
                render_w = 650
                render_h = int(room.height * render_w / room.width)
                result = room.resize((render_w, render_h), Image.LANCZOS)
            else:
                color = settings.get("catColor", "none")
                if color == "none":
                    return None
                sheet_path = os.path.join(asset_dir, f"cat_{color}.png")
                state_path = os.path.join(asset_dir, f"cat_state_{color}.json")
                if not os.path.exists(sheet_path):
                    return None
                sprite = self._pick_sprite(sheet_path, state_path, "floor")
                result = sprite.resize((64, 64), Image.NEAREST)

            buf = io.BytesIO()
            result.save(buf, format="PNG")
            return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
        except Exception as e:
            logger.warning(f"Failed to load cat sprite: {e}")
            return None

    def get_contrast_color(self, color):
        r, g, b = ImageColor.getrgb(color)
        yiq = (r * 299 + g * 587 + b * 114) / 1000
        return "#000000" if yiq >= 150 else "#ffffff"
