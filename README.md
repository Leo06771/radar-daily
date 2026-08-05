# radar-daily

热点雷达云端每日更新：GitHub Actions 每天 07:00（Asia/Shanghai）抓取免费公开财经资讯源，按 v4 契约规则打标，生成 `data/radar.json`。

本地看板优先拉取远端数据（raw URL），拉取失败时回退本地文件。无 API Key、零成本运行。

- 生成脚本：`scripts/update_radar.py`（stdlib-only）
- 数据产物：`data/radar.json`
