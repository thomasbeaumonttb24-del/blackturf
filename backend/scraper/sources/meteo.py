"""
Source OpenWeatherMap — Météo par hippodrome.
Fréquence : toutes 30 minutes.
"""
import httpx
import structlog
from typing import Optional
from api.config import get_settings

log = structlog.get_logger(source="meteo")

# Coordonnées des principaux hippodromes français
HIPPODROMES_COORDS = {
    "PARIS-VINCENNES": (48.8484, 2.4360),
    "CHANTILLY": (49.1942, 2.4639),
    "LONGCHAMP": (48.8578, 2.2375),
    "SAINT-CLOUD": (48.8558, 2.2044),
    "MAISONS-LAFFITTE": (48.9553, 2.1467),
    "DEAUVILLE": (49.3567, 0.0728),
    "AUTEUIL": (48.8569, 2.2572),
    "COMPIÈGNE": (49.4178, 2.8259),
    "LE LION D'ANGERS": (47.6278, -0.7139),
    "CAGNES-SUR-MER": (43.6636, 7.1564),
    "LA TESTE": (44.6153, -1.1278),
    "BORDEAUX-LE-BOUSCAT": (44.8850, -0.5983),
    "LYON-PARILLY": (45.7233, 4.9119),
    "MARSEILLE-VIVAUX": (43.2833, 5.4167),
    "STRASBOURG": (48.5667, 7.7667),
    "CABOURG": (49.2833, -0.1167),
}


class MeteoScraper:

    def __init__(self):
        self.api_key = get_settings().openweather_api_key
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()

    async def get_meteo(self, hippodrome: str) -> Optional[dict]:
        """Récupère la météo actuelle pour un hippodrome."""
        if not self.api_key:
            log.warning("meteo.no_api_key")
            return None

        coords = self._get_coords(hippodrome)
        if not coords:
            log.warning("meteo.hippodrome_unknown", hippodrome=hippodrome)
            return None

        lat, lon = coords
        url = (
            f"https://api.openweathermap.org/data/2.5/weather"
            f"?lat={lat}&lon={lon}&appid={self.api_key}&units=metric&lang=fr"
        )

        client = await self._get_client()
        try:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()

            return {
                "temperature": data.get("main", {}).get("temp"),
                "humidite": data.get("main", {}).get("humidity"),
                "pression": data.get("main", {}).get("pressure"),
                "vent_vitesse": data.get("wind", {}).get("speed"),
                "vent_direction": self._deg_to_direction(data.get("wind", {}).get("deg")),
                "pluie_24h": data.get("rain", {}).get("1h", 0.0) or 0.0,
                "visibilite": data.get("visibility"),
                "description": data.get("weather", [{}])[0].get("description", ""),
            }
        except Exception as e:
            log.error("meteo.fetch_failed", hippodrome=hippodrome, error=str(e))
            return None

    def _get_coords(self, hippodrome: str) -> Optional[tuple[float, float]]:
        """Trouve les coordonnées d'un hippodrome."""
        hippo_upper = hippodrome.upper()
        for key, coords in HIPPODROMES_COORDS.items():
            if key in hippo_upper or hippo_upper in key:
                return coords
        return None

    @staticmethod
    def _deg_to_direction(deg: Optional[float]) -> Optional[str]:
        if deg is None:
            return None
        dirs = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"]
        idx = round(deg / 45) % 8
        return dirs[idx]
