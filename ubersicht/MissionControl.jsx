// Daily Mission Control v5 — コンパクト・ゾーン色鮮明版・ポモドーロ30分

export const command = `
TIME=$(date '+%H:%M:%S')
H=$((10#$(date '+%H')))
M=$((10#$(date '+%M')))
S=$((10#$(date '+%S')))
if [ "$M" -eq 0 ] && [ "$S" -eq 0 ]; then
  case "$H" in
    0|4|5|9|21|22) afplay /System/Library/Sounds/Glass.aiff >/dev/null 2>&1 & ;;
  esac
fi
if [ "$S" -eq 0 ] && [ $((M % 30)) -eq 0 ]; then
  afplay /System/Library/Sounds/Ping.aiff >/dev/null 2>&1 &
  open -a Clock >/dev/null 2>&1 &
fi
echo "$TIME"
`;

export const refreshFrequency = 1000;

export const className = `
  bottom: 28px;
  left: 28px;
  font-family: -apple-system, BlinkMacSystemFont, sans-serif;
  z-index: 100;
  cursor: default;
  user-select: none;
`;

// 明るい色に変更（視認性UP）
const ZONES = [
  { start: 0,  end: 4,  color: "#94a3b8", label: "睡眠中",        icon: "🌙", body: "7h睡眠確保。脳と体を回復。デバイスをオフに。" },
  { start: 4,  end: 5,  color: "#4ade80", label: "朝ルーティン",  icon: "🏃", body: "起床→水→ストレッチ→外気→今日のインテンション設定。" },
  { start: 5,  end: 9,  color: "#818cf8", label: "集中ブロック",  icon: "⚡", body: "最重要タスク優先。通知OFF。25分ポモドーロで実行。" },
  { start: 9,  end: 21, color: "#fb923c", label: "アクティブデイ", icon: "🎯", body: "商談・会議・一問一答。外部対応この時間に集約。21時締切。" },
  { start: 21, end: 22, color: "#60a5fa", label: "翌日準備",      icon: "📋", body: "翌日ToDo確定→デジタルデトックス→入浴→読書。" },
  { start: 22, end: 24, color: "#94a3b8", label: "睡眠中",        icon: "🌙", body: "デバイスをオフ。良質な睡眠が翌日パフォーマンスを決める。" },
];

const pad = n => String(n).padStart(2, "0");

export const render = ({ output }) => {
  if (!output) return <div />;
  const time = output.trim();
  const [h, m, s] = time.split(":").map(Number);
  const zone = ZONES.find(z => h >= z.start && h < z.end) || ZONES[0];
  const c = zone.color;

  // デッドライン残り
  let secs = 21 * 3600 - (h * 3600 + m * 60 + s);
  if (secs < 0) secs += 86400;
  const dH = Math.floor(secs / 3600);
  const dM = Math.floor((secs % 3600) / 60);
  const dS = secs % 60;
  const urgent = dH < 2 && h >= 9 && h < 21;

  // アクティブデイ進捗
  const nowSec = h * 3600 + m * 60 + s;
  const dayPct = Math.min(100, Math.max(0, Math.round((nowSec - 9*3600) / (12*3600) * 100)));

  // ポモドーロ
  const pomSec = (m % 30) * 60 + s;
  const pomPct = Math.round(pomSec / 1800 * 100);
  const pomRemM = Math.floor((1800 - pomSec) / 60);
  const pomRemS = (1800 - pomSec) % 60;

  const bar = (pct, color, opacity = 1) => (
    <div style={{ height: 3, background: "rgba(255,255,255,0.08)", borderRadius: 2, overflow: "hidden" }}>
      <div style={{ height: "100%", width: `${pct}%`, background: color, borderRadius: 2, opacity }} />
    </div>
  );

  return (
    <div style={{
      background: "rgba(6, 6, 16, 0.92)",
      backdropFilter: "blur(20px)",
      WebkitBackdropFilter: "blur(20px)",
      borderRadius: 11,
      padding: "7px 12px",
      minWidth: 215,
      border: `0.5px solid ${c}55`,
      boxShadow: `0 4px 20px rgba(0,0,0,0.6), 0 0 14px ${c}22`,
    }}>

      {/* ヘッダー */}
      <p style={{ fontSize: 8, color: c, fontWeight: 700, letterSpacing: "0.15em", textTransform: "uppercase", margin: "0 0 2px" }}>
        DAILY MISSION CONTROL
      </p>

      {/* 時刻（大） */}
      <p style={{ fontSize: 30, fontWeight: 200, color: "#fff", margin: 0, letterSpacing: "0.04em", fontVariantNumeric: "tabular-nums", lineHeight: 1 }}>
        {time}
      </p>

      {/* ゾーン + デッドライン — 1行 */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginTop: 4, paddingTop: 4, borderTop: `0.5px solid ${c}30` }}>
        <p style={{ fontSize: 12, color: c, fontWeight: 700, margin: 0 }}>{zone.icon} {zone.label}</p>
        <p style={{ fontSize: 16, fontWeight: 600, color: urgent ? "#f87171" : "#fff", margin: 0, fontVariantNumeric: "tabular-nums" }}>
          ▶ {pad(dH)}:{pad(dM)}:{pad(dS)}
        </p>
      </div>

      {/* 進捗バー2本 — 1ブロック */}
      <div style={{ marginTop: 5, paddingTop: 4, borderTop: `0.5px solid ${c}22` }}>
        {/* アクティブデイ */}
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 3 }}>
          <p style={{ fontSize: 8, color: c, fontWeight: 700, letterSpacing: "0.1em", textTransform: "uppercase", margin: 0, minWidth: 36 }}>DAY</p>
          <div style={{ flex: 1 }}>{bar(dayPct, c)}</div>
          <p style={{ fontSize: 9, color: c, fontWeight: 700, margin: 0, fontVariantNumeric: "tabular-nums", minWidth: 26, textAlign: "right" }}>{dayPct}%</p>
        </div>
        {/* ポモドーロ */}
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <p style={{ fontSize: 8, color: c, fontWeight: 700, letterSpacing: "0.1em", textTransform: "uppercase", margin: 0, minWidth: 36 }}>POM</p>
          <div style={{ flex: 1 }}>{bar(pomPct, c, 0.7)}</div>
          <p style={{ fontSize: 9, color: c, fontWeight: 700, margin: 0, fontVariantNumeric: "tabular-nums", minWidth: 26, textAlign: "right" }}>{pad(pomRemM)}:{pad(pomRemS)}</p>
        </div>
      </div>

      {/* 本文 — 最終行 */}
      <div style={{ marginTop: 4, paddingTop: 4, borderTop: `0.5px solid ${c}1a` }}>
        <p style={{ fontSize: 10, color: c, fontWeight: 500, margin: 0, lineHeight: 1.45, letterSpacing: "0.01em" }}>
          {zone.body}
        </p>
      </div>

    </div>
  );
};
