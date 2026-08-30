# BirdNET fake detection data

`fake_birdnet_detections` creates development data directly through the Django
ORM. It requires an existing device, active cached species, and migrated schema.

```powershell
python manage.py fake_birdnet_detections --device pi-birdnet-001
```

Defaults: 25 rows over the previous 24 hours, confidence 0.50–0.99.

| Option | Default | Purpose |
|---|---:|---|
| `--device IDENTIFIER` | required | Existing device identifier. |
| `--count N` | `25` | Rows to create, 1–10,000. |
| `--hours HOURS` | `24` | Time window before now. |
| `--min-confidence VALUE` | `0.5` | Minimum confidence, 0–1. |
| `--max-confidence VALUE` | `0.99` | Maximum confidence, 0–1. |
| `--species SCIENTIFIC_NAME` | all active | Repeatable species restriction. |
| `--seed INTEGER` | random | Reproducible random generation. |
| `--interval SECONDS` | off | Emit one live detection (timestamped now) every SECONDS instead of bulk history, for testing the SSE stream. |

```powershell
python manage.py fake_birdnet_detections `
  --device pi-birdnet-001 `
  --count 100 `
  --hours 6 `
  --species "Turdus merula" `
  --species "Erithacus rubecula" `
  --seed 42
```

```powershell
python manage.py fake_birdnet_detections --device pi-birdnet-001 --count 20 --interval 1
```

With `--interval`, `--count` detections are created one at a time with the given
gap between them; each is stamped with the current time, so an open
`GET /api/birdnet/detections/stream` receives them live.

Generated records are eligible for normal 24-hour cleanup.

