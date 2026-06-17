# 标普500&纳斯达克100 额度哨兵

每个 A 股交易日抓取标普500 / 纳指100 全部场外被动指数基金（52只人民币份额）的
申购限额，生成三类发帖素材——纯文字（通用文案）、纯图片（完整名单长图）、
纯视频（封面图 + 6 幕 TTS 播报视频，末幕滚动完整名单）——
推送到手机后人工花两分钟转发到各平台。

## 快速开始（本地）

```bash
pip install -r requirements.txt
python main.py --mock   # 先用模拟数据跑通流程（注意会覆盖当日 data/ 快照）
python main.py          # 真实抓取（需能访问天天基金）
python video.py         # 合成播报视频（edge-tts 配音，需联网）
```

产出在 `output/`，对应三类发布素材：
- `text_YYYY-MM-DD.txt` — 通用文案，不分平台
- `card_YYYY-MM-DD.png` — 完整名单长图（额度档位聚类，暂停基金折叠）
- `cover_YYYY-MM-DD.png` + `video_*.mp4` — 视频封面图 + 1080x1920 竖版
  播报视频（6 幕分镜：封面 → 标普500 → 纳指100 → 变动 → 落版 → 完整名单慢滚）

大数字字体用 `assets/fonts/` 下的 Barlow Condensed（OFL 开源），
缺失时自动回退中文粗体，不影响运行。

每日快照存在 `data/`，第二天自动对比生成「放宽 / 收紧」标记。

## 部署到 GitHub Actions（全自动生成 + 半自动发布）

1. 推送本仓库到 GitHub（Settings → Actions 确认启用）。
2. **调度方式**：`.github/workflows/daily.yml` 以**外部触发为主**。GitHub 内置的
   schedule cron 不保证准点（高峰期常延迟数十分钟甚至整批丢弃），因此改由一个你可控的
   外部调度器（cron-job.org / VPS crontab / 云函数等）每工作日北京 08:05 调用 GitHub API
   派发 `repository_dispatch`（事件类型 `daily-trigger`），触发延迟从数十分钟降到几秒。
   workflow 内仍保留少量周一至周五的 schedule 槽位作**兜底**，外部调度器宕机时接管。
   两条触发路径都走 `trading_day.py` 交易日判断 + 远端判重（当日已生成则跳过），幂等安全。

   **配置外部触发**（以 cron-job.org 为例）：
   - GitHub → Settings → Developer settings → **Fine-grained token**，授权本仓库
     `Contents: Read and write`，复制 `github_pat_...`。
   - cron-job.org 新建任务：URL
     `https://api.github.com/repos/<owner>/<repo>/dispatches`，方法 `POST`，
     Header `Authorization: Bearer <PAT>`、`Accept: application/vnd.github+json`，
     Body `{"event_type":"daily-trigger"}`，时区 Asia/Shanghai、周一至五 08:05 触发。
   - 成功返回 HTTP 204；到仓库 Actions 页可见来源 `repository_dispatch` 的运行。
3. 在仓库 Settings → Secrets and variables → Actions 配置推送通道（二选一或都配）：
   - `WECOM_WEBHOOK`：企业微信群机器人 webhook 完整 URL
     （企业微信群 → 右键 → 添加群机器人，个人可注册免费企业）
   - `TG_BOT_TOKEN` + `TG_CHAT_ID`：Telegram 机器人 token 与会话 ID
4. 运行后手机会依次收到三类素材：①纯文字文案 ②完整名单长图
   ③封面图 + 播报视频，转发即完成发布。产物同时上传为 Actions
   artifact（保留14天），当日快照自动 commit 回 `data/` 供次日对比。

手动测试：仓库 Actions 页面 → daily-quota-report → Run workflow
（手动触发会跳过交易日检查）。

### 为什么是半自动发布

- 微博有开放平台 API，后续最容易接全自动
- 抖音开放平台需企业资质；B站无官方动态/投稿 API；小红书基本无发布 API
  且对自动化行为打击严格 —— 这三家用非官方接口有封号风险
- 因此 MVP 先做「生成全自动 + 发布人工兜底」，账号验证了需求再逐平台升级

## 维护

- **基金名单**：`python update_funds.py` 从天天基金官方代码表重新生成
  `funds.py`（被动指数、场外、人民币份额；不要手工编辑名单）。
- **数据核对**：`python verify_quota.py` 用 F10 费率页对快照做双源核对
  （名称 / 代码 / 状态 / 限额逐只比对）。
- **解析失效**：页面改版导致解析失败时，原始 HTML 自动存入 `debug/`，
  据此更新 `fetcher.py`；解析锚定在页面「交易状态」区块内，不要改成全页搜索。

## 注意事项

1. **限额分渠道。** 天天基金展示的限额与蚂蚁财富、基金直销渠道可能不同；
   基金公司发调整公告当天，天天基金不同页面可能新旧值混杂，
   文案中已注明"以基金公司公告为准"。
2. **请求克制。** 每天只跑一次、请求间隔 2 秒，不要改成高频轮询。
3. **合规红线。** 内容只陈述公开的额度事实，不要在文案中加入任何
   买卖建议或收益预期；免责声明不要删。

## 下一步可做

- 限额变化时单独生成「⚠️额度放开」突发卡片（这是涨粉内容）
- 微博开放平台 API 自动发布
- 视频加背景音乐轨、片头动画
