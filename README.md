# WhatToWear

一个小团队内部使用的“猜同事今天穿什么”Web 服务。它支持手机访问、成员注册登录、每日竞猜、动态赔率、实际着装记录、自动结算和奶茶积分榜。

## 功能

- 成员用昵称 + PIN 登录。
- 注册需要邀请码，管理员邀请码注册后拥有管理权限。
- 每日可选择一个或多个维度竞猜，截止前可修改。
- 内置上身、下身、外套、鞋子、发型、袜类等维度，并支持幽默选项。
- 管理员可在 Web 管理页维护竞猜维度和每个维度的选项。
- 管理员记录实际着装后，竞猜锁定并可结算。
- 赔率模型：按已选择维度组成竞猜池，使用历史加权命中率 + 池子大小贝叶斯先验。
- 多人猜中时按赔率权重瓜分猜错者积分。
- 全员猜中或全员猜错时当日作废，不产生积分变动。
- 竞猜时提供抽象实时效果图，颜色、款式、发型、鞋子等会随选择变化。
- 前端为响应式单页应用，兼容手机浏览器。

## 本地启动

```bash
python3 app.py
```

访问：

```text
http://127.0.0.1:8008
```

默认环境变量：

```text
PORT=8008
USER_INVITE_CODE=wear2026
ADMIN_INVITE_CODE=admin2026
SECRET_KEY=dev-change-this-secret
WHAT_TO_WEAR_DB=./data/what_to_wear.sqlite3
```

第一次注册的用户会自动成为管理员。生产环境建议显式设置 `SECRET_KEY`、`USER_INVITE_CODE` 和 `ADMIN_INVITE_CODE`。

## 部署

仓库内提供 systemd 服务模板：

```bash
sudo cp deploy/what-to-wear.service /etc/systemd/system/what-to-wear.service
sudo systemctl daemon-reload
sudo systemctl enable --now what-to-wear
```

默认监听 `0.0.0.0:8008`。
