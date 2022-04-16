# miracron

## これは何
mirakc/Mirakurunの放送を定期録画するツールです。番組情報からcronルールを生成し、それに従ってwgetすることで定期録画を行います。

## 必要なもの
* mirakc/Mirakurunが動いているホスト
* DockerとDocker-composeが入っているホスト
    * ない場合は公式ドキュメントを参照しインストールしてください。
        * [Install Docker Engine \| Docker Documentation](https://docs.docker.com/engine/install/)
        * [Install Docker Compose \| Docker Documentation](https://docs.docker.com/compose/install/)
    * Dockerは必須ではありませんが、以降の手順は全てDockerがある前提で書かれています。

## インストール方法
インストール作業により以下2つのコンテナが作成されます。詳細はdocker-compose.ymlを参照してください。

1. cronルールをもとにmirakc/Mirakurunへwgetするコンテナ
1. 録画データを見るためのsambaコンテナ
    * smbdのみ動いています。nmbdが止まっているためホスト名でのアクセスはできません。IPアドレスでアクセスしてください。

``` shell
# 適当な作業フォルダを作成 (インストール完了後も使い続けるため消さないこと)
mkdir ~/miracron
cd ~/miracron
# 設定サンプルのダウンロード
curl --output config.yml https://raw.githubusercontent.com/maeda577/miracron/main/config-sample.yml
curl --output docker-compose.yml https://raw.githubusercontent.com/maeda577/miracron/main/docker/docker-compose.yml

# 録画ルールの編集
vi config.yml
# Docker関連の設定 (気になる所が無ければ飛ばしてもOK)
vi docker-compose.yml

# イメージのビルドとコンテナ起動
sudo docker compose up --detach

# 録画スケジュールの即時更新
sudo docker exec miracron miracron-update
# 録画スケジュールの出力結果を確認
sudo docker exec miracron miracron-show
# 録画閲覧用の共有ディレクトリへアクセスする際のパスワード変更
sudo docker exec -it miracron-samba pdbedit -a -u root
```

## 録画ルールの更新
config.ymlのルールはそれなりに書きにくいです。ルールの編集とスケジュール即時更新を細かく繰り返すと多少ましになります。

``` shell
# インストール時に作成した作業フォルダへ移動
cd ~/miracron
# 録画ルールの編集
vi config.yml
# 録画スケジュールの即時更新
sudo docker exec miracron miracron-update
# 録画スケジュールの出力結果を確認
sudo docker exec miracron miracron-show
```

## 録画済データの閲覧方法
録画データはSambaの共有ディレクトリで提供されます。WebGUIなどはありません。

適当なWindowsクライアントPCで `¥¥<miracronが動いているDockerホストのホスト側IP>¥recorded` を開いてください。macの場合は`smb://<miracronが動いているDockerホストのホスト側IP>/recorded`です。IDはroot、パスワードは（変えていない場合は）P@ssw0rd!です。

## アップデート方法
イメージを消してから再度起動してください。

``` shell
# インストール時に作成した作業フォルダへ移動
cd ~/miracron
# コンテナ停止と削除
sudo docker compose down
# イメージ削除
sudo docker image rm localhost/miracron:latest
sudo docker image rm localhost/miracron-samba:latest
# イメージのビルドとコンテナ起動
sudo docker compose up --detach
```

## アンインストール方法
ボリュームを削除すると録画データが全て削除されます。ご注意ください。

``` shell
# インストール時に作成した作業フォルダへ移動
cd ~/miracron
# コンテナ停止と削除
sudo docker compose down
# イメージ削除
sudo docker image rm localhost/miracron:latest
sudo docker image rm localhost/miracron-samba:latest
# ボリューム削除
sudo docker volume rm miracron_recorded
# 設定削除
cd ~/
rm -r ~/miracron
```
