#!/usr/bin/env python3
"""
TZI Tag Tool — 選手クリック → 背番号タグ付けサーバー

使い方:
  cd scripts/tzi
  python tag_tool.py --match 20260325

ブラウザで http://localhost:5050 を開く。
- スライダーで時刻移動
- 検出枠をクリックして背番号を入力
- 保存ボタンで data/tzi/match_<id>/manual_tags.json に書き込み
"""

import argparse
import base64
import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np
from flask import Flask, jsonify, request, send_from_directory
from ultralytics import YOLO

sys.path.insert(0, str(Path(__file__).parent))
from config import p2f
from track_players_v3 import MATCH_CONFIGS
from config import W_LO1, W_HI1, W_LO2, W_HI2

def is_waseda_player(crop):
    """torso cropが早稲田のマルーン色かどうかHSVで判定。"""
    if crop is None or crop.size == 0:
        return False
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    m = cv2.bitwise_or(cv2.inRange(hsv, W_LO1, W_HI1),
                       cv2.inRange(hsv, W_LO2, W_HI2))
    ratio = m.sum() / 255 / max(crop.shape[0] * crop.shape[1], 1)
    return ratio > 0.07

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_TZI     = PROJECT_ROOT / "data" / "tzi"
VIDEOS       = PROJECT_ROOT / "videos"
STATIC_DIR   = Path(__file__).parent / "tag_tool_static"
STATIC_DIR.mkdir(exist_ok=True)

app = Flask(__name__, static_folder=str(STATIC_DIR))

# ── グローバル状態 ──────────────────────────────────────────────
_cfg        = {}   # match設定
_model      = None
_tags       = {}   # {match_id: {player_uid: {jersey, confirmed_at, ...}}}
_match_id   = None
_tags_path  = None


def _load_model():
    global _model
    if _model is None:
        pt = Path(__file__).parent / "yolov8n.pt"
        _model = YOLO(str(pt))
    return _model


def _get_frame(match_id, time_min):
    """指定試合・時刻のフレームをBGR ndarrayで返す。"""
    cfg  = MATCH_CONFIGS[match_id]
    combined = bool(cfg.get("combined"))
    if combined:
        vpath = VIDEOS / cfg["h1"]
        half  = "1H"
    else:
        cap_tmp = cv2.VideoCapture(str(VIDEOS / cfg["h1"]))
        fps_tmp = cap_tmp.get(cv2.CAP_PROP_FPS) or 30.0
        nf_tmp  = cap_tmp.get(cv2.CAP_PROP_FRAME_COUNT)
        cap_tmp.release()
        h1_dur  = nf_tmp / fps_tmp / 60.0
        if time_min <= h1_dur:
            vpath, half = VIDEOS / cfg["h1"], "1H"
            t_rel = time_min
        else:
            vpath, half = VIDEOS / cfg["h2"], "2H"
            t_rel = time_min - h1_dur

    cap = cv2.VideoCapture(str(vpath))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    if combined:
        t_rel = time_min
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(t_rel * fps * 60))
    ret, frame = cap.read()
    cap.release()
    return frame if ret else None


def _detect(frame):
    """YOLOで人物検出し、検出一覧を返す。"""
    model = _load_model()
    h, w  = frame.shape[:2]
    results = model(frame, classes=[0], verbose=False)[0]
    dets = []
    if results.boxes is None:
        return dets
    for box in results.boxes:
        x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
        conf = float(box.conf[0])
        cx   = (x1 + x2) // 2
        cy   = y2  # foot point
        fx, fy = p2f(cx, cy)
        bh = y2 - y1
        bw = x2 - x1
        # rough Waseda check (HSV on torso)
        torso = frame[y1 + bh//4 : y1 + 3*bh//4, x1:x2]
        waseda = is_waseda_player(torso) if torso.size > 0 else False
        dets.append({
            "det_id": len(dets),
            "x1": x1, "y1": y1, "x2": x2, "y2": y2,
            "cx": cx, "cy": cy,
            "fx": round(fx, 1), "fy": round(fy, 1),
            "conf": round(conf, 3),
            "waseda": waseda,
        })
    return dets


def _encode_frame(frame, dets, tags_at_t, scale=0.75):
    """フレームに検出枠・タグを描いてBase64 JPEGで返す。"""
    vis = cv2.resize(frame, (int(frame.shape[1]*scale), int(frame.shape[0]*scale)))
    vs  = scale
    for d in dets:
        x1, y1, x2, y2 = int(d["x1"]*vs), int(d["y1"]*vs), int(d["x2"]*vs), int(d["y2"]*vs)
        uid = f"{d['cx']}_{d['cy']}"
        jersey = tags_at_t.get(uid)
        color = (0, 200, 100) if d["waseda"] else (80, 80, 200)
        if jersey:
            color = (0, 255, 255)
        cv2.rectangle(vis, (x1, y1), (x2, y2), color, 2)
        label = f"#{jersey}" if jersey else ("W" if d["waseda"] else "O")
        cv2.putText(vis, label, (x1+2, y1+16),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
        cv2.putText(vis, str(d["det_id"]), (x1+2, y2-4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (180,180,180), 1)
    _, buf = cv2.imencode(".jpg", vis, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return base64.b64encode(buf).decode()


# ── ルーティング ───────────────────────────────────────────────
@app.route("/")
def index():
    return INDEX_HTML


@app.route("/api/frame")
def api_frame():
    t = float(request.args.get("t", 0.5))
    frame = _get_frame(_match_id, t)
    if frame is None:
        return jsonify({"error": "frame not found"}), 404
    dets = _detect(frame)

    # このフレーム付近のタグを検索 (±5秒)
    all_tags = _tags.get(_match_id, {})
    tags_at_t = {}
    for key, info in all_tags.items():
        if abs(info.get("confirmed_at", -999) - t) < 0.1:
            tags_at_t[key] = info["jersey"]

    img_b64 = _encode_frame(frame, dets, tags_at_t)
    return jsonify({
        "img": img_b64,
        "dets": dets,
        "time_min": t,
    })


@app.route("/api/tag", methods=["POST"])
def api_tag():
    """選手タグを保存。body: {det_id, cx, cy, fx, fy, jersey, time_min, waseda}"""
    data = request.json
    match_tags = _tags.setdefault(_match_id, {})
    uid = f"{data['cx']}_{data['cy']}"
    match_tags[uid] = {
        "jersey":       int(data["jersey"]),
        "confirmed_at": float(data["time_min"]),
        "cx": data["cx"], "cy": data["cy"],
        "fx": data["fx"], "fy": data["fy"],
        "waseda": data.get("waseda", True),
    }
    _save_tags()
    return jsonify({"ok": True, "total_tags": len(match_tags)})


@app.route("/api/tag/<uid>", methods=["DELETE"])
def api_delete_tag(uid):
    match_tags = _tags.get(_match_id, {})
    match_tags.pop(uid, None)
    _save_tags()
    return jsonify({"ok": True})


@app.route("/api/tags")
def api_tags():
    return jsonify(_tags.get(_match_id, {}))


@app.route("/api/video_info")
def api_video_info():
    cfg = MATCH_CONFIGS.get(_match_id, {})
    combined = bool(cfg.get("combined"))
    if combined:
        cap = cv2.VideoCapture(str(VIDEOS / cfg["h1"]))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        nf  = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        cap.release()
        total_min = nf / fps / 60.0
    else:
        total_min = 90.0
    from track_players_v3 import MATCH_LABELS
    return jsonify({
        "match_id": _match_id,
        "label": MATCH_LABELS.get(_match_id, _match_id),
        "total_min": round(total_min, 1),
        "combined": combined,
    })


def _save_tags():
    out = _tags.get(_match_id, {})
    _tags_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"  [tag] saved {len(out)} tags → {_tags_path}")


# ── HTML ──────────────────────────────────────────────────────
INDEX_HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<title>TZI Tag Tool</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #0d1117; color: #e6edf3; font-family: Arial, sans-serif; font-size: 14px; }
header { background: #161b22; padding: 14px 20px; border-bottom: 1px solid #30363d; display:flex; align-items:center; gap:16px; }
header h1 { font-size:16px; color:#58a6ff; }
.sub { color:#8b949e; font-size:12px; }
#main { display:flex; gap:0; height: calc(100vh - 53px); }
#canvas-wrap { flex:1; position:relative; overflow:hidden; background:#000; display:flex; align-items:center; justify-content:center; }
#frame-img { max-width:100%; max-height:100%; cursor:crosshair; }
#sidebar { width:280px; background:#161b22; border-left:1px solid #30363d; display:flex; flex-direction:column; overflow:hidden; }
.sidebar-section { padding:14px; border-bottom:1px solid #30363d; }
.sidebar-section h2 { font-size:13px; color:#8b949e; margin-bottom:10px; text-transform:uppercase; letter-spacing:1px; }
#time-display { font-size:22px; font-weight:bold; color:#58a6ff; }
input[type=range] { width:100%; accent-color:#58a6ff; }
.btn { display:block; width:100%; padding:8px; border-radius:6px; border:none; cursor:pointer; font-size:13px; margin-top:6px; }
.btn-primary { background:#238636; color:#fff; }
.btn-secondary { background:#21262d; color:#e6edf3; border:1px solid #30363d; }
.btn:hover { filter:brightness(1.2); }
#tag-panel { padding:14px; }
#tag-panel h2 { font-size:13px; color:#8b949e; margin-bottom:8px; }
.tag-item { display:flex; align-items:center; justify-content:space-between; padding:6px 8px; background:#21262d; border-radius:4px; margin-bottom:4px; font-size:12px; }
.tag-item .num { font-weight:bold; color:#3fb950; font-size:15px; min-width:28px; }
.tag-item .pos { color:#8b949e; }
.tag-del { background:none; border:none; color:#f85149; cursor:pointer; font-size:14px; padding:0 4px; }
#info-box { background:#0d1117; border:1px solid #30363d; border-radius:6px; padding:10px; font-size:12px; color:#8b949e; min-height:48px; }
#jersey-input-wrap { display:none; position:absolute; z-index:100; background:#161b22; border:2px solid #58a6ff; border-radius:8px; padding:12px; box-shadow:0 4px 20px rgba(0,0,0,0.5); }
#jersey-input-wrap input { width:80px; font-size:24px; text-align:center; background:#0d1117; color:#e6edf3; border:1px solid #58a6ff; border-radius:4px; padding:4px; }
#jersey-input-wrap .hint { font-size:11px; color:#8b949e; margin-top:6px; }
</style>
</head>
<body>
<header>
  <h1>TZI Tag Tool</h1>
  <span id="match-label" class="sub">loading...</span>
</header>
<div id="main">
  <div id="canvas-wrap">
    <img id="frame-img" src="" alt="loading..." />
    <div id="jersey-input-wrap">
      <div style="font-size:12px;color:#8b949e;margin-bottom:8px">背番号を入力 (Enterで確定・Escでキャンセル)</div>
      <input id="jersey-num" type="number" min="1" max="99" placeholder="#" autofocus />
      <div class="hint" id="det-info"></div>
    </div>
  </div>
  <div id="sidebar">
    <div class="sidebar-section">
      <h2>時刻</h2>
      <div id="time-display">0:00</div>
      <input type="range" id="time-slider" min="0" max="90" step="0.1" value="0.5" />
      <div style="display:flex;gap:6px;margin-top:8px">
        <button class="btn btn-secondary" onclick="seekRel(-0.5)">◀ 30秒</button>
        <button class="btn btn-secondary" onclick="seekRel(0.5)">30秒 ▶</button>
      </div>
      <button class="btn btn-secondary" onclick="seekRel(-0.033)" style="margin-top:4px">◀ 2秒</button>
      <button class="btn btn-secondary" onclick="seekRel(0.033)" style="margin-top:4px">2秒 ▶</button>
    </div>
    <div class="sidebar-section">
      <h2>操作説明</h2>
      <div id="info-box">選手の枠をクリック → 背番号を入力してEnter。<br>緑=早稲田 青=相手 黄=タグ済み</div>
    </div>
    <div style="flex:1;overflow-y:auto">
      <div id="tag-panel">
        <h2>タグ一覧 (<span id="tag-count">0</span>)</h2>
        <div id="tag-list"></div>
      </div>
    </div>
  </div>
</div>

<script>
let currentDets = [];
let selectedDet = null;
let pendingClickX = 0, pendingClickY = 0;
let currentTime = 0.5;
let maxTime = 90;
let imgRect = null;
let allTags = {};

async function loadVideoInfo() {
  const r = await fetch('/api/video_info');
  const info = await r.json();
  document.getElementById('match-label').textContent = info.label;
  maxTime = info.total_min;
  document.getElementById('time-slider').max = info.total_min;
}

async function loadFrame(t) {
  currentTime = t;
  document.getElementById('time-display').textContent =
    Math.floor(t) + ':' + String(Math.round((t % 1) * 60)).padStart(2,'0');
  const r = await fetch(`/api/frame?t=${t}`);
  const data = await r.json();
  if (data.error) return;
  currentDets = data.dets;
  document.getElementById('frame-img').src = 'data:image/jpeg;base64,' + data.img;
  imgRect = null;
}

async function loadTags() {
  const r = await fetch('/api/tags');
  allTags = await r.json();
  renderTagList();
}

function renderTagList() {
  const list = document.getElementById('tag-list');
  const keys = Object.keys(allTags);
  document.getElementById('tag-count').textContent = keys.length;
  list.innerHTML = keys.map(uid => {
    const t = allTags[uid];
    return `<div class="tag-item">
      <span class="num">#${t.jersey}</span>
      <span class="pos">${t.waseda?'早稲田':'相手'} (${t.fx},${t.fy}m) t=${t.confirmed_at.toFixed(1)}min</span>
      <button class="tag-del" onclick="deleteTag('${uid}')">✕</button>
    </div>`;
  }).join('');
}

async function deleteTag(uid) {
  await fetch(`/api/tag/${uid}`, {method:'DELETE'});
  await loadTags();
  await loadFrame(currentTime);
}

document.getElementById('frame-img').addEventListener('click', function(e) {
  if (!imgRect) imgRect = this.getBoundingClientRect();
  const scaleX = this.naturalWidth / imgRect.width;
  const scaleY = this.naturalHeight / imgRect.height;
  const imgX = (e.clientX - imgRect.left) * scaleX;
  const imgY = (e.clientY - imgRect.top)  * scaleY;

  // 画像は0.75スケールで描画されているので実際のピクセル座標に変換
  const VIS_SCALE = 0.75;
  const frameX = imgX / VIS_SCALE;
  const frameY = imgY / VIS_SCALE;

  // 最近傍検出を探す (bboxの中心から50px以内)
  let best = null, bestD = 60;
  for (const d of currentDets) {
    const dx = frameX - d.cx;
    const dy = frameY - (d.y1 + d.y2)/2;
    const dist = Math.sqrt(dx*dx + dy*dy);
    if (dist < bestD) { bestD = dist; best = d; }
  }
  if (!best) {
    document.getElementById('info-box').textContent = '検出された選手の近くをクリックしてください';
    return;
  }
  selectedDet = best;
  pendingClickX = e.clientX;
  pendingClickY = e.clientY;

  const wrap = document.getElementById('jersey-input-wrap');
  wrap.style.display = 'block';
  wrap.style.left = Math.min(e.clientX + 10, window.innerWidth - 200) + 'px';
  wrap.style.top  = Math.max(e.clientY - 60, 10) + 'px';
  document.getElementById('jersey-num').value = '';
  document.getElementById('det-info').textContent =
    `Det#${best.det_id} | ${best.waseda?'早稲田':'相手'} | Field(${best.fx},${best.fy}m)`;
  document.getElementById('jersey-num').focus();
});

document.getElementById('jersey-num').addEventListener('keydown', async function(e) {
  if (e.key === 'Enter') {
    const jersey = parseInt(this.value);
    if (!isNaN(jersey) && jersey >= 1 && jersey <= 99 && selectedDet) {
      await fetch('/api/tag', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          det_id: selectedDet.det_id,
          cx: selectedDet.cx, cy: selectedDet.cy,
          fx: selectedDet.fx, fy: selectedDet.fy,
          jersey: jersey,
          time_min: currentTime,
          waseda: selectedDet.waseda,
        })
      });
      document.getElementById('jersey-input-wrap').style.display = 'none';
      selectedDet = null;
      document.getElementById('info-box').textContent = `#${jersey}をタグ付けしました`;
      await loadTags();
      await loadFrame(currentTime);
    }
  } else if (e.key === 'Escape') {
    document.getElementById('jersey-input-wrap').style.display = 'none';
    selectedDet = null;
  }
});

document.getElementById('time-slider').addEventListener('input', function() {
  loadFrame(parseFloat(this.value));
});

function seekRel(delta) {
  const newT = Math.max(0, Math.min(maxTime, currentTime + delta));
  document.getElementById('time-slider').value = newT;
  loadFrame(newT);
}

(async () => {
  await loadVideoInfo();
  await loadTags();
  await loadFrame(0.5);
})();
</script>
</body>
</html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--match", required=True)
    ap.add_argument("--port", type=int, default=5050)
    args = ap.parse_args()

    global _match_id, _tags_path
    _match_id  = args.match
    _tags_path = DATA_TZI / f"match_{args.match}" / "manual_tags.json"

    if _tags_path.exists():
        _tags[args.match] = json.loads(_tags_path.read_text())
        print(f"  [tag] loaded {len(_tags[args.match])} existing tags from {_tags_path}")
    else:
        _tags[args.match] = {}

    print(f"\n  TZI Tag Tool — match {args.match}")
    print(f"  Open: http://localhost:{args.port}/")
    print(f"  Tags: {_tags_path}\n")
    app.run(host="0.0.0.0", port=args.port, debug=False)


if __name__ == "__main__":
    main()
