# TouringProjectV2_Backend

TouringProjectV2 の API（API Gateway＋Lambda・Python・SAM・`ap-northeast-1`）。
App から質問（PCM の音声か文字）と位置と進行方位を受け付け、文字起こし・住所の確定・Agent の呼び出し・読み上げ音声の生成を行い、結果を返す。進行方位は App が走行のルートから求めて送る（親の adr/0013）。
走行・ルート・メモ・地点メモ・質問できなかった地点と、それらの削除を受け取り、ユーザー名ごとに置く。引き継ぎのときは、ユーザーの記録をページ送りで返す。
プロジェクト全体の要件・方針・契約は [docs-parent/](docs-parent/README.md)（親リポジトリの写し。編集しない）。

## 構成

| 場所 | 中身 |
|---|---|
| `docs-parent/07a_openapi.yaml` | Android ↔ Backend の API 仕様（親の `docs/07a_openapi.yaml` の写し。正本は親） |
| `template.yaml`・`samconfig.toml` | SAM（スタック `stack-trv2-dev-backend`） |
| `src/handlers/` | `health`・`ask`（`POST /asks`）・`result`（`GET /asks/{askId}`）・`ask_edit`（`PUT /asks/{askId}/memo`・`PUT /asks/{askId}/offline`・`DELETE /asks/{askId}`）・`worker`（SQS）・`rides`（`/rides/{rideId}` の `PUT`・`DELETE`、`PUT /rides/{rideId}/route/{seq}`、`/rides/{rideId}/notes/{noteId}` の `PUT`・`DELETE`）・`transcriptions`（`POST /transcriptions`・`GET /transcriptions/{transcriptionId}`）・`records`（`GET /records`） |
| `src/lib/` | 入力の検証（質問と音声は `request`・走行とメモは `rides`・地点メモは `notes`・質問できなかった地点は `offline`）・方位・プロンプト・住所・記録（削除の跡を含む）・読み出す形（`records`）・会話の時間・Agent・音声合成・文字起こし |
| `scripts/smoke.py` | デプロイ後の通しの確認 |

## 流れ

1. `POST /asks` が入力を検証し、録音を S3（`audio/`・1日で消える）に置き、記録を `pending` で作り、SQS に積む。会話を区切る時刻を SSM `/trv2/dev/conversation-reset-minutes`（既定15・55以下）から求めて返す。SQS に積めなかったときは、記録と録音を消して 503 を返す（App は通信の失敗として扱う）。会話の記録（`CONV#`）は TTL（`expiresAt`）で1日後に消える。
2. worker が受け持ちを獲得し（条件付き書き込み）、文字起こし（ストリーミング）→ 住所（Location Service）・方位（App の `headingDegrees`。無ければ古い形の `headingSample` から求める。0.1度に丸め、360は0）・日時 → Agent（us-east-1・`runtimeSessionId` はユーザー名と会話の識別子から作る SHA-256）→ Polly（Kazuha・DRC と +6dB）の順に処理し、記録を `completed` か `failed` にする。
3. App は `GET /asks/{askId}` をポーリングし、回答の文と音声の署名付き URL（10分有効）を受け取る。質問できなかった地点を問い合わせると、状態は `offline` になる。
4. 走行: App は走行のメタ情報（走行のメモを含む）を `PUT /rides/{rideId}` で、ルートの点を300点までのかたまりにして `PUT /rides/{rideId}/route/{seq}` で置く。メタ情報は `updatedAt` が保存済みより新しいときだけ上書きする（古ければ `applied: false` の 200）。
5. メモと地点メモ: 会話のメモは `PUT /asks/{askId}/memo`、地点メモは `PUT /rides/{rideId}/notes/{noteId}` で置く。どちらも `updatedAt` が新しいときだけ書く。地点メモの住所は最初に受けたときに質問と同じ求め方で決め、方位は最初に受けた App の値を残して返す。
6. 削除: `DELETE` を受けると、先に削除の跡（`DELETED#<ASK|RIDE|NOTE>#<id>`・期限なし）を書いてから消す。走行を消すと、ルート・地点メモ・その走行の質問も消し、地点メモと質問にも跡を残す。跡のある記録（と、跡のある走行の下の記録）への `PUT` は、書き込みと跡の確かめを1つのトランザクションにして、書かずに 410 を返す。
7. 質問できなかった地点: App は、Backend に届かなかった質問の日時・位置・方位を、自分で作った `askId` で `PUT /asks/{askId}/offline` に置く。`status: "offline"` の質問として、地点メモと同じく位置・住所・方位を最初に決め、あとの版では変えない。メモと削除は、ほかの質問と同じ経路を使う。
8. 引き継ぎ: `GET /records` が、ユーザーのパーティションを強い一貫性でソートキーの順に読み、走行・ルート・地点メモ・質問・削除の跡を `kind` つきで返す。1ページは1回の問い合わせ（最大1MB）で、続きは `cursor` で読む（`cursor` には続きのソートキーだけを入れ、パーティションは `x-user-name` から作る）。
9. 地点メモの声: `POST /transcriptions` が録音を S3 に置いて SQS に積み、worker が文字起こしだけを行う（AI と読み上げは呼ばない）。App は `GET /transcriptions/{transcriptionId}` をポーリングする。記録は DynamoDB の TTL（`expiresAt`）で1日後に消える。

## テスト

```sh
python3 -m venv env && env/bin/pip install -r requirements-dev.txt
env/bin/pytest
```

## デプロイ

前提: Agent がデプロイ済みで、SSM `/trv2/dev/agent-runtime-arn`（東京）がある。

SSM のパラメーターの名前（`AgentRuntimeArn`・`ConversationResetParameter`）は、テンプレートに既定値を持たせず、`samconfig.toml` の環境ごとの `parameter_overrides` で渡す。別の環境を作るときは、その環境の名前（`/trv2/<環境>/...`）を書いた設定を足す。渡し忘れると、デプロイがエラーで止まる。

```sh
AWS_PROFILE=touring sam build && AWS_PROFILE=touring sam deploy
AWS_PROFILE=touring env/bin/python scripts/smoke.py
```

接続キー（App の設定に入れる値）は次で読む。表示された値はコミットしない。

```sh
KEY_ID=$(AWS_PROFILE=touring aws cloudformation describe-stacks --region ap-northeast-1 --stack-name stack-trv2-dev-backend \
  --query "Stacks[0].Outputs[?OutputKey=='ApiKeyId'].OutputValue" --output text)
AWS_PROFILE=touring aws apigateway get-api-key --region ap-northeast-1 --api-key "$KEY_ID" --include-value --query value --output text
```

## 運用

- 会話を区切る時間を変える: `aws ssm put-parameter --name /trv2/dev/conversation-reset-minutes --type String --overwrite --value <分>`（60秒以内に反映）
- 段ごとの所要時間: CloudWatch の `/aws/lambda/lambda-trv2-dev-worker` の `ask_done` の行（`durationsMs`）
