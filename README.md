# Hue Sensor Logger

Real-time motion detection and sensor logging for Philips Hue bridges with Pushover notifications.

## Features

- **Real-time event monitoring** - Instant motion detection via Hue Event Stream API
- **Polling monitor** - Periodic sensor polling (fallback for older bridges)
- **Organized logging** - Sensor data logged by category and name
- **Pushover alerts** - Get notifications on motion detection (optional)
- **Configurable alerts** - Set up alerts for motion, temperature, battery, and offline status
- **Selective logging** - Log only specific sensor categories (motion, temperature, light, etc.)

## Installation

### Requirements
- Python 3.8+
- Philips Hue Bridge on the same network

### Setup

1. **Clone or download** the project
2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the app for the first time**:
   ```bash
   python main.py list
   ```
   - The app will discover your Hue Bridge automatically
   - When prompted, **press the link button on your Hue Bridge** and press Enter
   - Your bridge credentials are saved to `config/settings.json`

## Usage

### Commands

#### Monitor in Real-Time (Recommended)
```bash
python main.py stream
```
Connects to the Hue Event Stream for instant motion detection.

Output:
```
============================================================
🔔 MOTION DETECTED: Kitchen
   Time: 14:32:15 | Date: 2026-01-18
============================================================

  >> Pushover alert sent
```

#### Polling Monitor
```bash
python main.py monitor -i 10    # Poll every 10 seconds (default: 30s)
```

#### Single Read
```bash
python main.py run               # Read sensors once
python main.py run -q            # Quiet mode (no console output)
```

#### List Sensors
```bash
python main.py list              # Show all current sensor values
```

#### View Configuration
```bash
python main.py alerts            # Show configured alerts
python main.py logs              # Show logged sensors
```

### Logging Options

By default, only motion sensors are logged. Control what gets logged:

```bash
# Log only motion (default)
python main.py run
python main.py monitor

# Log motion and temperature
python main.py run --log "motion,temperature"

# Log all categories
python main.py run --log "motion,temperature,light,switch,daylight"
```

Available categories: `motion`, `temperature`, `light`, `switch`, `daylight`, `other`

## Configuration

### Pushover Notifications (Optional)

1. **Get your keys:**
   - Pushover user key: https://pushover.net
   - Create an app: https://pushover.net/apps/build

2. **Configure** `config/settings.json`:
   ```json
   {
     "pushover": {
       "user_key": "YOUR_USER_KEY",
       "api_token": "YOUR_APP_TOKEN"
     }
   }
   ```

### Motion Alerts

Edit `config/alerts.json` to set up motion notifications:

```json
{
  "sensors": [
    {
      "sensor_name": "Kitchen",
      "type": "presence",
      "condition": "detected",
      "cooldown": 1,
      "priority": 0,
      "sound": "pushover",
      "enabled": true
    }
  ]
}
```

**Alert Types:**
- `presence` - Motion detected/cleared
- `temperature` - Temperature above/below threshold
- `battery` - Low battery warning
- `offline` - Sensor goes unreachable

**Priority Levels:**
- `-2` - Silent (no notification)
- `-1` - Low (quiet)
- `0` - Normal
- `1` - High (bypass quiet hours)
- `2` - Emergency (requires acknowledgment)

## Project Structure

```
APIHUE/
├── app/
│   ├── bridge.py           # Hue Bridge connection
│   ├── sensors.py          # Sensor reading & parsing
│   ├── logger.py           # Organized logging
│   ├── notifications.py    # Pushover alerts
│   └── eventstream.py      # Real-time event stream
├── config/
│   ├── settings.json       # Bridge IP, API key, Pushover creds
│   └── alerts.json         # Alert rules
├── logs/
│   └── sensors/
│       ├── motion/         # Motion sensor logs
│       ├── temperature/    # Temperature sensor logs
│       └── ...
├── main.py                 # Main entry point
└── README.md               # This file
```

## Log Format

Sensor logs are organized by category and name:

```
logs/sensors/motion/Kitchen.json
logs/sensors/temperature/Bedroom.json
logs/sensors/light/Living_Room.json
```

Each file contains:
```json
{
  "sensor_info": {
    "id": "37",
    "name": "Kitchen",
    "type": "ZLLPresence",
    "category": "motion"
  },
  "readings": [
    {
      "timestamp": "2026-01-18T14:32:15.123456",
      "presence": true,
      "battery": 95,
      "reachable": true
    }
  ]
}
```

## Troubleshooting

### Motion detection not working
- Use `python main.py stream` instead of polling (real-time vs 30-second intervals)
- Motion sensors only report `presence: true` for a few seconds
- Check that alerts are enabled in `config/alerts.json`

### No Pushover notifications
- Verify credentials in `config/settings.json`
- Run `python main.py alerts` to confirm alerts are enabled
- Check alert cooldown - notifications won't repeat within the cooldown period

### Bridge not found
- Ensure bridge is on the same network
- Try resetting bridge discovery by deleting `config/settings.json` and running `python main.py list` again

## Supported Sensors

- **Motion Sensors** - ZLLPresence (detect presence)
- **Temperature Sensors** - ZLLTemperature (ambient temperature)
- **Light Sensors** - ZLLLightLevel (ambient light level)
- **Switches** - ZLLSwitch, ZGPSwitch (button events)
- **Daylight Sensor** - Daylight (day/night indicator)

## License

MIT
