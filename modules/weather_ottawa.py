"""Ottawa weather: 24h temp+precip combo plot and 7d hi/lo, via Open-Meteo."""

from datetime import datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from . import _common as C

LAT = 45.4215
LON = -75.6972
TZ = "America/Toronto"

API = (
    "https://api.open-meteo.com/v1/forecast"
    f"?latitude={LAT}&longitude={LON}"
    "&hourly=temperature_2m,precipitation,wind_speed_10m,relative_humidity_2m"
    "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,"
    "sunrise,sunset,weather_code"
    f"&timezone={TZ}&past_days=1&forecast_days=7"
)


def _weather_code_text(code):
    table = {
        0: "Clear", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
        45: "Fog", 48: "Rime fog",
        51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
        61: "Light rain", 63: "Rain", 65: "Heavy rain",
        71: "Light snow", 73: "Snow", 75: "Heavy snow",
        77: "Snow grains",
        80: "Rain showers", 81: "Heavy showers", 82: "Violent showers",
        85: "Snow showers", 86: "Heavy snow showers",
        95: "Thunderstorm", 96: "T-storm w/ hail", 99: "Severe t-storm",
    }
    return table.get(int(code), f"code {code}")


@C.safe_section("weather_ottawa")
def render(printer):
    C.banner(printer, "Ottawa Weather")
    data = C.http_get(API, timeout=15).json()

    daily = data["daily"]
    today_idx = 1 if len(daily["time"]) > 1 else 0  # past_days=1 makes today index 1
    hi = daily["temperature_2m_max"][today_idx]
    lo = daily["temperature_2m_min"][today_idx]
    pop = daily["precipitation_sum"][today_idx]
    code_txt = _weather_code_text(daily["weather_code"][today_idx])
    sunrise = daily["sunrise"][today_idx].split("T")[1]
    sunset = daily["sunset"][today_idx].split("T")[1]

    printer.text(f"Today: {code_txt}\n")
    printer.text(f"  Hi {hi:.0f}C / Lo {lo:.0f}C  Precip {pop:.1f} mm\n")
    printer.text(f"  Sunrise {sunrise}  Sunset {sunset}\n\n")

    # 24-hour graph: temperature + precipitation
    hourly = data["hourly"]
    times = [datetime.fromisoformat(t) for t in hourly["time"]]
    now = datetime.now()
    # Take the next 24h starting from current hour
    start = next((i for i, t in enumerate(times) if t >= now.replace(minute=0, second=0, microsecond=0)), 0)
    end = min(start + 24, len(times))
    t24 = times[start:end]
    temp24 = hourly["temperature_2m"][start:end]
    pr24 = hourly["precipitation"][start:end]

    with plt.rc_context(C.MPL_STYLE):
        fig, ax1 = plt.subplots(figsize=(8, 3.0))
        ax1.plot(t24, temp24, color="black", marker="o", markersize=3,
                 label="Temp (C)")
        ax1.set_ylabel("Temp (C)")
        ax1.set_title("Next 24h")
        ax1.grid(True, axis="y", alpha=0.3)
        ax1.tick_params(axis="x", rotation=0)
        ax1.set_xticks(t24[::4])
        ax1.set_xticklabels([t.strftime("%Hh") for t in t24[::4]])

        ax2 = ax1.twinx()
        ax2.bar(t24, pr24, width=0.04, color="black", alpha=0.4,
                label="Precip (mm)")
        ax2.set_ylabel("Precip (mm)")
        ax2.spines["right"].set_visible(True)

        fig.tight_layout()
        img = C.fig_to_576_bitmap(fig)
        plt.close(fig)
    C.print_image(printer, img)
    printer.text("\n")

    # 7-day hi/lo plot
    days = [datetime.fromisoformat(d).strftime("%a") for d in daily["time"][today_idx:today_idx + 7]]
    his = daily["temperature_2m_max"][today_idx:today_idx + 7]
    los = daily["temperature_2m_min"][today_idx:today_idx + 7]

    with plt.rc_context(C.MPL_STYLE):
        fig, ax = plt.subplots(figsize=(8, 2.5))
        x = list(range(len(days)))
        ax.plot(x, his, color="black", marker="o", label="High")
        ax.plot(x, los, color="black", marker="s", linestyle="--", label="Low")
        ax.fill_between(x, los, his, color="black", alpha=0.1)
        ax.set_xticks(x)
        ax.set_xticklabels(days)
        ax.set_title("7-Day Hi / Lo (C)")
        ax.legend(loc="best")
        ax.grid(True, axis="y", alpha=0.3)
        fig.tight_layout()
        img = C.fig_to_576_bitmap(fig)
        plt.close(fig)
    C.print_image(printer, img)
    printer.text("\n")

    C.divider(printer)


if __name__ == "__main__":
    C.standalone_dummy_run(render, "weather_ottawa")
