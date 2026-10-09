import { useEffect, useMemo, useRef } from 'react'
import L from 'leaflet'
import { CircleMarker, MapContainer, Marker, Polyline, TileLayer, Tooltip, useMap } from 'react-leaflet'
import { formatPlate } from '../lib/format'

const DEHRADUN = [30.25, 78.05]

function markerKind(v) {
  if (v.status === 'MAINTENANCE') return 'maintenance'
  if (v.trip?.status === 'ACTIVE' && (v.location?.speed_kmh ?? 0) > 0) return 'moving'
  if (v.trip?.status === 'SCHEDULED') return 'scheduled'
  return 'idle'
}

const escapeHtml = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))

// Leaflet's default PNG markers break under bundlers, so markers are plain HTML labels.
function plateIcon(v, selected) {
  const classes = ['tt-marker', `tt-marker--${markerKind(v)}`, selected ? 'tt-marker--selected' : ''].join(' ')
  return L.divIcon({
    className: 'tt-icon',
    html: `<div class="${classes}">${escapeHtml(formatPlate(v.registration_no))}</div>`,
    iconSize: [0, 0],
  })
}

/** Fits the map to all vehicles once, then leaves the view to the user. */
function FitOnce({ points }) {
  const map = useMap()
  const done = useRef(false)
  useEffect(() => {
    if (done.current || points.length === 0) return
    done.current = true
    map.fitBounds(L.latLngBounds(points), { padding: [60, 60], maxZoom: 13 })
  }, [map, points])
  return null
}

function FlyTo({ target }) {
  const map = useMap()
  useEffect(() => {
    if (target) map.flyTo(target, Math.max(map.getZoom(), 12), { duration: 0.6 })
  }, [map, target])
  return null
}

export default function FleetMap({ vehicles, selectedId, onSelect, trail, flyTarget }) {
  const points = useMemo(
    () => vehicles.filter((v) => v.location).map((v) => [v.location.latitude, v.location.longitude]),
    [vehicles],
  )
  const selected = vehicles.find((v) => v.vehicle_id === selectedId)

  return (
    <MapContainer center={DEHRADUN} zoom={11} className="h-full w-full" scrollWheelZoom>
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <FitOnce points={points} />
      <FlyTo target={flyTarget} />

      {trail?.length > 1 && (
        <Polyline positions={trail.map((p) => [p.latitude, p.longitude])}
                  pathOptions={{ color: '#f0a202', weight: 4, opacity: 0.9 }} />
      )}
      {selected?.trip && (
        <CircleMarker center={[selected.trip.dest_lat, selected.trip.dest_lng]} radius={7}
                      pathOptions={{ color: '#0e5a43', fillColor: '#fff', fillOpacity: 1, weight: 3 }}>
          <Tooltip direction="top" offset={[0, -6]}>Destination: {selected.trip.destination}</Tooltip>
        </CircleMarker>
      )}

      {vehicles.filter((v) => v.location).map((v) => (
        <Marker
          key={v.vehicle_id}
          position={[v.location.latitude, v.location.longitude]}
          icon={plateIcon(v, v.vehicle_id === selectedId)}
          zIndexOffset={v.vehicle_id === selectedId ? 1000 : 0}
          eventHandlers={{ click: () => onSelect(v.vehicle_id) }}
          keyboard
          title={formatPlate(v.registration_no)}
        />
      ))}
    </MapContainer>
  )
}
