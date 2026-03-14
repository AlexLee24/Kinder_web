# Kinder Trigger

# For newest readme please check [github](https://github.com/AlexLee24/Kinder_Trigger)

Astronomical observation task trigger tool for the Kinder Team. Automatically generates ACP observation scripts and sends them to the control room.

Supports both **SLT** and **LOT** (Lulin One-meter Telescope).

## Installation

Download the latest `.dmg` file from the [Releases](https://github.com/AlexLee24/Kinder_Trigger/releases) page. Double-click to mount the disk image, then drag **Kinder Trigger.app** into your Applications folder.

> **First launch on macOS**: If you see "cannot be opened because it is from an unidentified developer", go to **System Settings -> Privacy & Security** and click "Open Anyway".

---

## Interface Overview

The left sidebar contains four pages:

| Page | Description |
|------|-------------|
| **Home** | Manage observation target list |
| **Script** | Generate ACP observation script and visibility plot |
| **Send** | Preview script and send to Slack control room |
| **Settings** | Configure data path, Slack credentials, and LOT programs |

---

## Page 1 — Home

### Basic Operations

- Use the **Telescope** dropdown (top right) to switch between SLT and LOT. The corresponding JSON file is loaded automatically.
- Click **Add Target** to add a new target.
- Each target card has the following buttons:
  - Up / Down arrows — reorder targets
  - Edit — open the target editor
  - Copy — duplicate the target
  - Delete — remove the target
- All changes are auto-saved to `main_set_SLT.json` or `main_set_LOT.json`.

### Add / Edit Target Fields

| Field | Description |
|-------|-------------|
| **Target Name** | Target identifier (only letters, digits, and hyphens are kept in the script) |
| **RA** | Right Ascension — accepts `hh:mm:ss.ss` or decimal degrees (auto-converted) |
| **Dec** | Declination — accepts `+/-dd:mm:ss.ss` or decimal degrees (auto-converted) |
| **Magnitude** | Apparent magnitude |
| **Priority** | Normal / High / Urgent |
| **Repeat** | Number of repeat observations (0 = no repeat) |
| **Program** | LOT only — select observation program (e.g. R01, R07) |
| **Auto Exposure** | Automatically determine exposure time from magnitude (see rules below) |
| **Note** | Required when priority is Urgent |

### Exposure Rules

**SLT — Auto Exposure Table**:

| Magnitude | up | gp | rp | ip | zp |
|-----------|-----|-----|-----|-----|-----|
| <=12 | 60s x1 | 30s x1 | 30s x1 | 30s x1 | 30s x1 |
| 13-14 | 60s x2 | 60s x1 | 60s x1 | 60s x1 | 60s x1 |
| 15-16 | 150s x2 | 150s x1 | 150s x1 | 150s x1 | 150s x1 |
| 17-19 | 300s x2 | 300s x1 | 300s x1 | 300s x1 | 300s x1 |
| 20 | — | — | 300s x6 | — | — |
| 21 | — | — | 300s x12 | — | — |
| 22 | — | — | 300s x36 | — | — |
| >22 or <12 | Manual exposure required |

**LOT**: Auto Exposure is always disabled. Manual filter and exposure settings are required for all targets.

### Manual Exposure Configuration

When Auto Exposure is off, configure filters manually:

- **Add Filter** — add a single filter row (default: rp, 300s, x1)
- **+ All ugriz** — add all five SDSS filters at once
- **+ All UBVRI** — add all five Johnson-Cousins filters at once
- Each filter row has independent exposure time (seconds) and count settings
- Subtotals and grand total exposure time are updated in real time

### Supported Filters

| Set | Filters |
|-----|---------|
| SDSS | up, gp, rp, ip, zp |
| Johnson-Cousins (developing)| U, B, V, R, I |

---

## Page 2 — Script

### Steps

1. Select **Telescope** (SLT or LOT).
2. If LOT is selected, choose a **Program** (e.g. R01).
3. Choose the target sort order:
   - **Home order** — use the order from the Home page
   - **Rise time order** — sort by rise time, earliest first
4. Click **Generate Script**.
5. The visibility plot appears on the right (Object Visibility).
6. Click **Copy to Clipboard** to copy the script.

### Output Files

Files are saved under the configured data path:

- Scripts:
  - SLT -> `script_SLT.txt`
  - LOT R01 -> `script_LOT_R01.txt`
- Visibility plots (in `plot/` subfolder):
  - SLT -> `obv_plot_SLT.jpg`
  - LOT R01 -> `obv_plot_LOT_R01.jpg`

### Generated ACP Script Format

```
;===SLT_Normal_priority===

#BINNING 1, 1, 1, 1, 1
#FILTER up_Astrodon_2018, gp_Astrodon_2018, rp_Astrodon_2018, ip_Astrodon_2018, zp_Astrodon_2018
#INTERVAL 300, 300, 300, 300, 300
#COUNT 2, 1, 1, 1, 1
;# mag: 17.5 mag
SN2024ggi	11:18:22.09	-32:50:15.27
#WAITFOR 1
```

---

## Page 3 — Send

### Steps

1. Select a script file from the dropdown (filename and modification date are shown).
2. Click **Load**:
   - The script content appears in the left preview panel.
   - The visibility plot is regenerated from the current target list and shown on the right.
   - The message field is auto-populated with telescope and program information.
3. Edit the message text if needed.
4. Click **Send to Slack** and confirm in the dialog.

### What Gets Sent

The following are sent to the Slack control room channel:

1. The message text
2. The observation script file (.txt)
3. The visibility plot (.jpg)

---

## Page 4 — Settings

### Data Path

The directory where all JSON files, scripts, and plots are stored. Defaults to `~/Documents/Kinder_Trigger/`. Click **Change Folder** to update.

### LOT Programs

- Manage the list of LOT observation programs (e.g. R01, R07, R11) using chip tags.
- Click **Add** to add a new program code (automatically uppercased).
- Click the X on a chip to remove a program.
- The list is persisted to `~/.kinder_trigger/programs.json`.

### Slack Configuration

| Field | Description |
|-------|-------------|
| **Slack Bot Token** | Bot token (`xoxb-...`). Contact Alex to obtain one. |
| **Slack Channel ID** | Control room channel ID (`C...`). |

Click **Save to .env** to persist. Settings are stored in `~/.kinder_trigger/.env`.

---

## Directory Structure

```
~/Documents/Kinder_Trigger/        <- data path (configurable in Settings)
├── main_set_SLT.json              <- SLT target list
├── main_set_LOT.json              <- LOT target list
├── script_SLT.txt                 <- generated SLT script
├── script_LOT_R01.txt             <- generated LOT R01 script
└── plot/                          <- visibility plots
    ├── obv_plot_SLT.jpg
    └── obv_plot_LOT_R01.jpg

~/.kinder_trigger/                 <- config directory (persists across app updates)
├── .env                           <- Slack credentials + DATA_PATH
└── programs.json                  <- LOT program list
```

---

## JSON Format (v2)

Targets are auto-saved to `main_set_SLT.json` or `main_set_LOT.json`:

```json
{
  "version": 2,
  "settings": { "telescope": "SLT" },
  "targets": [
    {
      "name": "SN2024ggi",
      "ra": "11:18:22.087",
      "dec": "-32:50:15.27",
      "mag": "17.5",
      "priority": "Normal",
      "auto_exposure": true,
      "observations": [],
      "repeat": 0,
      "program": "",
      "note": ""
    }
  ]
}
```

### Manual Exposure Example

```json
{
  "name": "M31",
  "ra": "00:42:44.3",
  "dec": "+41:16:09",
  "mag": "3.4",
  "priority": "High",
  "auto_exposure": false,
  "observations": [
    { "filter": "gp", "exp_time": 300, "count": 5 },
    { "filter": "rp", "exp_time": 300, "count": 5 }
  ],
  "repeat": 0,
  "program": "",
  "note": "Monitor nightly"
}
```

### LOT Target Example (with program)

```json
{
  "name": "AT2025abc",
  "ra": "14:30:12.5",
  "dec": "+25:10:45.0",
  "mag": "19.0",
  "priority": "Normal",
  "auto_exposure": false,
  "observations": [
    { "filter": "rp", "exp_time": 300, "count": 3 },
    { "filter": "ip", "exp_time": 300, "count": 3 }
  ],
  "repeat": 0,
  "program": "R01",
  "note": ""
}
```

### Field Reference

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Target name |
| `ra` | string | Right Ascension (`hh:mm:ss.ss` or decimal degrees) |
| `dec` | string | Declination (`+/-dd:mm:ss.ss` or decimal degrees) |
| `mag` | string | Apparent magnitude |
| `priority` | string | `"Normal"` / `"High"` / `"Urgent"` |
| `auto_exposure` | bool | `true` = auto by magnitude, `false` = manual |
| `observations` | array | Manual exposure settings (used when `auto_exposure` is false) |
| `repeat` | int | Repeat count (0 = no repeat) |
| `program` | string | LOT program code (leave empty for SLT) |
| `note` | string | Notes (required for Urgent priority) |

> Legacy v1 JSON files are automatically converted to v2 on load.

---

## Environment Variables (.env)

Created automatically at `~/.kinder_trigger/.env` on first launch:

```env
DATA_PATH=/Users/you/Documents/Kinder_Trigger
SLACK_BOT_TOKEN=xoxb-...
SLACK_CHANNEL_ID_CONTROL_ROOM=C...
```

| Variable | Description |
|----------|-------------|
| `DATA_PATH` | Directory for JSON files, scripts, and plots |
| `SLACK_BOT_TOKEN` | Slack Bot Token (contact Alex to obtain) |
| `SLACK_CHANNEL_ID_CONTROL_ROOM` | Slack control room channel ID |

---

## Important Notes

- Triple-check the observation plan before sending to the control room.
- The `.env` file contains sensitive credentials — do not commit it to version control.
- Coordinates accept decimal degree input and are automatically converted to sexagesimal in the generated script.
- Target names are sanitized in the script output: only letters, digits, and hyphens are kept.

---

## Developers

Kinder Team — National Central University, Institute of Astronomy, GREAT Lab

## License

Developed by the [Kinder Team](http://kinder.astro.ncu.edu.tw).
The observation planning module is based on [obsplanning](https://github.com/pjcigan/obsplanning) by Phil Cigan.