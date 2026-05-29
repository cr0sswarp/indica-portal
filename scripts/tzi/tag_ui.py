#!/usr/bin/env python3
"""
tag_ui.py — 選手手動タグ付けUI (Flask Web UI)

SSH ポート転送 (-L 8080:localhost:8080) でVast.aiに接続した状態で
ブラウザから http://localhost:8080 を開いて選手に背番号を割り当てる。

使い方:
  pip install flask
  python3 tag_ui.py                   # 前半 0秒目のフレーム
  python3 tag_ui.py --half 2          # 後半
  python3 tag_ui.py --sec 30          # 30秒時点のフレーム
"""
import argparse, base64, json, subprocess, threading
from pathlib import Path

import cv2, numpy as np
from flask import Flask, jsonify, render_template_string, request
from ultralytics import YOLO

from config import VIDEO_H1, VIDEO_H2, OUTPUT_DIR

TAGS_JSON = Path(__file__).parent / "tags.json"
MODEL     = Path(__file__).parent / "yolov8m.pt"
CONF      = 0.25
IMGSZ     = 1280
DEVICE    = "0"

app    = Flask(__name__)
_state = {"jpg": None, "boxes": [], "tags": {}, "fw": 1, "fh": 1,
          "frame_idx": 0, "log": []}


# ── フレーム検出 ────────────────────────────────────────────────
def detect_frame(video_path: Path, sec: float):
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    fidx = int(fps * sec)
    cap.set(cv2.CAP_PROP_POS_FRAMES, fidx)
    ret, frame = cap.read()
    cap.release()
    if not ret:
        raise RuntimeError(f"フレーム {fidx} を読み込めません")

    model   = YOLO(str(MODEL))
    results = model(frame, classes=[0], imgsz=IMGSZ, conf=CONF,
                    verbose=False, device=DEVICE)
    raw = results[0].boxes
    fh, fw = frame.shape[:2]

    boxes = []
    if raw is not None:
        for i, b in enumerate(raw.xyxy.cpu().numpy()):
            x1, y1, x2, y2 = map(int, b)
            boxes.append({"idx": i, "x1": x1, "y1": y1, "x2": x2, "y2": y2})
            cv2.rectangle(frame, (x1, y1), (x2, y2), (120, 120, 120), 1)
            cv2.putText(frame, str(i), (x1+3, y1+20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (180, 180, 180), 2)

    _, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 82])
    return base64.b64encode(jpg).decode(), boxes, fw, fh, fidx


# ── HTML ────────────────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>TZI 選手タグ付け</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#111;color:#eee;font-family:sans-serif;display:flex;height:100vh}
#left{flex:1;position:relative;overflow:hidden;display:flex;align-items:center;justify-content:center}
#frame-img{max-width:100%;max-height:100%;display:block}
.box{position:absolute;border:2px dashed #888;cursor:pointer;transition:border-color .15s,background .15s}
.box:hover{border-color:#0f0;background:rgba(0,255,0,.08)}
.box.tagged{border-color:#0af;border-style:solid}
.box-label{position:absolute;top:-22px;left:0;font-size:13px;font-weight:bold;
            background:#0af;color:#000;padding:1px 5px;border-radius:3px;white-space:nowrap}
#right{width:280px;background:#1a1a1a;display:flex;flex-direction:column;padding:16px;gap:12px;overflow-y:auto}
h2{font-size:15px;color:#aaa;margin-bottom:4px}
#tag-list{flex:1;overflow-y:auto}
.tag-row{display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid #333;font-size:14px}
.tag-row .num{background:#0af;color:#000;padding:2px 7px;border-radius:3px;font-weight:bold;min-width:36px;text-align:center}
.tag-row .box-id{color:#888;font-size:12px}
.del-btn{margin-left:auto;background:none;border:none;color:#f44;cursor:pointer;font-size:16px}
#btn-run{background:#0c8;color:#000;border:none;padding:10px;font-size:15px;border-radius:6px;cursor:pointer;font-weight:bold}
#btn-run:hover{background:#0fa}
#btn-combined{background:#08a;color:#fff;border:none;padding:8px;font-size:13px;border-radius:6px;cursor:pointer}
#log-box{background:#000;padding:8px;font-size:11px;height:180px;overflow-y:auto;border-radius:4px;color:#0f0}
#status{font-size:12px;color:#fa0;min-height:20px}
#popup{display:none;position:fixed;background:#222;border:1px solid #555;border-radius:8px;
       padding:16px;z-index:999;box-shadow:0 4px 20px #000}
#popup h3{margin-bottom:10px;font-size:14px}
#popup input{width:100%;padding:6px;background:#333;border:1px solid #555;color:#fff;
             border-radius:4px;font-size:18px;text-align:center}
#popup-btns{display:flex;gap:8px;margin-top:10px}
#popup-ok,#popup-del,#popup-cancel{flex:1;padding:6px;border:none;border-radius:4px;cursor:pointer;font-size:13px}
#popup-ok{background:#0c8;color:#000}
#popup-del{background:#f44;color:#fff}
#popup-cancel{background:#555;color:#fff}
</style>
</head>
<body>
<div id="left">
  <img id="frame-img" src="data:image/jpeg;base64,{{ jpg }}" alt="frame">
</div>
<div id="right">
  <div>
    <h2>選手タグ付け</h2>
    <p style="font-size:12px;color:#888;margin-top:4px">
      フレーム上のボックスをクリックして<br>背番号を入力してください
    </p>
  </div>
  <div id="tag-list"></div>
  <div id="status"></div>
  <button id="btn-combined" onclick="runPipeline('--combined')">▶ --combined (0-5min テスト)</button>
  <button id="btn-run" onclick="runPipeline('--full')">▶ --full (全試合 90分)</button>
  <div id="log-box"></div>
</div>

<div id="popup">
  <h3 id="popup-title">背番号を入力</h3>
  <input id="popup-input" type="number" min="1" max="99" placeholder="例: 6">
  <div id="popup-btns">
    <button id="popup-ok" onclick="popupOk()">決定</button>
    <button id="popup-del" onclick="popupDel()">削除</button>
    <button id="popup-cancel" onclick="popupClose()">キャンセル</button>
  </div>
</div>

<script>
const BOXES = {{ boxes|tojson }};
const FW = {{ fw }}, FH = {{ fh }};
let tags = {{ tags|tojson }};
let activeBoxIdx = null;

function scaleBoxes() {
  const img = document.getElementById('frame-img');
  const left = document.getElementById('left');
  const rect = img.getBoundingClientRect();
  const sx = rect.width / FW, sy = rect.height / FH;
  const ox = rect.left - left.getBoundingClientRect().left;
  const oy = rect.top  - left.getBoundingClientRect().top;

  document.querySelectorAll('.box').forEach(el => el.remove());
  BOXES.forEach(b => {
    const div = document.createElement('div');
    div.className = 'box' + (tags[b.idx] ? ' tagged' : '');
    div.style.left   = (ox + b.x1*sx) + 'px';
    div.style.top    = (oy + b.y1*sy) + 'px';
    div.style.width  = ((b.x2-b.x1)*sx) + 'px';
    div.style.height = ((b.y2-b.y1)*sy) + 'px';
    if (tags[b.idx]) {
      const lbl = document.createElement('div');
      lbl.className = 'box-label';
      lbl.textContent = '#' + tags[b.idx];
      div.appendChild(lbl);
    }
    div.addEventListener('click', () => openPopup(b.idx, b));
    document.getElementById('left').appendChild(div);
  });
}

function openPopup(idx, box) {
  activeBoxIdx = idx;
  const popup = document.getElementById('popup');
  const input = document.getElementById('popup-input');
  document.getElementById('popup-title').textContent =
    `ボックス ${idx} の背番号 (中央: ${Math.round((box.x1+box.x2)/2)}, ${Math.round((box.y1+box.y2)/2)})`;
  input.value = tags[idx] || '';
  popup.style.display = 'block';
  popup.style.left = '50%';
  popup.style.top  = '40%';
  popup.style.transform = 'translate(-50%,-50%)';
  input.focus();
  input.select();
}

function popupClose() {
  document.getElementById('popup').style.display = 'none';
  activeBoxIdx = null;
}

async function popupOk() {
  const val = document.getElementById('popup-input').value.trim();
  if (!val) { popupClose(); return; }
  const res = await fetch('/tag', {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({idx: activeBoxIdx, jersey: val})});
  const data = await res.json();
  tags = data.tags;
  popupClose();
  renderTagList();
  scaleBoxes();
}

async function popupDel() {
  const res = await fetch('/tag', {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({idx: activeBoxIdx, jersey: ''})});
  const data = await res.json();
  tags = data.tags;
  popupClose();
  renderTagList();
  scaleBoxes();
}

document.getElementById('popup-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') popupOk();
  if (e.key === 'Escape') popupClose();
});

function renderTagList() {
  const list = document.getElementById('tag-list');
  list.innerHTML = Object.keys(tags).length === 0
    ? '<p style="color:#666;font-size:13px">まだタグなし</p>'
    : Object.entries(tags).map(([idx, j]) =>
        `<div class="tag-row">
          <span class="num">#${j}</span>
          <span class="box-id">ボックス${idx}</span>
          <button class="del-btn" onclick="deleteTag('${idx}')">✕</button>
        </div>`).join('');
}

async function deleteTag(idx) {
  const res = await fetch('/tag', {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({idx: parseInt(idx), jersey: ''})});
  const data = await res.json();
  tags = data.tags;
  renderTagList();
  scaleBoxes();
}

async function runPipeline(mode) {
  await fetch('/save', {method:'POST'});
  document.getElementById('status').textContent = 'パイプライン起動中...';
  await fetch('/run', {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({mode})});
  pollLog();
}

function pollLog() {
  setTimeout(async () => {
    const res = await fetch('/log');
    const {log} = await res.json();
    const box = document.getElementById('log-box');
    box.textContent = log.join('\n');
    box.scrollTop = box.scrollHeight;
    if (log.some(l => l.includes('Google Drive'))) {
      const link = log.find(l => l.includes('https://'));
      document.getElementById('status').innerHTML =
        link ? `<a href="${link.trim()}" target="_blank" style="color:#0af">${link.trim()}</a>` : '完了';
    } else {
      pollLog();
    }
  }, 2000);
}

window.addEventListener('load', () => { scaleBoxes(); renderTagList(); });
window.addEventListener('resize', scaleBoxes);
</script>
</body>
</html>"""


# ── Flask ルート ────────────────────────────────────────────────
@app.route("/")
def index():
    from jinja2 import Template
    t = Template(HTML)
    return t.render(
        jpg=_state["jpg"],
        boxes=_state["boxes"],
        tags=_state["tags"],
        fw=_state["fw"],
        fh=_state["fh"],
    )


@app.route("/tag", methods=["POST"])
def tag():
    d = request.json
    idx = str(d["idx"])
    jersey = d.get("jersey", "").strip()
    if jersey:
        _state["tags"][idx] = jersey
    elif idx in _state["tags"]:
        del _state["tags"][idx]
    return jsonify({"tags": _state["tags"]})


@app.route("/save", methods=["POST"])
def save():
    result = {}
    for idx_s, jersey in _state["tags"].items():
        box = next((b for b in _state["boxes"] if str(b["idx"]) == idx_s), None)
        if box:
            result[jersey] = {
                "bbox":      [box["x1"], box["y1"], box["x2"], box["y2"]],
                "frame_idx": _state["frame_idx"],
            }
    TAGS_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return jsonify({"saved": str(TAGS_JSON), "players": list(result.keys())})


@app.route("/run", methods=["POST"])
def run():
    d = request.json or {}
    mode = d.get("mode", "--combined")
    cmd = ["python3", "tzi_pipeline_gpu.py",
           "--tags", str(TAGS_JSON), mode]
    _state["log"].clear()

    def _bg():
        proc = subprocess.Popen(
            cmd, cwd=str(Path(__file__).parent),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in proc.stdout:
            _state["log"].append(line.rstrip())

    threading.Thread(target=_bg, daemon=True).start()
    return jsonify({"started": True, "cmd": cmd})


@app.route("/log")
def log():
    return jsonify({"log": _state["log"][-80:]})


# ── main ────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--half", type=int, default=1, choices=[1, 2])
    parser.add_argument("--sec",  type=float, default=0.0,
                        help="タグ付けに使うフレームの秒数 (default: 0)")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    video = VIDEO_H1 if args.half == 1 else VIDEO_H2
    print(f"YOLO検出中 ({video.name} @ {args.sec:.0f}s) ...")
    jpg, boxes, fw, fh, fidx = detect_frame(video, args.sec)

    _state["jpg"]       = jpg
    _state["boxes"]     = boxes
    _state["fw"]        = fw
    _state["fh"]        = fh
    _state["frame_idx"] = fidx

    print(f"検出: {len(boxes)} 人")
    print(f"ブラウザで http://localhost:{args.port} を開いてください")
    app.run(host="0.0.0.0", port=args.port, debug=False)


if __name__ == "__main__":
    main()
