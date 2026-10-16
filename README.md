# TouringProjectV2_Backend

TouringProjectV2 の API（API Gateway＋Lambda・Python・SAM・`ap-northeast-1`）。
App から質問（PCM の音声か文字）と位置を受け付け、文字起こし・住所と方位の確定・Agent の呼び出し・読み上げ音声の生成を行い、結果を返す。
プロジェクト全体の要件・方針・契約は [docs-parent/](docs-parent/README.md)（親リポジトリの写し。編集しない）。

## 構成

| 場所 | 中身 |
|---|---|
| `openapi.yaml` | App ↔ Backend の API 仕様（正本） |
| `template.yaml`・`samconfig.toml` | SAM（スタック `stack-trv2-dev-backend`） |
| `src/handlers/` | `health`・`ask`（`POST /asks`）・`result`（`GET /asks/{askId}`）・`worker`（SQS） |
| `src/lib/` | 入力の検証・方位・プロンプト・住所・記録・会話の時間・Agent・音声合成・文字起こし |
| `scripts/smoke.py` | デプロイ後の通しの確認 |

## 流れ

1. `POST /asks` が入力を検証し、録音を S3（`audio/`・1日で消える）に置き、記録を `pending` で作り、SQS に積む。会話を区切る時刻を SSM `/trv2/dev/conversation-reset-minutes`（既定15・55以下）から求めて返す。
2. worker が受け持ちを獲得し（条件付き書き込み）、文字起こし（ストリーミング）→ 住所（Location Service）・方位・日時 → Agent（us-east-1・`runtimeSessionId` は会話の識別子）→ Polly（Kazuha・DRC と +6dB）の順に処理し、記録を `completed` か `failed` にする。
3. App は `GET /asks/{askId}` をポーリングし、回答の文と音声の署名付き URL（10分有効）を受け取る。

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
