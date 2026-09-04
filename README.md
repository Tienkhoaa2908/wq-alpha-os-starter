# WQ Alpha OS Starter

Local research system for WorldQuant BRAIN metadata exports.

## Quick start

```bash
python -m venv .venv
.venv\\Scripts\\activate  # Windows PowerShell: .venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
python -m src.ingest_raw
python -m src.generate_alphas
streamlit run src.app
```

Use `browser_exporter.js` in browser console to export visible BRAIN pages into JSON, then place files under `exports_raw/`.
