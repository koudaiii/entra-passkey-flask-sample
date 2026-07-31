# entra-passkey-flask-sample

Microsoft Entra External ID でサインインし、[パスキー (FIDO2)](https://learn.microsoft.com/en-us/entra/external-id/customers/how-to-sign-in-with-passkey) を
登録、一覧、削除できる最小構成の Flask アプリ。

パスキーの操作は Microsoft Graph beta の
[fido2AuthenticationMethod](https://learn.microsoft.com/en-us/graph/api/resources/fido2authenticationmethod?view=graph-rest-beta)
をサーバ側から呼んでいる。

## パスキーとは

**パスキー (Passkey)** は、パスワードを置き換える FIDO2/WebAuthn 標準ベースの認証方式。
公開鍵暗号を使い、次の2つを1組にして扱う。

- **秘密鍵**: ユーザーのデバイス（スマホ、PC、セキュリティキー等）の中だけに存在し、外に出ない
- **公開鍵**: サインイン先のサービス（今回は Entra External ID テナント）に登録される

サインイン時はサービスが出した「チャレンジ（ランダム値）」に対して、デバイスが生体認証や
PIN でユーザー本人を確認したうえで秘密鍵で署名し、サービス側が公開鍵で検証する。
パスワードのようにサーバへ送る「共有の秘密」自体が存在しないため、フィッシングや
パスワード使い回しや漏えいの影響を受けない。iCloud キーチェーンや Google パスワード
マネージャーなどを介して複数デバイス間で同期させることもできる。

## 全体アーキテクチャ

登場人物は3つ。

- **ブラウザ**: WebAuthn API (`navigator.credentials.create()`) を呼び、秘密鍵の生成と署名を
  デバイスの認証器（Touch ID、Windows Hello、セキュリティキー等）に委譲する
- **このアプリ (Flask)**: ユーザーのサインインを保持しつつ、パスキーの登録、一覧、削除を
  Microsoft Graph に取り次ぐ。**秘密鍵にもパスワードにも一切触れない**
- **Microsoft Graph / Entra External ID**: 公開鍵（パスキー）の実体を保管する
  Relying Party（依拠当事者）。ユーザーのサインインとパスキー管理 API 双方の認可を担う

```
+--------------+        WebAuthn API        +------------------+
|   Browser    | <------------------------> |  Authenticator   |
| (JavaScript) |  navigator.credentials.*   | (Touch ID, etc.) |
+--------------+                            +------------------+
       | HTTPS (this app serves a subdomain of rp.id itself)
       v
+----------------------------------+   delegated user token   +----------------------+
| Flask app                        |------------------------> | Entra External ID    |
| (local :3000)                    | <------------------------| (sign-in)            |
|                                  |                          +----------------------+
| - /               : top page     |   app-only token         +----------------------+
| - /passkeys       : passkey UI   |------------------------> | Microsoft Graph beta |
| - /api/passkeys/* : Graph proxy  | <------------------------| fido2Methods API     |
+----------------------------------+   (passkey CRUD)         +----------------------+
```

このアプリでの役割分担:

- **サインイン**（ユーザー自身の認証）は `identity.flask.Auth` が MSAL 経由で行う。
  ユーザー委任のトークンを使い、`context["user"]["oid"]` で本人を特定する
- **パスキー管理**（登録、一覧、削除の API 呼び出し）は別系統で、
  アプリ専用トークン（client credentials フロー）を使って Graph を呼ぶ。
  ユーザーがサインインしていることを前提に、そのユーザーの `oid` に対する
  パスキーだけを操作する

## ローカル環境での全体図

パスキーの WebAuthn 検証はブラウザが「ページの origin と `rp.id`（Relying Party ID、
実質テナントのドメイン）が同一サイトであること」を要求するため、`localhost` では
動かせない。そのため、ローカルでも次の構成で **本物のテナントドメインのサブドメインを
HTTPS で自分自身から配信する**。

```
開発者のブラウザ
   │  https://auth.<subdomain>.ciamlogin.com:3000/passkeys
   ▼
/etc/hosts で 127.0.0.1 に固定
   │
   ▼
mkcert の自己署名証明書で HTTPS 終端
   │
   ▼
ローカルの Flask 開発サーバ (script/server)
   │  - サインイン確認 (identity.flask.Auth)
   │  - /api/passkeys/* をアプリ専用トークンで Graph に中継
   ▼
インターネット越しに実際の Entra External ID テナント / Microsoft Graph (beta) を呼ぶ
```

つまりローカル実行といっても、**認証、認可、Graph 呼び出しはすべて実物のクラウド**に対して
行われる。ローカルで差し替えているのは「配信元が `127.0.0.1` である」という点だけで、
それを `rp.id` と一致させるために hosts ファイルと mkcert 証明書を使っている。

## 必要なもの

- [uv](https://docs.astral.sh/uv/)
- [mkcert](https://github.com/FiloSottile/mkcert)（ローカル HTTPS 用。パスキーの登録には
  信頼された証明書が必要なため。インストール手順は「ローカルのセットアップ」に記載）
- Microsoft Entra 外部テナント（下記の手順で作成する）

## Entra 側のセットアップ

すべて [Microsoft Entra 管理センター](https://entra.microsoft.com) で行う。

> [!IMPORTANT]
> **手順 3 以降はすべて「外部テナントに切り替えた状態」で行う。**
> 管理センターは既定でサインインに使ったワークフォース テナント（勤務先の Entra ID）を
> 開いており、**アプリの登録**も**認証方法**も画面の見た目は外部テナントとほとんど同じ。
> 切り替えないまま作業すると、ワークフォース テナント側にアプリが登録されてしまい、
> `<subdomain>.ciamlogin.com` の authority ではサインインできない。
> 各手順の前に、右上の**設定**アイコン > **ディレクトリ + サブスクリプション** で
> 現在のディレクトリが手順 1 で作成した外部テナント（プライマリ ドメインが
> `<subdomain>.onmicrosoft.com`）になっていることを確認すること。

### 1. 外部テナントを作成する（切り替え前のテナントで行う）

**Entra ID** > **概要** > **テナントを管理** > **作成** > **外部**。
初めてなら Azure サブスクリプション不要の 30 日間無料試用版を選べる。作成には最大 30 分かかる。

→ [外部テナントの作成](https://learn.microsoft.com/ja-jp/entra/external-id/customers/how-to-create-external-tenant-portal)

### 2. テナントの詳細を控える

右上の**設定**アイコン > **ディレクトリ + サブスクリプション** で作成したテナントに**切り替え**、
**クイック ナビゲーション** > **テナントの概要** を開く。**テナント ID** と
**プライマリ ドメイン**（`<subdomain>.onmicrosoft.com`）を控える。

→ [外部テナントの詳細を取得する](https://learn.microsoft.com/ja-jp/entra/external-id/customers/how-to-create-external-tenant-portal#get-the-external-tenant-details)

### 3. アプリを登録する（外部テナント）

**手順 2 で切り替えた外部テナント上で行う。** ワークフォース テナントに登録しても
このアプリからはサインインできない。

**アプリの登録** > **新規登録**。サポートされるアカウントの種類は
**この組織のディレクトリ内のアカウントのみ**（単一テナント）を選ぶ。ここでいう
「この組織のディレクトリ」は外部テナントを指す。
**アプリケーション (クライアント) ID** を控える。

**証明書とシークレット** > **新しいクライアント シークレット** を作成し、**値**を控える
（この画面を離れると二度と表示されない）。

登録後、アプリの**概要**にある**ディレクトリ (テナント) ID** が手順 2 で控えた
テナント ID と一致していることを確認すると、テナントを間違えていないと分かる。

→ [外部テナントにアプリケーションを登録する](https://learn.microsoft.com/ja-jp/entra/external-id/customers/how-to-register-ciam-app) /
[アプリケーションの登録](https://learn.microsoft.com/ja-jp/entra/identity-platform/quickstart-register-app)

### 4. リダイレクト URI を登録する（外部テナント）

**認証** > **プラットフォームを追加** > **Web** に次を追加する。

```
https://auth.<subdomain>.ciamlogin.com:3000/getAToken
```

> [!IMPORTANT]
> パスキーの `rp.id` はテナントのドメイン（`<subdomain>.ciamlogin.com`）になり、ブラウザは
> ページの origin が `rp.id` と同一サイトであることを検証するため、`localhost` からは
> パスキーを登録できない。そのためアプリ自体を `auth.<subdomain>.ciamlogin.com` の
> HTTPS で配信する。

### 5. ユーザー フローを作成してアプリを紐づける（外部テナント）

**External Identities** > **ユーザー フロー** でサインアップとサインインのユーザー フローを作成し、
作成したアプリケーションを追加する。これがないとサインインできない。

→ [ユーザー フローの作成](https://learn.microsoft.com/ja-jp/entra/external-id/customers/how-to-user-flow-sign-up-sign-in-customers) /
[ユーザー フローにアプリケーションを追加する](https://learn.microsoft.com/ja-jp/entra/external-id/customers/how-to-user-flow-add-application)

### 6. パスキーを有効にする（外部テナント）

ここで出てくる **Entra ID** > **セキュリティ** はワークフォース テナントにも同じ画面があるため、
外部テナントに切り替わっているか特に間違えやすい。

- **Entra ID** > **セキュリティ** > **認証方法** > **ポリシー** > **パスキー (FIDO2)** を**有効**にし、対象ユーザーを指定する
- 同ポリシーの**構成**タブで「**セルフサービス セットアップを許可**」を**はい**にする。
  パスキー プロファイルでは種類に **Synced** と **Device-bound** の両方、
  **構成証明の強制**を**いいえ**にしておくと同期パスキーも使える
- アプリの登録 > **API のアクセス許可**で **`UserAuthMethod-Passkey.ReadWrite.All`** の
  **アプリケーション**許可を追加し、**管理者の同意を与える**

→ [パスキーでサインインする](https://learn.microsoft.com/ja-jp/entra/external-id/customers/how-to-sign-in-with-passkey)

### 7. 控えた値と `.env` の対応

| 控えた値 | `.env` |
|---|---|
| アプリケーション (クライアント) ID | `CLIENT_ID` |
| クライアント シークレットの**値** | `CLIENT_SECRET` |
| テナント ID | `TENANT_ID`、および `AUTHORITY` の末尾 |
| プライマリ ドメインの `<subdomain>` 部分 | `AUTHORITY` のホスト、`REDIRECT_URI` のホスト |

```env
CLIENT_ID="..."
CLIENT_SECRET="..."
AUTHORITY=https://<subdomain>.ciamlogin.com/<tenant-id>
REDIRECT_URI="https://auth.<subdomain>.ciamlogin.com:3000/getAToken"
TENANT_ID="<tenant-id>"
```

`TENANT_ID` はこのアプリ固有の追加項目。パスキー操作に使うアプリ専用トークンは
`ciamlogin.com` の authority では取得できず、`login.microsoftonline.com/<tenant-id>` を
使う必要があるため。

## ローカルのセットアップ

```bash
# 1. mkcert を入れて、ローカル CA をシステムのトラストストアに登録する
brew install mkcert
mkcert -install

# 2. .env を用意して、上で控えた **値** を埋める
cp .env.sample .env

# 3. 依存の同期と証明書の発行
script/bootstrap

# 4. hosts に追記（bootstrap が必要な行を表示する）
sudo sh -c 'echo "127.0.0.1  auth.<subdomain>.ciamlogin.com" >> /etc/hosts'

# 5. 起動
script/server
```

`mkcert -install` は一度やれば以降は不要。元に戻すときは `mkcert -uninstall`。

`script/server` が開くべき URL を表示する。

配信ホストとポートは `.env` の `REDIRECT_URI` から導出しているので、設定箇所はここ 1 か所だけ。
リダイレクト URI と配信 origin がずれないようにするため。一時的に変えたいときは
`PASSKEY_HOST` / `PORT` を環境変数で渡す。`.env` 自体は Flask CLI が
python-dotenv 経由で自動的に読み込む。

## API

すべてサインインが必要。操作対象のユーザーはトークンの `oid` から決まるため、
リクエストではユーザーを指定できない。

| Method | Path | 内容 |
|---|---|---|
| GET | `/passkeys` | 管理ページ |
| GET | `/api/passkeys` | 一覧 |
| GET | `/api/passkeys/creation-options` | WebAuthn の `publicKey` 作成オプション |
| POST | `/api/passkeys` | 登録 |
| DELETE | `/api/passkeys/<id>` | 削除 |

## 開発

```bash
script/test   # pytest
script/lint   # ruff check + format --check
```

`graph_passkeys.py` は Flask に依存しないため、`requests` をモックしてブラウザなしで
テストできる（`tests/test_graph_passkeys.py`）。カバーしているのは URL の組み立て、
Graph のネストしたエラー JSON の正規化、`displayName` 省略時の自動生成など。
Flask のルーティングと `login_required` を通した結線テストは `tests/test_passkeys_api.py`。
WebAuthn を伴う登録フロー全体は自動テスト対象外で、ブラウザでの手動確認としている。

## 構成

| ファイル | 役割 | 依存 |
|---|---|---|
| `app.py` | `auth.init_app(app)` + `register_blueprint` + 既存 `/` | 上記 |
| `auth.py` | `Auth(app=None, ...)` の生成のみ（循環 import を避けるため `ms-identity-python` の Application Factory パターンに従い、app.py とは別モジュールにしている） | identity |
| `graph_passkeys.py` | Graph の薄いクライアント。アプリトークン取得と CRUD 4関数。**Flask 非依存**で単体テスト可能 | msal, requests |
| `passkeys.py` | Blueprint。ルーティング、JSON 整形、エラー変換 | flask, auth, graph_passkeys |
| `templates/passkeys.html` | WebAuthn を呼ぶ素の JavaScript（React / Vite などのビルド環境は導入しない） | — |
| `script/_config` | `.env` の `REDIRECT_URI` からホストとポートを導出（bootstrap / server が source する） | — |

## 設計

### 目的と参照サンプルとの構成差

既存の Flask アプリ（`ms-identity-python` の `identity.flask.Auth` でサインイン済み）に、
ユーザー自身がパスキーを **登録、一覧、削除** できる最小限の JSON API と管理ページを追加している。
Microsoft は現時点でパスキー登録の組み込み UI を提供していないため、FIDO2 プロビジョニング API
（[fido2AuthenticationMethod](https://learn.microsoft.com/en-us/graph/api/resources/fido2authenticationmethod?view=graph-rest-beta)）
を使って自前で実装した。

参考にした [passkey-sample (React SPA)](https://github.com/Azure-Samples/ms-identity-ciam-native-javascript-samples/tree/main/passkey-sample)
は Graph をアプリ専用トークン（client credentials）で呼ぶために **client secret をブラウザに置き**、
トークンエンドポイントの CORS を回避するプロキシ（`cors.js`）を別プロセスで起動している。
本アプリは Flask = confidential client なので、client secret はサーバ側に留まり、CORS プロキシは
不要。アプリトークンのキャッシュも MSAL の内部キャッシュに任せている。

### フロー

```
Browser                          Flask                   Microsoft Graph (beta)
  |                                |                                |
  | GET /api/passkeys/creation-options                              |
  |------------------------------->|  app token (client credentials)|
  |                                |------------------------------->|
  |<- publicKey (passthrough) -----|<-- creationOptions ------------|
  |                                |                                |
  | navigator.credentials.create() |                                |
  |  (rp.id = <subdomain>.ciamlogin.com)                            |
  |                                |                                |
  | POST /api/passkeys             |                                |
  |------------------------------->|------------------------------->|
```

`creationOptions` の `challenge` / `user.id` / `excludeCredentials[].id` は Graph が base64url
文字列で返し、ブラウザが `ArrayBuffer` に変換する。登録時は逆方向で、ブラウザが
`attestationObject` / `clientDataJSON` を base64url 化した JSON を作る。したがって Flask は
**JSON を素通しするだけ**でよく、Python 側に base64 変換コードは持たない。

### `graph_passkeys.py` のインターフェース

Flask に依存せず、引数と戻り値だけで完結させている。

```python
def app_token() -> str
def list_passkeys(user_id: str) -> dict          # Graph の生レスポンス
def get_creation_options(user_id: str) -> dict   # publicKey の中身
def create_passkey(user_id: str, payload: dict) -> dict
def delete_passkey(user_id: str, passkey_id: str) -> None
```

Graph がエラーを返した場合は `GraphError(status_code, message)` を送出し、`passkeys.py` が
HTTP レスポンスに変換する。

すべての API は `@auth.login_required` で保護し、ユーザー ID は `context["user"]["oid"]`
から取得する（他人のパスキーを操作されるのを防ぐため、**リクエストからは受け取らない**）。

### `GET /api/passkeys` のレスポンス例

Graph の `value[]` から必要な項目のみを抜き出して返す。日付の整形はブラウザ側で行う。

```json
{
  "passkeys": [
    {
      "id": "...",
      "displayName": "passkey_1753...",
      "createdDateTime": "2026-07-30T01:23:45Z",
      "lastUsedDateTime": null,
      "model": "YubiKey 5",
      "aaGuid": "...",
      "attestationLevel": "notAttested",
      "passkeyType": "deviceBound"
    }
  ]
}
```

### `POST /api/passkeys` のリクエスト例

ブラウザから受け取った内容をそのまま Graph に渡す。

```json
{
  "publicKeyCredential": {
    "id": "...",
    "response": {
      "attestationObject": "<base64url>",
      "clientDataJSON": "<base64url>"
    }
  },
  "displayName": "my-yubikey"
}
```

`displayName` が省略された場合は `passkey_<unixtime>_<乱数6文字>` を生成する
（参照サンプルの `generateUniquePasskeyName` と同じ方針）。

### ブラウザ側 JS (`templates/passkeys.html`) の設計

参照サンプルから移植したのは以下の3点のみ。

1. `base64urlToBuffer` / `bufferToBase64url`（`graphServiceUtils.js` 相当）
2. **`decodeGraphCredentialId`**（Graph が返す `excludeCredentials[].id` は
   「base64url + 末尾にパディング数を表す数字1桁」という独自形式で、標準の base64url
   デコードでは壊れるため、`graphServiceUtils.js` の実装を移植した）
3. `rp.id` は `creationOptions.rp.id` をそのまま使う。参照サンプルは
   `appConfig.customDomain` で上書きできるようにしているが、本アプリでは creationOptions
   の値に従う（カスタム URL ドメインを後で設定した場合も自動追従する）

登録フロー: `GET /api/passkeys/creation-options` → `challenge`/`user.id`/`excludeCredentials[].id`
を `ArrayBuffer` に変換 → `navigator.credentials.create({ publicKey })` →
`attestationObject`/`clientDataJSON` を base64url 化して `POST /api/passkeys` → 一覧を再取得。

UI は一覧テーブル、「パスキーを追加」ボタン、各行の削除ボタン、エラー/成功メッセージ表示領域のみ。
削除確認モーダルやトースト通知は実装していない。

### エラー処理の設計

- **Graph のエラー**: `{"error": {"code": "...", "message": "..."}}` の `message` に
  odata エラーが JSON 文字列としてネストしていることがあるため、1段だけ剥がして
  `{"error": "<code>: <message>"}` に正規化し、Graph のステータスコードで返す。
  剥がせない場合は `message` をそのまま使う。
- **未認証時**: `@auth.login_required` は未認証時に **ログインページの HTML** を返す
  （302 ではない）。`fetch` から見ると JSON パースに失敗するため、JS 側で `content-type`
  を確認し、`application/json` でなければ「セッションが切れました」と表示する。
- **WebAuthn のエラー**: `navigator.credentials.create()` はユーザーキャンセル、
  タイムアウト、同一デバイスへの登録済みなどで例外を投げる。`NotAllowedError` は
  これらを区別できないため、まとめた文言で案内する（詳細は「トラブルシューティング」を参照）。

### スコープ外（意図的に未実装）

- **MFA (ngcmfa) ゲート**（参照サンプルは `claims` パラメータで `amr: ["ngcmfa"]` を要求し、
  トークンの `iat` から鮮度を判定しているが、本実装では省略している。
  `identity.flask.Auth` には認可リクエストへ `claims` を渡す口がなく
  （`log_in()` に claims 引数がなく、MSAL の `initiate_auth_code_flow` が持つ
  `claims_challenge` も転送していない）、また Graph はアプリトークンで呼ぶため
  ユーザーの MFA 状態を知り得ない。これは Entra が強制するものではなく
  **アプリの自主的なゲート**であり、将来入れる場合は `passkeys.py` の登録ハンドラと削除ハンドラの
  先頭に鮮度チェックを置く）。
- パスキー数の上限チェック（参照サンプルは 10）
- 登録後または削除後に一覧へ反映されるのを待つリトライ / バックオフ
- トースト通知、削除確認モーダル
- カスタム URL ドメインの設定の自動化（`rp.id` は creationOptions から読むため、設定した場合は
  hosts と証明書のホスト名を差し替えるだけでコード変更は不要）

## 制限

- MFA (ngcmfa) の鮮度チェックは未実装。Graph はアプリ専用トークンで呼ぶため
  Entra 側はユーザーの MFA 状態を判定できず、このゲートはアプリ側の実装事項になる。
- Graph beta API を使っているため、本番利用は非推奨。

## 本番運用に向けた検討事項

このリポジトリはローカル検証用の最小構成であり、そのまま本番投入すると以下が問題になる。

- **Graph beta API への依存**: `graph_passkeys.py` は `fido2Methods` を含め beta
  エンドポイントのみを呼んでいる。beta はスキーマや挙動が予告なく変わりうるため、
  本番では v1.0 への移行可否を継続的に確認するか、変更検知（スキーマの契約テストなど）を
  用意すること。
- **クライアント シークレットの扱い**: `.env` に平文でシークレットを置いている。
  本番では Azure Key Vault などのシークレット管理サービスに保管し、可能であれば
  クライアント シークレットではなく**証明書ベースの認証**（`client_credential` に
  証明書を渡す）に切り替える。シークレットのローテーション手順も用意すること。
- **TLS 証明書**: `mkcert` の自己署名証明書はローカル専用。本番では信頼された CA
  発行の証明書を使い、Flask の開発サーバではなく WSGI サーバ（gunicorn 等）を
  リバースプロキシ（nginx / Application Gateway 等）の背後で動かす。
- **セッションストレージ**: `flask_session` はデフォルトでファイルベースの
  セッションストア。複数インスタンスでのスケールアウトや再起動時の永続化を考えると、
  Redis 等の外部ストアに切り替える必要がある。
- **エラーメッセージの露出**: `_error_message` は Graph が返したエラーコードや
  メッセージをほぼそのまま JSON で返している。本番ではクライアントへの露出情報を
  絞り、詳細はサーバ側のログにのみ出す方が安全（情報漏えいの防止と攻撃者への手がかり抑制のため）。
- **管理者の同意の権限範囲**: `UserAuthenticationMethod.ReadWrite.All` は
  テナント内**全ユーザー**のパスキーを読み書きできる強い権限。本番では最小権限の
  原則に沿って、可能なら対象範囲を絞る、あるいはこの権限を持つアプリへのアクセスを
  厳格に制限する（監査ログや PIM などでの追加統制も検討）。
- **パスキー ポリシーの緩和設定**: 動作確認のため
  「構成証明の強制（Enforce attestation）」「キーの制限（Enforce key restrictions）」を
  無効にしている。本番では組織のセキュリティ要件に応じて、認定済み認証器のみ許可する、
  構成証明を要求するなど、ポリシーを見直すこと。
- **`enforceCredentialProtectionPolicy` のクライアント側上書き**: 「NotSupportedError」
  対策として `templates/passkeys.html` で `enforceCredentialProtectionPolicy` を
  `false` に上書きしている。これは Graph 側の暫定的な不整合に対する回避策であり、
  Microsoft 側の修正状況を継続的に確認し、不要になれば取り除くこと。
- **レート制限と監査ログ**: `/api/passkeys` 系エンドポイントにレート制限がない。
  総当たりや DoS への対策として API Management や WAF 等でのレート制限、
  および操作ログ（誰がいつ何を登録または削除したか）の記録を追加すること。
- **MFA 鮮度チェック未実装**（「制限」参照）: 本番でパスキー登録前に
  再認証（MFA の鮮度確認）を必須にする場合、アプリ側で別途実装が必要。

## トラブルシューティング / FAQ

### `creationOptions` (WebAuthn の `publicKey` 作成オプション) の JSON の見方

`GET /api/passkeys/creation-options` が返す JSON は、`navigator.credentials.create()` に
そのまま渡す WebAuthn の `PublicKeyCredentialCreationOptions` 相当。各項目の意味:

| フィールド | 意味 |
|---|---|
| `attestation` | 認証器の身元証明書の要求レベル（`direct` = 証明書そのものを要求） |
| `authenticatorSelection` | 使える認証器の条件。`authenticatorAttachment`（接続方式）、`requireResidentKey`（常駐/検出可能な資格情報を要求するか）、`userVerification`（生体認証などのユーザー確認を要求するか） |
| `challenge` | リプレイ攻撃防止用のランダム値（署名対象） |
| `excludeCredentials` | 既に登録済みの資格情報一覧（重複登録防止） |
| `extensions` | CTAP2 拡張機能。`credProtect`（`credentialProtectionPolicy`）は「この資格情報をどの保護レベルで扱うか」を認証器に指示するもの |
| `pubKeyCredParams` | 使用可能な署名アルゴリズム（`-7` = ES256、`-257` = RS256） |
| `rp` | 依拠当事者（Relying Party）＝このテナントのドメイン情報 |
| `user` | 登録対象ユーザーの情報 |

`extensions.enforceCredentialProtectionPolicy` は、指定した `credentialProtectionPolicy`
の保護レベルを認証器が満たせない場合に**登録自体を拒否させる**フラグ。

参考:
- [PublicKeyCredentialCreationOptions（W3C WebAuthn Level 3 仕様）](https://www.w3.org/TR/webauthn-3/#dictionary-makecredentialoptions)
- [fido2AuthenticationMethod: creationOptions（Microsoft Graph beta リファレンス）](https://learn.microsoft.com/en-us/graph/api/fido2authenticationmethod-creationoptions?view=graph-rest-beta)
- [CTAP2.1 credProtect extension（FIDO Alliance 公式仕様）](https://fidoalliance.org/specs/fido-v2.1-ps-20210615/fido-client-to-authenticator-protocol-v2.1-ps-20210615.html#sctn-credProtect-extension)

### `AADSTS50011: The redirect URI ... does not match the redirect URIs configured for the application`

`.env` の `REDIRECT_URI` と、Entra ポータルのアプリの登録 > **認証** >
**リダイレクト URI** に登録されている値が一字一句一致していない。ポート番号込みで
完全一致している必要がある。ポータル側に追加し保存すること（「Entra 側のセットアップ」の
手順 4 を参照）。

`/etc/hosts` を編集しても直らないように見える場合、原因はほぼ確実にこの登録漏れであり
hosts の設定ミスではないことが多い（`dig` は `/etc/hosts` を参照しないので、`dig` の
正引き結果が実在の Microsoft 側 IP に見えても異常ではない。ループバックへの向き先確認には
`ping` を使うこと）。

### サインインで `AADSTS700016: Application with identifier ... was not found in the directory`

アプリをワークフォース テナント（管理センターに最初から開いているテナント）に登録して
しまっている。管理センターの画面は外部テナントとほとんど同じで、切り替えを忘れても
そのまま作業できてしまうため起きやすい。

右上の**設定** > **ディレクトリ + サブスクリプション** で外部テナントに**切り替え**、
**アプリの登録**にそのアプリが見えるか確認する。見えなければ登録先を間違えているので、
外部テナント側で「Entra 側のセットアップ」の手順 3 以降をやり直す。アプリの**概要**の
**ディレクトリ (テナント) ID** が `.env` の `TENANT_ID` と一致しているかでも判別できる。

### パスキーの一覧取得や作成が `403 accessDenied: Request Authorization failed` になる

Graph の `fido2Methods` はアプリ専用トークン（クライアント クレデンシャル フロー）で
呼んでいるため、**アプリケーションの許可**（委任の許可ではない）が必要。

1. **外部テナントに切り替えた状態で**アプリの登録 > **API のアクセス許可** > **+ 追加** > **Microsoft Graph**
2. **「アプリケーションの許可」**（「委任されたアクセス許可」ではない）を選択
3. `UserAuthenticationMethod.ReadWrite.All`（または `UserAuthMethod-Passkey.ReadWrite.All`）を追加
4. **「[テナント名] に管理者の同意を与えます」**ボタンを押し、管理者の同意列が
   緑のチェックになることを確認

権限の**種類**が「委任済み」になっていると、サインインしていないアプリ専用トークンでは
機能しない。一覧の「種類」列で必ず「アプリケーション」になっているか確認すること。

権限を追加して同意した直後は、サーバ側の MSAL がアプリトークンをメモリ内キャッシュしている
ため、`script/server` を再起動してから試すこと（トークンは最大 1 時間再利用される）。

### パスキー作成が `NotSupportedError: Requested protection policy is inconsistent or incongruent with other requested parameters` になる

Graph の `creationOptions`（`navigator.credentials.create()` に渡す WebAuthn の
`publicKey` オプション一式）が、`authenticatorSelection.userVerification: "required"` を
要求しつつ、`extensions.credentialProtectionPolicy: "userVerificationOptional"`（要求レベルより
低い設定）を `enforceCredentialProtectionPolicy: true` で返すことがある。

- `credentialProtectionPolicy` は FIDO CTAP2 の `credProtect` 拡張で、資格情報に対して
  認証器がどの保護レベルを適用するかを指定する（レベル1: 保護なし〜レベル3: 常に UV 必須）。
- `enforceCredentialProtectionPolicy: true` は、認証器が指定レベルを満たせない場合に
  **登録自体を拒否させる**フラグ。

要求している `userVerification: "required"` と、指定している保護レベルが噛み合っていないため、
この矛盾を認証器に「強制」すると WebAuthn の `NotSupportedError` になる。

`templates/passkeys.html` の `add()` で、`enforceCredentialProtectionPolicy` を
クライアント側で `false` に上書きしてから `navigator.credentials.create()` に渡すことで
回避している。Entra / Graph 側の既知の挙動であり、アプリ側のコードでの対処が必要。

参考:
- [CTAP2.1 credProtect extension（FIDO Alliance 公式仕様）](https://fidoalliance.org/specs/fido-v2.1-ps-20210615/fido-client-to-authenticator-protocol-v2.1-ps-20210615.html#sctn-credProtect-extension)
- [WebAuthn credProtect: Security Keys（Corbado ブログ、ブラウザ間の挙動差の解説）](https://www.corbado.com/blog/webauthn-credprotect-security-keys)

### パスキー作成が `NotAllowedError`（「タイムアウト、キャンセル、またはこのデバイスに登録済みの可能性があります」）になる

WebAuthn の仕様上、ブラウザは NotAllowedError の詳細な理由（タイムアウト / ユーザーの
キャンセル / 対応する認証器がない、等）を JavaScript に渡さないため、これらをまとめて
案内している。実際の理由はブラウザの開発者コンソールの `console.error(error)` 出力
（`error.name` / `error.message`）で確認できる。

なお `authenticatorSelection.authenticatorAttachment: "cross-platform"` が指定されていても、
Mac 内蔵の Touch ID による **iCloud キーチェーンの同期パスキー**は登録できる
（複数デバイス間を移動できる「同期」認証器は cross-platform の条件を満たすため）。
除外されるのは同期されない、デバイス固定の認証器のみ。

### パスキー一覧で「最終使用」（`lastUsedDateTime`）が `-` のまま更新されない

Entra ID / Entra External ID (CIAM) 側の既知の制限。`lastUsedDateTime` は Graph beta の
比較的新しいプロパティで、パスキーで実際にサインインしても更新されないことがある
（CIAM テナントに限らず一般の Entra ID テナントでも報告あり）。アプリ側の実装の問題ではない。

実際のサインイン履歴を確認したい場合は、この値ではなく Entra ID の**サインイン ログ**を
参照すること。

→ [Last used data for authentication methods is now available on the Graph](https://www.michev.info/blog/post/7039/last-used-data-for-authentication-methods-is-now-available-on-the-graph)
