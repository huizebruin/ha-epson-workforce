"""Data coordinator for Epson WorkForce/XP integration."""
from __future__ import annotations

import logging
import re
from datetime import timedelta

import aiohttp
import async_timeout
from bs4 import BeautifulSoup
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=5)

# URL paths on the printer's web interface
PATH_PRTINFO = "/PRESENTATION/ADVANCED/INFO_PRTINFO/TOP"
PATH_NWINFO = "/PRESENTATION/ADVANCED/INFO_NWINFO/TOP"
PATH_MENTINFO = "/PRESENTATION/ADVANCED/INFO_MENTINFO/TOP"
PATH_BEHAVIORINFO = "/PRESENTATION/ADVANCED/INFO_BEHAVIORINFO/TOP"


def _parse_key_value(soup: BeautifulSoup) -> dict[str, str]:
    """Parse all <dt>key</dt><dd>value</dd> pairs from a page."""
    result = {}
    for dt in soup.find_all("dt", class_="key"):
        key_span = dt.find("span", class_="key")
        if not key_span:
            continue
        key = key_span.get_text(strip=True).rstrip(":").strip()
        dd = dt.find_next_sibling("dd")
        if dd:
            value = dd.get_text(strip=True)
            result[key] = value
    return result


def _parse_ink_levels(soup: BeautifulSoup) -> dict[str, int | None]:
    """
    Parse ink levels from tank image heights.
    The printer encodes ink level as the pixel height of the ink image.
    Max height observed is ~25px → map to 0-100%.
    Returns dict like {"BK": 88, "Y": 40, ...}
    """
    ink = {}
    MAX_HEIGHT = 25  # observed maximum pixel height = full tank

    for li in soup.find_all("li", class_="tank"):
        img = li.find("img", class_="color")
        clrname_div = li.find("div", class_="clrname")
        if img and clrname_div:
            color = clrname_div.get_text(strip=True)
            try:
                height = int(img.get("height", 0))
                pct = min(100, round((height / MAX_HEIGHT) * 100))
            except (ValueError, ZeroDivisionError):
                pct = None
            ink[color] = pct
    return ink


def _parse_printer_status(soup: BeautifulSoup) -> str:
    """Parse overall printer status text."""
    for fieldset in soup.find_all("fieldset"):
        legend = fieldset.find("legend")
        if legend and "Printer Status" in legend.get_text():
            div = fieldset.find("div", class_="preserve-white-space")
            if div:
                return div.get_text(strip=True)
    return "Unknown"


class EpsonCoordinator(DataUpdateCoordinator):
    """Coordinator that fetches all data from the Epson printer."""

    def __init__(self, hass: HomeAssistant, host: str, port: int = 80) -> None:
        self.host = host
        self.port = port
        self._base_url = f"http://{host}:{port}"
        super().__init__(
            hass,
            _LOGGER,
            name=f"Epson {host}",
            update_interval=SCAN_INTERVAL,
        )

    async def _fetch(self, session: aiohttp.ClientSession, path: str) -> BeautifulSoup | None:
        url = self._base_url + path
        try:
            async with async_timeout.timeout(10):
                resp = await session.get(url)
                resp.raise_for_status()
                html = await resp.text()
                return BeautifulSoup(html, "html.parser")
        except Exception as err:
            _LOGGER.debug("Failed to fetch %s: %s", url, err)
            return None

    async def _async_update_data(self) -> dict:
        """Fetch data from all relevant printer pages."""
        data: dict = {}

        async with aiohttp.ClientSession() as session:
            # --- Product Status page (ink + firmware + serial + MAC) ---
            soup = await self._fetch(session, PATH_PRTINFO)
            if soup is None:
                raise UpdateFailed(f"Cannot reach printer at {self._base_url}")

            data["printer_status"] = _parse_printer_status(soup)
            data["ink_levels"] = _parse_ink_levels(soup)

            kv = _parse_key_value(soup)
            data["firmware"] = kv.get("Firmware")
            data["serial_number"] = kv.get("Serial Number")
            data["mac_address"] = kv.get("Network MAC Address")
            data["epson_connect_status"] = kv.get("Epson Connect Status")

            # --- Network Status page ---
            soup_nw = await self._fetch(session, PATH_NWINFO)
            if soup_nw:
                kv_nw = _parse_key_value(soup_nw)
                data["wifi_ssid"] = kv_nw.get("SSID")
                data["wifi_signal"] = kv_nw.get("Signal Strength")
                data["wifi_speed"] = _parse_wifi_speed(kv_nw.get("Connection Status", ""))
                data["wifi_channel"] = kv_nw.get("Channel")
                data["ip_address"] = kv_nw.get("IP Address")
                data["wifi_security"] = kv_nw.get("Security Level")
                data["wifi_mode"] = kv_nw.get("Wi-Fi Mode")
                data["device_name"] = kv_nw.get("Device Name")

            # --- Usage Status page (page counters) ---
            soup_ment = await self._fetch(session, PATH_MENTINFO)
            if soup_ment:
                kv_ment = _parse_key_value(soup_ment)
                data["total_pages"] = _to_int(kv_ment.get("Total Number of Pages"))
                data["bw_pages"] = _to_int(kv_ment.get("Total Number of B&W Pages"))
                data["color_pages"] = _to_int(kv_ment.get("Total Number of Color Pages"))
                data["bw_scans"] = _to_int(kv_ment.get("B&W Scan"))
                data["color_scans"] = _to_int(kv_ment.get("Color Scan"))
                data["first_print_date"] = kv_ment.get("First Printing Date")

            # --- Hardware Status page ---
            soup_hw = await self._fetch(session, PATH_BEHAVIORINFO)
            if soup_hw:
                kv_hw = _parse_key_value(soup_hw)
                data["scanner_status"] = kv_hw.get("Scanner")
                data["wifi_hw_status"] = kv_hw.get("Wi-Fi")

        return data


def _to_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value.replace(",", "").strip())
    except ValueError:
        return None


def _parse_wifi_speed(connection_status: str) -> str | None:
    """Extract speed from e.g. 'Wi-Fi-72Mbps' → '72 Mbps'."""
    match = re.search(r"(\d+)\s*Mbps", connection_status, re.IGNORECASE)
    if match:
        return f"{match.group(1)} Mbps"
    return connection_status if connection_status else None
