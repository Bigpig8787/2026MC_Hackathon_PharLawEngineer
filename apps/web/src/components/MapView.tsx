import { useEffect } from "react";
import { CircleMarker, MapContainer, Polyline, Popup, TileLayer, useMap } from "react-leaflet";
import type { LatLng, TravelOption } from "../types";

interface Props { origin: LatLng; building: { name: string; location: LatLng }; option: TravelOption | undefined }

function FitBounds({ points }: { points: [number, number][] }) {
  const map = useMap();
  useEffect(() => { if (points.length > 1) map.fitBounds(points, { padding: [24, 24] }); }, [map, points]);
  return null;
}

export default function MapView({ origin, building, option }: Props) {
  const line: [number, number][] = (option?.route?.polyline ?? []).map((p) => [p.lat, p.lng]);
  const points: [number, number][] = [[origin.lat, origin.lng], [building.location.lat, building.location.lng], ...line];
  const ld = option?.last_decision?.location;
  return (
    <MapContainer center={[origin.lat, origin.lng]} zoom={14} scrollWheelZoom={false}>
      <TileLayer attribution="&copy; OpenStreetMap" url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" />
      <FitBounds points={points} />
      {line.length > 1 && <Polyline positions={line} pathOptions={{ color: option?.feasible ? "#1e66f5" : "#b91c1c", weight: 5 }} />}
      <CircleMarker center={[origin.lat, origin.lng]} radius={7} pathOptions={{ color: "#1f2933" }}><Popup>出發</Popup></CircleMarker>
      <CircleMarker center={[building.location.lat, building.location.lng]} radius={8} pathOptions={{ color: "#15803d" }}><Popup>{building.name}</Popup></CircleMarker>
      {ld && <CircleMarker center={[ld.lat, ld.lng]} radius={7} pathOptions={{ color: "#b45309" }}><Popup>{option?.last_decision?.label}</Popup></CircleMarker>}
    </MapContainer>
  );
}
