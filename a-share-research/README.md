# A股研究数据采集（AKShare）

这是一个只使用公开股票数据的研究采集器，不连接券商账户，不交易，不读取个人资产。

- 数据源：AKShare 开源接口（东方财富 A股日线；遇到接口异常时尝试新浪日线）
- 股票：生益科技 600183、工业富联 601138
- 云端：GitHub Actions，周一至周五北京时间 16:35 尝试更新（节假日可能沿用上一交易日）
- 输出：`reports/latest.json`、`reports/latest.md`、各股票日线 CSV
- 任何请求失败会使任务失败，不会伪装成行情已更新。查看 Actions 日志可定位错误。
- **本仓库为公开仓库，输出也公开；不要放入个人账户、持仓、API 密钥等信息。**
- 价格采用前复权日线，目的为回报与回撤研究。实时价格仍应以交易所/券商为准。
- 估值、利润、财务指标不是这里自动提供的事实；本工具暂不输出买卖建议。

官方数据源：https://github.com/akfamily/akshare

## 运行状态
GitHub Actions 页面：https://github.com/akatsukifan/AI-/actions

本工具是否真正抓取成功，以 `reports/latest.json` 的 `updated_at_utc`、`latest_trade_date` 和 Actions 成功记录为准。
