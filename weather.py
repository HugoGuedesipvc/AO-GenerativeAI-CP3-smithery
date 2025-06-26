from typing import Any
import httpx
import uvicorn
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP server
mcp = FastMCP("weather")

IPMA_BASE_URL = "https://api.ipma.pt/open-data"
USER_AGENT = "weather-app/1.0"

async def make_ipma_request(endpoint: str) -> dict[str, Any] | None:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json"
    }
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{IPMA_BASE_URL}/{endpoint}", headers=headers, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except Exception:
            return None

async def get_city_id(city_name: str) -> int | None:
    """Find the globalIdLocal for a given city name."""
    data = await make_ipma_request("distrits-islands.json")
    if not data:
        return None

    for entry in data.get("data", []):
        if entry["local"].lower() == city_name.lower():
            return entry["globalIdLocal"]
    return None

def wind_direction_description(direction: str) -> str:
    """Translate wind direction abbreviation to full description."""
    directions = {
        "N": "North",
        "NE": "Northeast",
        "E": "East",
        "SE": "Southeast",
        "S": "South",
        "SW": "Southwest",
        "W": "West",
        "NW": "Northwest",
        "Variable": "Variable"
    }
    return directions.get(direction.upper(), direction)

@mcp.tool()
async def get_forecast(city: str) -> str:
    """Get 5-day weather forecast for a Portuguese city.

    Args:
        city: Name of the city (e.g. Lisboa, Porto, Faro)
    """
    city_id = await get_city_id(city)
    if city_id is None:
        return f"Could not find weather data for '{city}'."

    forecast_data = await make_ipma_request(f"forecast/meteorology/cities/daily/{city_id}.json")
    if not forecast_data:
        return f"Could not retrieve forecast for '{city}'."

    forecasts = []
    for day in forecast_data["data"][:5]:  # Limit to next 5 days
        forecast = f"""
    Date: {day['forecastDate']}
    Min Temp: {day['tMin']}ºC
    Max Temp: {day['tMax']}ºC
    Precipitation Probability: {day['precipitaProb']}%
    Wind Direction: {wind_direction_description(day['predWindDir'])}
    """
        forecasts.append(forecast)

    return "\n---\n".join(forecasts)


@mcp.tool()
async def weather_warnings() -> str:
    """
    Retrieve and format weather warnings from IPMA for Portugal up to 3 days ahead.

    Returns:
        A formatted string summarizing current weather warnings, with details by area and level.
    """
    data = await make_ipma_request(f"forecast/warnings/warnings_www.json")

    if not data:
        return "No weather warnings data available."

    # Mapping awareness levels to descriptive names
    level_names = {
        "green": "No Warning",
        "yellow": "Yellow Warning",
        "orange": "Orange Warning",
        "red": "Red Warning"
    }

    # Group warnings by area
    warnings_by_area = {}
    for warning in data:
        area = warning.get("idAreaAviso", "Unknown")
        level = warning.get("awarenessLevelID", "green")
        param = warning.get("awarenessTypeName", "Undefined")
        start = warning.get("startTime", "no start")
        end = warning.get("endTime", "no end")
        text = warning.get("text", "").strip()

        # Ignore green level warnings
        if level == "green":
            continue

        if area not in warnings_by_area:
            warnings_by_area[area] = []

        warnings_by_area[area].append({
            "level": level_names.get(level, level),
            "parameter": param,
            "start": start,
            "end": end,
            "description": text or "(no additional description)"
        })

    if not warnings_by_area:
        return "There are no active weather warnings for the next 3 days."

    # Format output
    lines = ["Active Weather Warnings:"]
    for area, warnings in warnings_by_area.items():
        lines.append(f"\nArea: {area}")
        for w in warnings:
            lines.append(f" - {w['parameter']} | Level: {w['level']}")
            lines.append(f"   Start: {w['start']}  End: {w['end']}")
            lines.append(f"   Details: {w['description']}")

    return "\n".join(lines)

@mcp.tool()
async def get_sea_forecast(day: int = 0) -> str:
    """
    Get daily sea state forecast for Portugal coastal areas.

    Args:
        day: 0 = today, 1 = tomorrow, 2 = day after tomorrow

    Returns:
        Formatted string with forecast info by location.
    """
    if day not in [0, 1, 2]:
        return "Invalid day. Use 0 (today), 1 (tomorrow), or 2 (day after tomorrow)."

    data = await make_ipma_request(f"forecast/oceanography/daily/hp-daily-sea-forecast-day{day}.json")

    if not data or "data" not in data or len(data["data"]) == 0:
        return "No sea forecast data available."

    forecast_date = data.get("forecastDate", "Unknown date")
    results = [f"Sea state forecast for {forecast_date}:\n"]

    for loc in data["data"]:
        loc_id = loc.get("globalIdLocal", "Unknown")
        lat = loc.get("latitude", "Unknown")
        lon = loc.get("longitude", "Unknown")

        wave_high_min = loc.get("waveHighMin", "N/A")
        wave_high_max = loc.get("waveHighMax", "N/A")
        wave_period_min = loc.get("wavePeriodMin", "N/A")
        wave_period_max = loc.get("wavePeriodMax", "N/A")
        pred_wave_dir = loc.get("predWaveDir", "N/A")
        total_sea_min = loc.get("totalSeaMin", "N/A")
        total_sea_max = loc.get("totalSeaMax", "N/A")
        sst_min = loc.get("sstMin", "N/A")
        sst_max = loc.get("sstMax", "N/A")

        results.append(
            f"Location ID: {loc_id}\n"
            f"Coordinates: {lat}, {lon}\n"
            f"Wave height (swell) min/max (m): {wave_high_min} / {wave_high_max}\n"
            f"Wave period (swell) min/max (s): {wave_period_min} / {wave_period_max}\n"
            f"Predominant wave direction: {pred_wave_dir}\n"
            f"Total sea height min/max (m): {total_sea_min} / {total_sea_max}\n"
            f"Sea surface temperature min/max (°C): {sst_min} / {sst_max}\n"
            "-----------------------------------"
        )

    return "\n".join(results)


@mcp.tool()
async def get_earthquakes(area: int = 7) -> str:
    """
    Get earthquake information for Portugal areas (Azores or Mainland + Madeira).

    Args:
        area: 3 for Azores, 7 for Mainland + Madeira

    Returns:
        Formatted string with recent earthquakes (last 30 days).
    """
    if area not in [3, 7]:
        return "Invalid area. Use 3 for Azores or 7 for Mainland + Madeira."

    data = await make_ipma_request(f"observation/seismic/{area}.json")

    if not data or "data" not in data or len(data["data"]) == 0:
        return "No earthquake data available."

    result_lines = []
    for event in data["data"]:
        time = event.get("time", "Unknown time")
        obs_region = event.get("obsRegion") or event.get("local") or "Unknown location"
        magnitude = event.get("magnitud", "Unknown magnitude")
        mag_type = event.get("magType", "")
        depth = event.get("depth", "Unknown depth")
        lat = event.get("lat", "Unknown lat")
        lon = event.get("lon", "Unknown lon")

        line = (
            f"Time (UTC): {time}\n"
            f"Location: {obs_region}\n"
            f"Magnitude: {magnitude} {mag_type}\n"
            f"Depth: {depth} km\n"
            f"Coordinates: {lat}, {lon}\n"
            "----------------------"
        )
        result_lines.append(line)

    return f"Recent earthquakes (last 30 days) for area {area}:\n\n" + "\n".join(result_lines)


@mcp.tool()
async def get_fire_risk_forecast(day: int = 1) -> str:
    """Get fire risk forecast for Portugal (today or tomorrow).

    Args:
        day: 1 for today, 2 for tomorrow
    """
    if day not in [1, 2]:
        return "Invalid day. Use 1 for today or 2 for tomorrow."

    data = await make_ipma_request(f"forecast/meteorology/rcm/rcm-d{day}.json")

    if not data or "local" not in data:
        return "Unable to fetch fire risk data."

    levels = {
        1: "Reduced",
        2: "Moderate",
        3: "High",
        4: "Very High",
        5: "Maximum"
    }

    high_risk = []
    for county_code, county_info in data["local"].items():
        risk_level = county_info["data"]["rcm"]
        if risk_level >= 4:
            high_risk.append(f"{county_code}: {levels.get(risk_level, 'Unknown')}")

    if not high_risk:
        return "No high fire risk forecasted."

    return f"High fire risk areas (day {day}):\n\n" + "\n".join(high_risk)


@mcp.tool()
async def uv_forecast() -> str:
    """
    Get the Ultraviolet Index (UV) forecast for Portugal for the next 3 days.

    Returns:
        A formatted string with UV index levels by date, location, and hour interval.
    """
    data = await make_ipma_request(f"forecast/meteorology/uv/uv.json")

    if not data:
        return "No UV forecast data available."

    # Function to interpret the UV index
    def uv_level(iuv: float) -> str:
        if iuv >= 11:
            return "Extreme"
        elif iuv >= 8:
            return "Very High"
        elif iuv >= 6:
            return "High"
        elif iuv >= 3:
            return "Moderate"
        elif iuv >= 1:
            return "Low"
        else:
            return "Very Low"

    # Group data by date and location
    forecast = {}
    for entry in data:
        date = entry.get("data", "unknown date")
        loc = entry.get("globalIdLocal", "unknown location")
        hour_interval = entry.get("intervaloHora", "")
        iuv = float(entry.get("iUv", 0))

        if date not in forecast:
            forecast[date] = {}

        if loc not in forecast[date]:
            forecast[date][loc] = []

        forecast[date][loc].append((hour_interval, iuv))

    # Format result
    lines = []
    for date in sorted(forecast.keys()):
        lines.append(f"UV Forecast for {date}:")
        for loc, uv_values in forecast[date].items():
            lines.append(f" Location ID: {loc}")
            for hour_interval, iuv in uv_values:
                level = uv_level(iuv)
                lines.append(f"  - {hour_interval}: UV Index {iuv} ({level})")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")