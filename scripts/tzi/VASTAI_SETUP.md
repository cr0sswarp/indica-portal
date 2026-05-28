# Vast.ai GPU セットアップ手順

## 1. アカウント作成・インスタンス起動

1. https://vast.ai にアクセス → Sign Up
2. クレジットカード登録（$10チャージで十分）
3. **Search** タブで以下の条件で検索:
   - **GPU**: RTX 4090（最安・高速）
   - **Disk**: 50GB 以上
   - **Image**: `pytorch/pytorch:2.1.0-cuda12.1-cudnn8-runtime`
4. 一番安いインスタンスを選んで **Rent** → **Launch**
5. **Connect** → **Open SSH** または **Jupyter** で接続

## 2. セットアップ実行

SSH接続後、以下を実行：

```bash
# リポジトリ取得
git clone https://github.com/cr0sswarp/indica-portal.git /workspace/indica-portal
cd /workspace/indica-portal

# セットアップスクリプト実行（約5分）
bash scripts/tzi/setup_vastai.sh
```

## 3. rclone Google Drive 設定

ローカルPCで認証を行い、設定ファイルをVast.aiに転送：

```bash
# ローカルPC で:
rclone config  # gdrive を設定済みの場合
rclone config file  # 設定ファイルのパスを確認
# 例: /Users/makino/.config/rclone/rclone.conf

# 設定ファイルをVast.aiにコピー (ローカルPCのターミナルで)
scp ~/.config/rclone/rclone.conf root@<vast_ai_ip>:/root/.config/rclone/
# または rclone の場合:
# rclone copyto ~/.config/rclone/rclone.conf remote:/path/  # NG
# 素直に scp か Jupyter の upload を使う
```

### 代替方法（Jupyter経由）

1. Vast.ai の Jupyter を開く
2. 左パネルからファイルをアップロード
3. ターミナルで:
```bash
mkdir -p /root/.config/rclone
mv /root/rclone.conf /root/.config/rclone/rclone.conf
rclone listremotes  # gdrive: が表示されればOK
```

## 4. 動画ダウンロード

```bash
cd /workspace/indica-portal
bash scripts/download_videos.sh
# → videos/ に前半・後半 mp4 がダウンロードされる
ls -la videos/
```

## 5. パイプライン実行

```bash
cd /workspace/indica-portal/scripts/tzi

# テスト: 前半0-5分 + 後半10-15分 (約10分で完了)
python3 tzi_pipeline_gpu.py --combined

# 前半全体 (45分処理, 約20分)
python3 tzi_pipeline_gpu.py --full

# 特定区間
python3 tzi_pipeline_gpu.py --half 1 --start 20 --dur 10
```

完了後に Google Drive リンクが自動表示されます。

## 6. 使用後はインスタンスを停止

**重要**: 使い終わったら必ずインスタンスを Destroy（削除）してください。
停止（Stop）ではなく **Destroy** = 課金停止。

Vast.ai ダッシュボード → **Instances** → **Destroy**

## コスト目安

| 処理内容 | GPU時間 | コスト |
|---|---|---|
| テスト（前半5分+後半5分） | ~10分 | ~$0.07 |
| 前半+後半 全体 | ~40分 | ~$0.27 |
| 月8試合（全体） | ~6時間 | ~$2.40 |

RTX4090: $0.40/hr 想定
