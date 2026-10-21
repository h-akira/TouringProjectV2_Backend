# TouringProjectV2_Backend

TouringProjectV2 の API（API Gateway＋Lambda・Python・SAM・`ap-northeast-1`）。
App から質問（PCM の音声か文字）と位置を受け付け、文字起こし・住所と方位の確定・Agent の呼び出し・読み上げ音声の生成を行い、結果を返す。
走行・ルート・メモ・地点メモと、それらの削除を受け取り、ユーザー名ごとに置く。
プロジェクト全体の要件・方針・契約は [docs-parent/](docs-parent/README.md)（親リポジトリの写し。編集しない）。

## 構成

| 場所 | 中身 |
|---|---|
| `openapi.yaml` | App ↔ Backend の API 仕様（正本） |
| `template.yaml`・`samconfig.toml` | SAM（スタック `stack-trv2-dev-backend`） |
| `src/handlers/` | `health`・`ask`（`POST /asks`）・`result`（`GET /asks/{askId}`）・`ask_edit`（`PUT /asks/{askId}/memo`・`DELETE /asks/{askId}`）・`worker`（SQS）・`rides`（`/rides/{rideId}` の `PUT`・`DELETE`、`PUT /rides/{rideId}/route/{seq}`、`/rides/{rideId}/notes/{noteId}` の `PUT`・`DELETE`）・`transcriptions`（`POST /transcriptions`・`GET /transcriptions/{transcriptionId}`） |
| `src/lib/` | 入力の検証（質問と音声は `request`・走行とメモは `rides`・地点メモは `notes`）・方位・プロンプト・住所・記録（削除の跡を含む）・会話の時間・Agent・音声合成・文字起こし |
| `scripts/smoke.py` | デプロイ後の通しの確認 |

## 流れ

1. `POST /asks` が入力を検証し、録音を S3（`audio/`・1日で消える）に置き、記録を `pending` で作り、SQS に積む。会話を区切る時刻を SSM `/trv2/dev/conversation-reset-minutes`（既定15・55以下）から求めて返す。
2. worker が受け持ちを獲得し（条件付き書き込み）、文字起こし（ストリーミング）→ 住所（Location Service）・方位・日時 → Agent（us-east-1・`runtimeSessionId` はユーザー名と会話の識別子から作る SHA-256）→ Polly（Kazuha・DRC と +6dB）の順に処理し、記録を `completed` か `failed` にする。
3. App は `GET /asks/{askId}` をポーリングし、回答の文と音声の署名付き URL（10分有効）を受け取る。
4. 走行: App は走行のメタ情報（走行のメモを含む）を `PUT /rides/{rideId}` で、ルートの点を300点までのかたまりにして `PUT /rides/{rideId}/route/{seq}` で置く。メタ情報は `updatedAt` が保存済みより新しいときだけ上書きする（古ければ `applied: false` の 200）。読み出しは後のスライス。
5. メモと地点メモ: 会話のメモは `PUT /asks/{askId}/memo`、地点メモは `PUT /rides/{rideId}/notes/{noteId}` で置く。どちらも `updatedAt` が新しいときだけ書く。地点メモの住所と方位は、最初に受けたときに質問と同じ求め方で決めて返す。
6. 削除: `DELETE` を受けると、先に削除の跡（`DELETED#<ASK|RIDE|NOTE>#<id>`・期限なし）を書いてから消す。走行を消すと、ルート・地点メモ・その走行の質問も消し、地点メモと質問にも跡を残す。跡のある記録（と、跡のある走行の下の記録）への `PUT` は、書き込みと跡の確かめを1つのトランザクションにして、書かずに 410 を返す。
7. 地点メモの声: `POST /transcriptions` が録音を S3 に置いて SQS に積み、worker が文字起こしだけを行う（AI と読み上げは呼ばない）。App は `GET /transcriptions/{transcriptionId}` をポーリングする。記録は DynamoDB の TTL（`expiresAt`）で1日後に消える。

## テスト

```sh
python3 -m venv env && env/bin/pip install -r requirements-dev.txt
env/bin/pytest
```

## デプロイ

前提: Agent がデプロイ済みで、SSM `/trv2/dev/agent-runtime-arn`（東京）がある。

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
