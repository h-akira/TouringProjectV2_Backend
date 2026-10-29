# docs

TouringProjectV2 の要件定義・契約・基本設計の現行版。

## 位置づけ

- ここにあるのが、いまの正。変えるときはここを直し、なぜ変えたかを [adr/](../adr/README.md) に書く。
- 01〜08 には、いまの決定だけを書く。経緯（何をやめたか・いつ変えたか・どのスライスで入れたか）は書かない。理由が要るときは adr を参照する。使わなくなった番号は「（欠番）」とだけ書く。モックは付録なので、この限りでない。
- [init/](init/README.md) は初期検討のスナップショットで、編集しない。最初からどう変わったかは、ここと比べれば分かる。
- スライスごとの設計は [specs/](specs/)、実装計画は [plans/](plans/) に置く。どちらも書いた時点の記録で、いまの姿はここに書く。
- 全体レビューの報告は [final-review/](final-review/) に実施日ごとに置く。書いた時点の記録で、後から直さない（いまの正ではない）。

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
| [06_units_definition.md](06_units_definition.md) | ユニットの定義（Android・Backend・Agent・CICD の責務） |
| [07_units_contracts.md](07_units_contracts.md) | ユニット間の契約 |
| [07a_openapi.yaml](07a_openapi.yaml) | Android ↔ Backend の API 仕様（項目の名前・型の正本。Backend のテストが実装と合うことを確かめる） |
| [07b_datamodel.md](07b_datamodel.md) | データモデル（受け渡す記録の種類・識別子・関係・持ち主・新旧の決め方） |
| [08_design.md](08_design.md) | 基本設計（構成・ユニットをまたぐ主な流れ） |
| [08a_android-design.md](08a_android-design.md) | Android の基本設計 |
| [08b_backend-design.md](08b_backend-design.md) | Backend の基本設計 |
| [08c_agent-design.md](08c_agent-design.md) | Agent の基本設計 |
| [mock/index.html](mock/index.html) | 画面モック（見た目・文言と、画面ごとの仕様メモ） |

## 書き分け

- 01・05 は方針の粒度にとどめ、数値や細部は書かない。
- 条件と数値は 04、画面の見た目と振る舞いはモック、ユニット間で揃える値は 07、API の項目は 07a、記録の論理モデルは 07b に書く。
- 08 系は、人がコードを読まずに仕組みを掴むための基本設計。構成・流れ・部品の分け方・データの置き方を書き、クラスの中身・数値・手順は書かない（数値は 04・07・07a、手順は各ユニットの README）。
- 要件・契約・仕組みが変わったら、関わる文書を直して実装と食い違わないようにする。直したら `scripts/sync-docs.sh` で各ユニットに写す。

## モック

`mock/index.html` をブラウザで開く。地図の表示にはインターネット接続が要る。左の画面一覧と上の状態の切り替えで各画面を見られ、右に仕様メモが出る。データはすべて架空のもの。
