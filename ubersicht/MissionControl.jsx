// ============================================================
// Daily Mission Control — Übersicht Widget v3
// 変更点:
//   - 全体サイズ半減（パディング・余白を圧縮）
//   - 小さいラベル文字 → 現在ゾーンの色を継承（A案）
//   - 区切り線・バー・パーセント表示もゾーン色に統一
//   - ゾーンサウンド・25分タイマー継続
// ============================================================

export const command = `
TIME=$(date '+%H:%M:%S')
H=$((10#$(date '+%H')))
M=$((10#$(date '+%M')))
S=$((10#$(date '+%S')))

# ゾーン切り替えサウンド（開始時刻の :00:00 に Glass を鳴らす）
if [ "$M" -eq 0 ] && [ "$S" -eq 0 ]; then
  case "$H" in
    0|4|5|9|21|22) afplay /System/Library/Sounds/Glass.aiff >/dev/null 2>&1 & ;;
  esac
fi

# ポモドーロ 25分: :25:00 と :50:00 に Ping ＋ 時計アプリ起動
if [ "$S" -eq 0 ] && [ "$M" -ne 0 ] && [ $((M % 25)) -eq 0 ]; then
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

const ZONES = [
  { start: 0,  end: 4,  color: "#718096", label: "睡眠中",        icon: "🌙", body: "7h睡眠確保。脳と体を回復。デバイスをオフに。" },
  { start: 4,  end: 5,  color: "#38a169", label: "朝ルーティン",  icon: "🏃", body: "起床→水→ストレッチ→外気→今日のインテンション設定。" },
  { start: 5,  end: 9,  color: "#5a67d8", label: "集中ブロック",  icon: "⚡", body: "最重要タスク優先。通知OFF。25分ポモドーロで実行。" },
  { start: 9,  end: 21, color: "#dd6b20", label: "アクティブデイ", icon: "🎯", body: "商談・会議・一問一答。外部対応この時間に集約。21時締切。" },
  { start: 21, end: 22, color: "#2b6cb0", label: "翌日準備",      icon: "📋", body: "翌日ToDo確定→デジタルデトックス→入浴→読書。" },
  { start: 22, end: 24, color: "#718096", label: "睡眠中",        icon: "🌙", body: "デバイスをオフ。良質な睡眠が翌日パフォーマンスを決める。" },
];

const pad = n => String(n).padStart(2, "0");

export const render = ({ output }) => {
  if (!output) return <div />;
  const time = output.trim();
  const [h, m, s] = time.split(":").map(Number);
  const zone = ZONES.find(z => h >= z.start && h < z.end) || ZONES[0];

  // ゾーン色を継承したラベルスタイル（A案）
  const L = {
    fontSize: 9,
    color: zone.color,
    letterSpacing: "0.12em",
    margin: "0 0 2px",
    textTransform: "uppercase",
    fontWeight: 700,
  };

  // ゾーン色の薄い区切り線
  const divider = {
    borderTop: `0.5px solid ${zone.color}33`,
    marginTop: 6,
    paddingTop: 6,
  };

  // 21:00デッドライン残り
  let secs = 21 * 3600 - (h * 3600 + m * 60 + s);
  if (secs < 0) secs += 86400;
  const dH = Math.floor(secs / 3600);
  const dM = Math.floor((secs % 3600) / 60);
  const dS = secs % 60;
  const urgent = dH < 2 && h >= 9 && h < 21;

  // アクティブデイ進捗
  const dayStart = 9 * 3600, dayEnd = 21 * 3600;
  const nowSec = h * 3600 + m * 60 + s;
  const dayPct = Math.min(100, Math.max(0, Math.round((nowSec - dayStart) / (dayEnd - dayStart) * 100)));

  // ポモドーロ 25分
  const pomSec = (m % 25) * 60 + s;
  const pomPct = Math.round(pomSec / 1500 * 100);
  const pomRemM = Math.floor((1500 - pomSec) / 60);
  const pomRemS = (1500 - pomSec) % 60;

  return (
    <div style={{
      background: "rgba(8, 8, 18, 0.9)",
      backdropFilter: "blur(20px)",
      WebkitBackdropFilter: "blur(20px)",
      borderRadius: 12,
      padding: "10px 14px",
      minWidth: 210,
      border: `0.5px solid ${zone.color}44`,
      boxShadow: `0 6px 24px rgba(0,0,0,0.5), 0 0 10px ${zone.color}18`,
    }}>

      {/* ヘッダー */}
      <p style={{ ...L, margin: "0 0 5px" }}>DAILY MISSION CONTROL</p>

      {/* 現在時刻 */}
      <p style={{ fontSize: 34, fontWeight: 200, color: "#fff", margin: 0, letterSpacing: "0.04em", fontVariantNumeric: "tabular-nums", lineHeight: 1 }}>
        {time}
      </p>

      {/* 現在のゾーン */}
      <div style={divider}>
        <p style={L}>現在のゾーン</p>
        <p style={{ fontSize: 13, color: zone.color, fontWeight: 600, margin: 0 }}>{zone.icon} {zone.label}</p>
      </div>

      {/* 21:00デッドライン */}
      <div style={divider}>
        <p style={L}>21:00 DEADLINE</p>
        <p style={{ fontSize: 24, fontWeight: 500, color: urgent ? "#fc5c5c" : "#fff", margin: 0, fontVariantNumeric: "tabular-nums", lineHeight: 1 }}>
          {pad(dH)}:{pad(dM)}:{pad(dS)}
        </p>
      </div>

      {/* アクティブデイ進捗 */}
      <div style={{ marginTop: 6 }}>
        <p style={L}>アクティブデイ進捗</p>
        <div style={{ height: 3, background: "rgba(255,255,255,0.1)", borderRadius: 2, overflow: "hidden" }}>
          <div style={{ height: "100%", width: `${dayPct}%`, background: zone.color, borderRadius: 2 }} />
        </div>
        <p style={{ fontSize: 10, fontWeight: 700, color: zone.color, margin: "2px 0 0", fontVariantNumeric: "tabular-nums" }}>
          {dayPct}%
        </p>
      </div>

      {/* ポモドーロ */}
      <div style={divider}>
        <p style={L}>ポモドーロ 25min</p>
        <div style={{ height: 3, background: "rgba(255,255,255,0.1)", borderRadius: 2, overflow: "hidden" }}>
          <div style={{ height: "100%", width: `${pomPct}%`, background: zone.color, borderRadius: 2, opacity: 0.65 }} />
        </div>
        <p style={{ fontSize: 10, fontWeight: 700, color: zone.color, margin: "2px 0 0", fontVariantNumeric: "tabular-nums" }}>
          次まで {pad(pomRemM)}:{pad(pomRemS)}
        </p>
      </div>

      {/* 本文（ゾーンミッション）— 最終行 */}
      <div style={{ ...divider, borderTopColor: `${zone.color}1a` }}>
        <p style={{ fontSize: 9, color: `${zone.color}cc`, margin: 0, lineHeight: 1.6, letterSpacing: "0.02em" }}>
          {zone.body}
        </p>
      </div>

    </div>
  );
};
