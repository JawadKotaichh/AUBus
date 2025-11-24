
import os
import sys
from weather_service import WeatherService, WeatherServiceError

def test_weather():
    print("Testing WeatherService...")
    print(f"WEATHER_ALLOW_FALLBACK: {os.getenv('WEATHER_ALLOW_FALLBACK')}")
    
    ws = WeatherService()
    print(f"Fallback enabled: {ws.supports_fallback}")
    
    try:
        result = ws.fetch()
        print("Fetch successful:", result)
    except WeatherServiceError as e:
        print("Fetch failed:", e)
    except Exception as e:
        print("Unexpected error:", e)

if __name__ == "__main__":
    test_weather()
