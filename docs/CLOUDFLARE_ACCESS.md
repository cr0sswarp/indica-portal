# VALIENTE ポータル — Cloudflare Access 認証セットアップ

`portal.indica.jp` を **Cloudflare Access (Zero Trust)** で保護し、
許可したメンバーだけがログインして閲覧できるようにする手順。

静的サイト(GitHub Pages)にパスワードを直接埋め込む方式は原理的に安全では
ないため採用しない。Cloudflare Access はサイトのコードを一切変更せず、
エッジで「許可されたメールアドレスだけ」を通す。各メンバーは自分のメールに
届くワンタイムコード(または Google ログイン)で入る — 共有パスワード不要。

---

## 前提0: ドメインが Cloudflare 管理下にあるか確認する

Access はドメインが Cloudflare のネームサーバを向いている必要がある。

```bash
# ネームサーバを確認。*.ns.cloudflare.com が出れば Cloudflare 管理下。
dig NS indica.jp +short
# 例: NS が "xxx.ns.cloudflare.com" → OK / それ以外 → 前提1へ
```

- **Cloudflare が出た** → 「前提1」を飛ばして「ステップ1」へ。
- **別のネームサーバ** → 前提1でドメインを Cloudflare に移管する。

## 前提1: ドメインを Cloudflare に追加 (未移管の場合のみ)

1. https://dash.cloudflare.com → **Add a site** → `indica.jp` を入力。
2. プラン選択 (Free で可)。
3. Cloudflare が表示する2つのネームサーバを、ドメインレジストラ
   (お名前.com / Route53 等) の NS 設定に登録。
4. 反映まで数時間〜最大48h。`dig NS indica.jp +short` で確認。
5. 既存の `portal` レコード (GitHub Pages 向け CNAME/A) が Cloudflare 側に
   取り込まれていること、**Proxy status が「Proxied(オレンジ雲)」** であることを
   確認 (DNS-only では Access が効かない)。

> GitHub Pages の場合: `portal` の CNAME は `cr0sswarp.github.io` を指す。
> Cloudflare 側でこの CNAME を Proxied にすれば、GitHub Pages のまま Access で
> 保護できる(ホスティング移行は不要)。

---

## ステップ1: Zero Trust を有効化

1. ダッシュボード左メニュー **Zero Trust** を開く。
2. 初回はチーム名(例: `indicalab`)を設定 → `indicalab.cloudflareaccess.com` が
   ログイン用ドメインになる。Free プランで50ユーザーまで無料。

## ステップ2: ログイン方法 (Identity Provider) を設定

**Settings → Authentication → Login methods**

- 手軽: **One-time PIN** を有効化 (許可メールに6桁コードを送信。追加設定不要)。
- 推奨: **Google** を追加 (各自の Google アカウントで即ログイン)。
  - `makino@indicalab.jp` が Google Workspace なら相性が良い。

## ステップ3: チームを「グループ」として定義 (将来拡張の要)

メンバーを増やすたびにポリシーを書き換えないよう、**Access Group** に
メールを束ねる。

**Access → Access Groups → Add a group**

- Name: `valiente-team`
- Include → **Emails**:
  - `makino@indicalab.jp`
  - `<牧野羽瑠さんのメール>`  ← 後で追加
- 保存。

> 今後メンバーを増やすときは **このグループにメールを足すだけ**。
> 全アプリのポリシーに自動反映される。

## ステップ4: ポータルを保護する Access アプリケーションを作成

**Access → Applications → Add an application → Self-hosted**

- Application name: `VALIENTE Portal`
- Session Duration: `24h` (任意)
- **Application domain**: `portal.indica.jp` (パス無し = サイト全体)
- Next。

### ポリシー

- Policy name: `Allow VALIENTE team`
- Action: **Allow**
- Include → **Access groups** → `valiente-team` を選択。
- 保存 → アプリ作成完了。

## ステップ5: 動作確認

1. シークレットウィンドウで `https://portal.indica.jp` を開く。
2. Cloudflare のログイン画面が出る → 許可メールでコード/Google ログイン。
3. 認証後にポータルが表示されれば成功。
4. 許可していないメールでは弾かれることも確認。

### ログアウト用リンク (任意)

ポータル内に置けるログアウト URL:

```
https://indicalab.cloudflareaccess.com/cdn-cgi/access/logout
```

---

## メンバーの追加・削除 (運用)

- 追加: **Access Groups → valiente-team → Emails** にメールを足す。
- 削除: 同じ場所からメールを消す。即時反映。

## (任意) 設定をコードで管理したい場合

ダッシュボード操作の代わりに **Terraform (cloudflare provider)** で
Access アプリ・グループ・ポリシーを宣言し、メンバー追加を「コミット＋apply」
で行う運用も可能。チーム名簿を Git 履歴で管理できる。必要なら別途用意する。

---

## 補足: ポータル本体 (index.html) について

`index.html` は VALIENTE v3 テンプレートを基に実HTMLとして再構築済み
(クイックリンク / TZIフットボール分析ハブ / スキル・ツール)。Access は中身に
関わらずドメインを保護するため、この認証手順はそのまま適用できる。
