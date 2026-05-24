# TZI Soccer Analytics App

Streamlit-based web app for TZI (Tactical Zone Intelligence) analysis.

## Run locally

```bash
pip install -r requirements.txt
streamlit run scripts/app/tzi_app.py
```

Browser opens at http://localhost:8501

## Features

- **Browse mode**: View analysis results for all 8 existing matches
  - Position heatmaps (field overlay)
  - Zone distribution bar chart
  - Player details table
  - Direction debug visualization

- **Upload mode**: Analyze a new video file (MP4/AVI/MOV)
  - Drag-and-drop upload
  - Select half (1H / 2H)
  - Adjustable sampling interval

## Next steps toward full app

1. Add `process_video_half()` as an exported function in `track_players_v3.py`
2. Per-frame homography using field line detection (accuracy improvement)
3. Real-time RTSP stream support
4. Deploy to Streamlit Cloud or Hugging Face Spaces
