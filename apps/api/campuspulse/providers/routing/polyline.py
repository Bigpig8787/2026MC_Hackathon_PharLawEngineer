"""Google encoded polyline decoder."""
from __future__ import annotations

from campuspulse.core.models import LatLng


def decode_polyline(encoded: str) -> list[LatLng]:
    points: list[LatLng] = []
    index = lat = lng = 0
    while index < len(encoded):
        for is_lat in (True, False):
            result = shift = 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if is_lat:
                lat += delta
            else:
                lng += delta
        points.append(LatLng(lat=lat / 1e5, lng=lng / 1e5))
    return points
