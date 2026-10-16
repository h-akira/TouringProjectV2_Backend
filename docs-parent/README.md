# docs

TouringProjectV2 の要件定義と基本設計の現行版。

## 位置づけ

- ここにあるのが、いまの正。変えるときはここを直し、なぜ変えたかを [adr/](../adr/README.md) に書く。
- [init/](init/README.md) は初期検討のスナップショットで、編集しない。最初からどう変わったかは、ここと比べれば分かる。
- スライスごとの設計は [specs/](specs/)、実装計画は [plans/](plans/) に置く。

## 概要

バイクでツーリング中のライダーが、インカムのボタンと声だけで AI に質問できる Android アプリ。
AI は現在地と進行方向を踏まえて答え、質問と回答は走ったルートとともに記録に残り、あとで地図で振り返れる。

## 目次

| 文書 | 中身 |
|---|---|
| [01_requirements.md](01_requirements.md) | 要件定義（利用者・ユーザーストーリー・機能／非機能要件・やらないこと・未確定事項） |
| [02_screen_list.md](02_screen_list.md) | 画面一覧 |
| [03_screen_transition.md](03_screen_transition.md) | 画面遷移図 |
| [04_detailed_requirements.md](04_detailed_requirements.md) | 詳細要件（`US-A-01.001` 形式の、判定できる条件） |
| [05_technical_policies.md](05_technical_policies.md) | 技術方針（全体構成・各レイヤーの方針・技術選定） |
| [06_units_definition.md](06_units_definition.md) | ユニットの定義（App・Backend・Agent・CICD の責務） |
| [07_units_contracts.md](07_units_contracts.md) | ユニット間の契約 |
| [mock/index.html](mock/index.html) | 画面モック（見た目・文言と、画面ごとの仕様メモ） |

## 書き分け

- 01・05 は方針の粒度にとどめ、数値や細部は書かない。
- 条件と数値は 04、画面の見た目と振る舞いはモック、ユニット間で揃える値は 07 に書く。

## モック

`mock/index.html` をブラウザで開く。地図の表示にはインターネット接続が要る。左の画面一覧と上の状態の切り替えで各画面を見られ、右に仕様メモが出る。データはすべて架空のもの。
