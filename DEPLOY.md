# Railway 免费部署指南

## 1. 准备
- GitHub 账号
- 把 D:\WestTrailMusic\ 整个文件夹上传到 GitHub（新建一个私有仓库）

## 2. 部署
- 打开 railway.com，用 GitHub 登录
- 点击 New Project → Deploy from GitHub repo
- 选择你的仓库，Railway 自动检测 Dockerfile 并部署
- 等 2-3 分钟，拿到域名（如 xxx.up.railway.app）

## 3. 配置凭证
- 在 Railway 项目面板 → Variables → 无需额外变量
- 把 credential.json 也传到 GitHub（或后续通过登录 API 扫码获取）

## 4. 更新 APP 地址
- 打开 Flutter 项目 lib/main.dart
- 把 baseUrl 改成 https://xxx.up.railway.app
- 重新 flutter build apk

## 注意事项
- 免费额度每月 $5，个人使用足够
- 下载功能在服务端保存，手机端可以调用下载 API
- 如果不想暴露凭证，可以把 credential.json 加 .gitignore，部署后再上传
