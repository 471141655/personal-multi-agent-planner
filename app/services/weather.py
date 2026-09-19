from __future__ import annotations

from datetime import datetime

import httpx


WEATHER_LABELS = {
    0: "晴朗",
    1: "大致晴朗",
    2: "局部多云",
    3: "阴天",
    45: "有雾",
    48: "雾凇",
    51: "小毛毛雨",
    53: "毛毛雨",
    55: "较强毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    80: "阵雨",
    81: "中等阵雨",
    82: "强阵雨",
    95: "雷暴",
}


def fetch_weather(city: str, target_at: datetime) -> dict:
    with httpx.Client(timeout=8.0, follow_redirects=True) as client:
        geo_response = client.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1, "language": "zh", "format": "json"},
        )
        geo_response.raise_for_status()
        results = geo_response.json().get("results") or []
        if not results:
            raise ValueError(f"无法识别城市：{city}")
        place = results[0]
        forecast_response = client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "hourly": "temperature_2m,apparent_temperature,precipitation_probability,weather_code,wind_speed_10m",
                "timezone": "Asia/Shanghai",
                "forecast_days": 7,
            },
        )
        forecast_response.raise_for_status()
        payload = forecast_response.json()

    hourly = payload.get("hourly", {})
    times = hourly.get("time", [])
    if not times:
        raise ValueError("天气接口未返回小时数据")
    target_key = target_at.strftime("%Y-%m-%dT%H:00")
    index = min(range(len(times)), key=lambda idx: abs(datetime.fromisoformat(times[idx]) - datetime.fromisoformat(target_key)))
    code = int(hourly["weather_code"][index])
    return {
        "city": city,
        "resolved_name": place.get("name", city),
        "latitude": place["latitude"],
        "longitude": place["longitude"],
        "forecast_time": times[index],
        "temperature": hourly["temperature_2m"][index],
        "apparent_temperature": hourly["apparent_temperature"][index],
        "precipitation_probability": hourly["precipitation_probability"][index],
        "wind_speed": hourly["wind_speed_10m"][index],
        "weather_code": code,
        "condition": WEATHER_LABELS.get(code, "未知天气"),
    }

