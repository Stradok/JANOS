# JAN AR Client

A mobile web app that turns your phone into an AR viewer powered by JAN's AR module.

## Quick Start

1. **Ensure your phone and JAN are on the same WiFi network**
2. Open `index.html` on your phone's browser
3. Tap the **⚙** gear icon and enter JAN's IP address and port (e.g. `192.168.1.100:8765`)
4. Tap **Connect** — the status dot turns green when connected
5. Grant camera and location permissions when prompted

## Modes

| Mode | Description |
|------|-------------|
| **Translate** | Point camera at text — JAN translates it and overlays the result |
| **Navigate** | AR navigation arrows. Tap **Set Destination**, type a place name, and JAN will geocode it and guide you |
| **Detect** | Object detection — JAN draws bounding boxes and labels around recognized objects |
| **Faces** | Face labeling — JAN identifies known faces and overlays names |

## Requirements

- **HTTPS or localhost**: Most browsers require a secure context to access the camera. Options:
  - Serve via HTTPS (e.g. `python -m http.server` behind an HTTPS reverse proxy)
  - Use `localhost` (always allowed)
  - In Chrome, add your LAN IP to `chrome://flags/#unsafely-treat-insecure-origin-as-secure`
- **Modern mobile browser**: Chrome, Safari, or Firefox on iOS/Android
- **Camera permission**: Required for the video feed
- **Location permission**: Required for GPS-based navigation mode

## Protocol

The client communicates with JAN's `ar_module` over WebSocket:

### Phone → JAN
```json
{"type": "frame", "data": "<base64 jpeg>", "mode": "translate|navigate|detect|label_faces"}
{"type": "gps", "lat": 40.7128, "lon": -74.0060}
{"type": "set_destination", "lat": 40.7128, "lon": -74.0060, "name": "Central Park"}
```

### JAN → Phone
```json
{"type": "overlay", "elements": [
  {"type": "text", "x": 100, "y": 50, "content": "Hello", "color": "#00ff88", "size": 16},
  {"type": "box", "x": 10, "y": 20, "w": 80, "h": 60, "label": "Cat", "color": "#ff0"},
  {"type": "arrow", "x": 160, "y": 120, "angle": 45, "color": "#00aaff"},
  {"type": "path", "points": [{"x":0,"y":240},{"x":160,"y":120}], "color": "#ffaa00"}
]}
```

Overlay coordinates use a 320×240 grid that the client scales to the phone's viewport.

## Troubleshooting

- **Black screen**: Camera permission was denied — check browser settings
- **Can't connect**: Verify JAN's AR server is running and the IP/port are correct
- **No overlays**: Check that JAN's `ar_module` is active and processing the selected mode
