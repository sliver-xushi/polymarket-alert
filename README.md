# Musk Tweet Trader

半自动 Polymarket 马斯克推文区间交易驾驶舱。

当前版本是 MVP，目标是先完成观察、区间组合模拟、纸面交易和订单草稿，不自动提交实盘订单。

## 启动

```bash
python3 server.py
```

打开：

```text
http://127.0.0.1:8787
```

## 当前能力

- 市场发现：优先尝试 Polymarket Gamma API，失败时使用内置样例市场。
- 盘口展示：展示 bid、ask、spread、depth、成交量。
- 模型概率：基于市场隐含概率，并可用手动 xtracker count 做当前进度修正。
- 区间组合模拟：按每区间等份数计算组合成本、命中概率、结算 edge、最大亏损、命中盈利，并给出结算建议和波段建议。
- 纸面交易：将模拟交易记录到本地 SQLite。
- 订单草稿：生成限价单草稿，但不会提交到 Polymarket。

## 文件结构

```text
server.py
public/
  index.html
  styles.css
  app.js
data/
  trader.db
马斯克推文Polymarket半自动交易系统方案V2.md
```

## API

```text
GET  /api/health
GET  /api/markets
POST /api/basket/simulate
GET  /api/paper-trades
POST /api/paper-trades
GET  /api/order-drafts
POST /api/order-drafts
```

## 安全边界

当前版本不保存私钥，不自动下单，不做实盘交易。

下一阶段再接：

- xtracker 自动计数。
- 历史样本回填。
- 更完整的相似轨迹概率模型。
- Polymarket 账户连接。
- 人工确认后的实盘限价单。
