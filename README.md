# Musk Tweet Trader

半自动 Polymarket 马斯克推文区间交易驾驶舱。

当前版本是 MVP，目标是先完成观察、区间组合模拟、模拟交易和订单草稿，不自动提交实盘订单。

## 启动

```bash
python3 server.py
```

打开：

```text
http://127.0.0.1:8787
```

## Vercel 部署

这个项目已经适配 Vercel：

- 静态页面通过 `vercel.json` rewrite 到 `public/`
- 读接口拆成了 `api/*.py` Vercel Functions
- `模拟交易记录` 和 `下单建议` 在 Vercel 环境下改为浏览器 `localStorage` 保存
- 本地 `SQLite` 只保留给 `python3 server.py` 的本地开发模式

直接部署时，Vercel 的 Root Directory 指向仓库根目录即可。

## 当前能力

- 市场发现：优先尝试 Polymarket Gamma API，失败时使用内置样例市场。
- 盘口展示：展示 bid、ask、spread、depth、成交量。
- 模型概率：基于市场隐含概率，并可用手动 xtracker count 做当前进度修正。
- 区间组合模拟：按每区间等份数计算组合成本、命中概率、结算 edge、最大亏损、命中盈利，并给出结算建议和波段建议。
- 模拟交易：本地开发模式写入 SQLite；Vercel 部署模式保存到当前浏览器。
- 订单草稿：生成限价单草稿，但不会提交到 Polymarket；Vercel 部署模式保存到当前浏览器。

## 文件结构

```text
server.py
api/
  health.py
  markets.py
  tracker.py
  basket/simulate.py
  resolve-market/index.py
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
GET  /api/resolve-market
GET  /api/tracker
POST /api/basket/simulate
```

## 安全边界

当前版本不保存私钥，不自动下单，不做实盘交易。

下一阶段再接：

- xtracker 自动计数。
- 历史样本回填。
- 更完整的相似轨迹概率模型。
- Polymarket 账户连接。
- 人工确认后的实盘限价单。
