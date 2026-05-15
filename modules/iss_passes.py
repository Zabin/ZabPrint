"""Next ISS passes over Ottawa from a Celestrak TLE + sgp4 propagation."""

from datetime import datetime, timedelta, timezone
import math

from sgp4.api import Satrec, jday

from . import _common as C

LAT = 45.4215
LON = -75.6972
ALT_KM = 0.07
TLE_URL = "https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=TLE"

EARTH_R = 6378.137  # km
MIN_ELEV_DEG = 10.0


def _ecef_from_geodetic(lat_deg, lon_deg, alt_km):
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    r = EARTH_R + alt_km
    return (r * math.cos(lat) * math.cos(lon),
            r * math.cos(lat) * math.sin(lon),
            r * math.sin(lat))


def _gmst(jd_ut1):
    T = (jd_ut1 - 2451545.0) / 36525.0
    g = (280.46061837
         + 360.98564736629 * (jd_ut1 - 2451545.0)
         + T * T * (0.000387933 - T / 38710000.0))
    return math.radians(g % 360.0)


def _eci_to_ecef(x, y, z, gmst):
    cg, sg = math.cos(gmst), math.sin(gmst)
    return (cg * x + sg * y, -sg * x + cg * y, z)


def _elevation(sat_eci, jd, lat, lon, alt):
    gmst = _gmst(jd)
    sx, sy, sz = _eci_to_ecef(*sat_eci, gmst)
    ox, oy, oz = _ecef_from_geodetic(lat, lon, alt)
    dx, dy, dz = sx - ox, sy - oy, sz - oz
    # Rotate to local ENU
    lat_r = math.radians(lat)
    lon_r = math.radians(lon)
    sl, cl = math.sin(lat_r), math.cos(lat_r)
    sn, cn = math.sin(lon_r), math.cos(lon_r)
    e = -sn * dx + cn * dy
    n = -sl * cn * dx - sl * sn * dy + cl * dz
    u = cl * cn * dx + cl * sn * dy + sl * dz
    rng = math.sqrt(e * e + n * n + u * u)
    if rng == 0:
        return -90.0, rng
    return math.degrees(math.asin(u / rng)), rng


@C.safe_section("iss_passes")
def render(printer):
    C.banner(printer, "ISS Passes (Ottawa)")
    tle_text = C.http_get(TLE_URL, timeout=10).text.strip().splitlines()
    lines = [ln for ln in tle_text if ln.strip()]
    if len(lines) < 2:
        raise ValueError("Unexpected TLE format from Celestrak")
    if lines[0].startswith("1 "):
        l1, l2 = lines[0], lines[1]
    else:
        l1, l2 = lines[1], lines[2]
    sat = Satrec.twoline2rv(l1, l2)

    start = datetime.now(timezone.utc)
    step = timedelta(seconds=30)
    horizon = start + timedelta(hours=24)

    passes = []
    in_pass = False
    pass_start = None
    pass_max = -90.0
    pass_max_time = None
    t = start
    prev_elev = None
    while t < horizon:
        jd, fr = jday(t.year, t.month, t.day, t.hour, t.minute,
                      t.second + t.microsecond / 1e6)
        e, r, v = sat.sgp4(jd, fr)
        if e:
            t += step
            continue
        elev, _ = _elevation(r, jd + fr, LAT, LON, ALT_KM)
        if not in_pass and elev >= MIN_ELEV_DEG:
            in_pass = True
            pass_start = t
            pass_max = elev
            pass_max_time = t
        elif in_pass:
            if elev > pass_max:
                pass_max = elev
                pass_max_time = t
            if elev < MIN_ELEV_DEG:
                passes.append((pass_start, t, pass_max, pass_max_time))
                in_pass = False
                if len(passes) >= 3:
                    break
        prev_elev = elev
        t += step

    if not passes:
        printer.text("No passes >10 deg in the next 24h.\n")
        C.divider(printer)
        return

    for start_t, end_t, peak, peak_t in passes:
        dur = (end_t - start_t).total_seconds() / 60.0
        printer.set(font="b", bold=True)
        printer.text(f"{start_t.strftime('%a %H:%MZ')}\n")
        printer.set(font="b", bold=False)
        printer.text(f"  duration {dur:.1f} min\n")
        printer.text(f"  peak {peak:.0f} deg at {peak_t.strftime('%H:%MZ')}\n\n")
    C.divider(printer)


if __name__ == "__main__":
    C.standalone_dummy_run(render, "iss_passes")
