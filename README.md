# CLAUDE.md

本文件为 Claude Code 在操作此仓库时提供指导。

## 快速入口（必读）

要了解项目当前状态，优先查看：

1. **`CLAUDE.md`**（本文件）— 项目骨架架构、命令、配置、依赖
2. **`CURRENT.md`**（服务器 `/root/projects/CURRENT.md`）— 每日自动生成的**项目快照**，包含情绪指数、数据积累进度、容器状态、定时任务等实时信息

> 用户给你看 `CURRENT.md` 即可了解项目当前全貌。

## 项目概览

本项目是一个 **4 个子项目组成的大仓**，构成面向 A股/港股/美股的自动化投资决策系统：

1. **`search_information/`** — 信息采集层（热榜聚合、RSS、AI分析、通知推送）
2. **`analyse_information/`** — 深度分析与知识沉淀（AI评分、Obsidian笔记、RAG检索）
3. **`invest/`** — 投资决策与执行（多因子引擎、回测、实时仪表盘）
4. **`Feedback_and_Learning/`** — 反馈收集与学习优化（模式识别、规则生成）

**数据流：** `采集(search_information) → 分析(analyse_information) → 决策(invest) → 学习(Feedback_and_Learning) → 回写优化`

---

## 1. search_information — 信息采集层

### 功能说明

| 模块         | 功能                                                         | 关键文件                                           |
| ------------ | ------------------------------------------------------------ | -------------------------------------------------- |
| TrendRadar   | 11平台热榜采集（头条/百度/微博/知乎/B站等），每30分钟自动抓取 | `TrendRadar/__main__.py`（1724行，NewsAnalyzer类） |
| RSS聚合      | 9个核心投资RSS源（东方财富/华尔街见闻/Bloomberg/CNBC/Yahoo/SCMP等） | `TrendRadar/crawler/rss/`                          |
| AI分析       | 小米MiMo API深度分析+大白话翻译，3层金字塔关键词匹配         | `TrendRadar/ai/`                                   |
| 钉钉推送     | 每天4条定时推送（9/13/18点文字总结，22点思维导图）           | `TrendRadar/notification/`                         |
| MCP Server   | 21个AI工具，支持 stdio 和 HTTP（端口3333）双模式             | `mcp_server/server.py`                             |
| 通知中心     | 统一通知中心（端口5050），9个渠道（钉钉/飞书/企微/Telegram/邮件/ntfy/Bark/Slack/Webhook） | `notification_center/server.py`                    |
| Dashboard    | Web仪表盘（端口8085→5060），14个API端点，内嵌HTML/CSS/JS     | `dashboard_service/server.py`                      |
| 情绪采集     | 雪球+东方财富情绪数据采集                                    | `sentiment_fetcher.py`                             |
| 内容深度分析 | Defuddle提取+AI分析+Obsidian知识沉淀                         | `analyzer/scripts/`                                |

### 依赖清单

```
requests>=2.31.0, PyYAML>=6.0, schedule>=1.2.0, feedparser>=6.0.0,
beautifulsoup4>=4.12.0, lxml>=4.9.0, openai>=1.0.0, python-dotenv>=1.0.0,
dingtalk-stream>=0.5.0, pytz>=2023.3, litellm>=1.0.0, tenacity>=8.2.0
```

### Docker 部署方式

- **镜像构建**：`TrendRadar/docker/Dockerfile`（python:3.10-slim + supercronic 定时任务）
- **编排文件**：`docker-compose-server.yml` — trendradar、notification-center、dashboard、semantic-search
- **容器环境变量**（来自 Dockerfile）：`PYTHONUNBUFFERED=1`、`CONFIG_PATH=/app/config/config.yaml`、`FREQUENCY_WORDS_PATH=/app/config/frequency_words.txt`
- **启动入口**：`ENTRYPOINT ["/entrypoint.sh"]`

### 启动命令

```bash
# 热榜采集（主程序）
cd search_information/TrendRadar && python main.py

# MCP Server
cd search_information/TrendRadar && python -c "from mcp_server.server import run_server; run_server()"

# 通知中心
cd search_information/notification_center && python server.py

# Dashboard
cd search_information/dashboard_service && python server.py

# 内容深度分析
cd search_information/analyzer/scripts && python analyze.py

# 关键词分析
cd search_information && python analyze_keywords.py

# 历史数据标注
cd search_information/scripts && python label_historical.py

# Windows菜单式启动
search_information/start.bat
```

---

## 2. analyse_information — 信息分析层

### 功能说明

| 模块         | 功能                                                         | 关键文件                                    |
| ------------ | ------------------------------------------------------------ | ------------------------------------------- |
| Pipeline编排 | 9种运行模式（URL/RSS/信号目录/搜索/反馈/摘要/统计等）        | `analyzer/pipeline.py`                      |
| 内容提取     | 3级提取：Defuddle → BeautifulSoup → 纯文本                   | `analyzer/defuddle/extractor.py`            |
| AI分析       | MiMo API 深度分析，3级降级（统一模式→分步模式→关键词匹配）   | `analyzer/ai_analyzer.py`                   |
| 知识沉淀     | Obsidian笔记（YAML frontmatter + wikilink 双向链接），8个分类 | `analyzer/knowledge_builder.py`             |
| RAG检索      | ChromaDB 向量检索 + TF-IDF 回退                              | `analyzer/rag_retriever.py`、`vector_db.py` |
| 语义搜索API  | Flask 服务（端口5070），支持语义搜索和RAG问答                | `analyzer/search_api.py`                    |
| 摘要生成     | 每日/每周 Digest 自动生成                                    | `analyzer/digest.py`                        |

### 依赖清单

```
pyyaml>=6.0, requests>=2.28.0, beautifulsoup4>=4.12.0, python-dotenv>=1.0.0,
lxml>=4.9.0, chromadb>=0.4.0, flask>=2.3.0, openai>=1.0.0, litellm>=1.0.0,
tqdm>=4.65.0, tenacity>=8.2.0
```

### Docker 部署方式

- **镜像构建**：`analyse_information/Dockerfile`（python:3.11-slim + gcc/g++ 编译依赖）
- **编排文件**：analyser（RSS分析后休眠3600秒）、semantic-search（端口5070常驻）
- **容器环境变量**：`PYTHONUNBUFFERED=1`、`PYTHONDONTWRITEBYTECODE=1`，暴露端口5070
- **启动命令**：analyser 的 CMD 是 `python analyzer/pipeline.py --rss`，semantic-search 的 CMD 是 `python analyzer/search_api.py --host 0.0.0.0 --port 5070`
- **数据目录**：容器内 `/app/knowledge_base/`，挂载宿主机 `./data/knowledge_base/`

### 启动命令

```bash
# RSS分析流水线
cd analyse_information && python analyzer/pipeline.py --rss

# 处理单条URL
cd analyse_information && python analyzer/pipeline.py --url "https://example.com"

# 批量处理JSON文件
cd analyse_information && python analyzer/pipeline.py --json "path/to/file.json"

# 搜索已沉淀文章
cd analyse_information && python analyzer/pipeline.py --search

# 标记反馈（有用/没用）
cd analyse_information && python analyzer/pipeline.py --feedback

# 生成每日/每周简报
cd analyse_information && python analyzer/pipeline.py --digest
cd analyse_information && python analyzer/pipeline.py --weekly-digest

# 查看处理统计
cd analyse_information && python analyzer/pipeline.py --stats

# 启动语义搜索API服务
cd analyse_information && python analyzer/search_api.py --host 0.0.0.0 --port 5070

# 构建RAG索引
cd analyse_information && python scripts/build_rag_index.py

# RAG查询
cd analyse_information && python scripts/rag_query.py
```

---

## 3. invest — 投资决策层

### 功能说明

| 模块            | 功能                                                         | 关键文件                                                     |
| --------------- | ------------------------------------------------------------ | ------------------------------------------------------------ |
| 闭环调度器      | 8步流水线（更新净值→采集→分析→止盈止损→决策→执行→通知→回测） | `pipeline_scheduler.py`                                      |
| 决策引擎        | 8因子加权评分（技术20%+情绪15%+多时间框架15%+动量15%+历史10%+波动10%+市场情绪10%+关键词5%），买入>0.58卖出<0.42 | `decision_engine.py`                                         |
| 交易执行        | 模拟买卖、持仓管理、止盈止损（动态阈值）、风控拦截           | `execution_engine.py`                                        |
| 交易系统        | 6模块（趋势/波动/买点/风控/止盈/情绪），输出 BUY/SELL/HOLD   | `trading_system.py`                                          |
| 情绪分析        | AI情绪分析（MiMo/DeepSeek）+ 关键词情绪                      | `ai_sentiment_analyzer.py`、`sentiment_analyzer.py`          |
| 市场情绪指数    | 5维度 Fear & Greed Index（新闻30%+动量25%+波动率20%+技术15%+社交10%） | `market_sentiment_index.py`                                  |
| 回测引擎        | 基于动量与波动的策略回测，参数优化器（网格搜索）             | `backtester.py`、`enhanced_backtester.py`、`parameter_optimizer.py` |
| 组合分析        | Sharpe / Sortino / VaR / 最大回撤 / Alpha / Beta             | `portfolio_analyzer.py`                                      |
| 知识管理        | 决策历史+向量检索+投资研究库，按月分库                       | `knowledge_manager.py`、`knowledge_vector_db.py`、`knowledge_base.py` |
| News API Server | 端口5000，接收 TrendRadar 推送、持仓/决策/情绪数据查询       | `news_api_server.py`                                         |
| 实时基金仪表盘  | Next.js 前端（60+组件），Tailwind / Radix UI / Zustand / Chart.js | `real-time-fund/`                                            |
| 并行执行        | 文件锁+JSON队列+状态机（created→analyzed→decided→executed→feedbacked→learned→error） | `parallel_executor.py`                                       |

### 依赖清单

```
pandas>=1.3.0, numpy>=1.21.0, matplotlib>=3.5.0, requests>=2.28.0, pyyaml>=6.0,
requests-cache>=0.9.0, plotly>=5.0.0, jinja2>=3.0.0, watchdog>=2.0.0,
openai>=1.0.0, litellm>=1.0.0, chromadb>=0.4.0, tqdm>=4.65.0, tenacity>=8.2.0
# 可选: akshare, empyrical, streamlit（Python 3.9+）
```

前端依赖：next（16.1.5）、react、chart.js、framer-motion、@dnd-kit、@tanstack/react-query、@supabase/supabase-js、radix-ui、zustand、sentry

### Docker 部署方式

- **后端镜像**：`invest/Dockerfile`（python:3.9-slim，端口5000，CMD 为 `news_api_server.py`）
- **前端镜像**：`invest/real-time-fund/Dockerfile`（Next.js，端口3000）
- **编排文件**：invest-backend（端口5000）、invest-frontend（端口3000）
- **环境变量**：通过 `.env` 文件注入 `MIMO_API_KEY` 等

### 启动命令

```bash
# 后端
cd invest/scripts && python pipeline_scheduler.py --full    # 全流程
cd invest/scripts && python news_api_server.py               # API服务（端口5000）
cd invest/scripts && python daily_report.py                  # 持仓日报
cd invest/scripts && python fund_data_fetcher.py             # 基金数据抓取

# 前端
cd invest/real-time-fund && npm install
cd invest/real-time-fund && npm run dev       # 开发模式 http://localhost:3000
cd invest/real-time-fund && npm run build     # 生产构建
cd invest/real-time-fund && npm run start     # 生产启动
cd invest/real-time-fund && npm run lint      # ESLint检查

# 回测
cd invest/scripts && python backtester.py
cd invest/scripts && python parameter_optimizer.py

# 配置管理
cd invest/scripts && python config_manager.py
```

---

## 4. Feedback_and_Learning — 反馈学习层

### 功能说明

| 模块       | 功能                                                         | 关键文件                 |
| ---------- | ------------------------------------------------------------ | ------------------------ |
| 反馈收集器 | 收集交易执行结果、计算实际收益、评估决策质量（excellent/good/fair/poor） | `feedback_collector.py`  |
| 学习优化器 | 5种决策模式识别 + 4类规则生成 + 优化分数计算                 | `learning_optimizer.py`  |
| 知识管理器 | 经验教训沉淀、决策模式去重、自动备份、频率更新               | `knowledge_manager.py`   |
| 并行执行器 | 跨平台文件锁（msvcrt/fcntl）+ JSON 任务队列 + 状态机         | `parallel_executor.py`   |
| 错误处理器 | 10种错误类型 + 重试策略 + 监控告警                           | `error_handler.py`       |
| 重试管理器 | 可配置重试（1分钟/5分钟/15分钟递增），带回退函数和超时控制   | `utils/retry_manager.py` |
| 文件锁     | SharedLock（读锁，多读者并行）+ ExclusiveLock（写锁，独占），支持超时 | `utils/file_lock.py`     |

### 完整流程说明

```
主循环 main_loop 持续轮询
  → 读取 results/executions.json，查找 status="executed" 的批次
  → 检查处理延迟 >= 1小时（确保价格有足够变动）
  → 更新批次状态为 "feedbacked"
  → FeedbackCollector 收集反馈（获取当前价格、计算收益率、评估决策质量）
  → LearningOptimizer 学习优化（模式识别→规则生成→优化分数）
  → KnowledgeManager 更新知识库（添加经验教训、去重、备份）
  → 更新批次状态为 "learned"
```

### 依赖清单

依赖 invest 的 requirements.txt（openai、litellm、tenacity 等），自身仅额外依赖 `openai`。

### Docker 部署方式

- **镜像构建**：`Feedback_and_Learning/Dockerfile`（python:3.9-slim）
- **编排文件**：feedback-learner（无外部端口），依赖 invest-backend
- **容器环境变量**：`MIMO_API_KEY`、`MIMO_API_BASE`、`MIMO_MODEL`、`USE_MIMO`、`PYTHONUNBUFFERED=1`

### 启动命令

```bash
# 正常运行
cd Feedback_and_Learning/invest/scripts && python feedback_learner_main.py

# 守护进程模式
cd Feedback_and_Learning/invest/scripts && python feedback_learner_main.py --daemon

# 运行测试
cd Feedback_and_Learning/invest/scripts && python run_tests.py
```

---

## 5. 跨项目数据契约（JSON格式）

| 来源                  | 去向                  | 文件路径                                                     |
| --------------------- | --------------------- | ------------------------------------------------------------ |
| search_information    | analyse_information   | `TrendRadar/output/summaries/ai_summaries.jsonl`             |
| analyse_information   | invest                | `knowledge_base/analyzed/*.json` + `obsidian/*.md`           |
| invest                | Feedback_and_Learning | `data/results/executions.json`                               |
| Feedback_and_Learning | invest                | `data/knowledge/lessons.json`、`patterns.json`、`rules.json` |

各字段完整定义见 `search_information/.trae/documents/接口契约表.md`（7个契约，含完整 JSON Schema）。

---

## 6. 共享基础设施

| 服务                | 端口                       | 所属项目            | 职责                                 |
| ------------------- | -------------------------- | ------------------- | ------------------------------------ |
| notification-center | 5050                       | search_information  | 统一通知调度，9个推送渠道            |
| dashboard           | 8085（外部）/ 5060（内部） | search_information  | Web 仪表盘（Flask，内嵌HTML/CSS/JS） |
| semantic-search     | 5070                       | analyse_information | ChromaDB + TF-IDF 语义搜索           |
| invest-backend      | 5000                       | invest              | 新闻情绪 API + 决策引擎              |
| invest-frontend     | 3000                       | invest              | Next.js 基金仪表盘                   |

---

## 7. 核心模式

- **AI 模型**：MiMo `mimo-v2.5-pro` 通过 LiteLLM 调用。LiteLLM 需要 `openai/` 前缀，直接 API 调用不需要。降级链：MiMo → DeepSeek → 规则引擎
- **关键词**：3层金字塔，定义在 `TrendRadar/config/frequency_words.txt`（获利→先机→趋势）
- **Pipeline 模式**：`pipeline.py` 支持 9 种模式（`--url`、`--rss`、`--signals-dir`、`--digest`、`--stats` 等）
- **决策引擎**：8因子加权评分（技术0.20、情绪0.15、多时间框架0.15、动量0.15、历史0.10、波动0.10、市场情绪0.10、关键词0.05），买入阈值0.58，卖出阈值0.42
- **报告模式**：daily（当日汇总）/ current（当前榜单）/ incremental（增量监控，推荐）
- **存储**：SQLite 按日期分库（`news/YYYY-MM-DD.db`、`rss/YYYY-MM-DD.db`），可选 S3 兼容远程存储
- **钉钉推送**：每天4条（9:00/13:00/18:00文字总结，22:00思维导图总结）
- **批次状态机**：created → analyzed → decided → executed → feedbacked → learned → error

---

## 8. 环境变量配置（按模块分组）

### 8.1 核心 AI 与模型

| 变量名                          | 使用方     | 默认值                                    | 说明                                  |
| ------------------------------- | ---------- | ----------------------------------------- | ------------------------------------- |
| `MIMO_API_KEY`                  | 全部项目   | —                                         | MiMo API 密钥（主力模型）             |
| `MIMO_API_BASE`                 | invest、FL | `https://token-plan-cn.xiaomimimo.com/v1` | MiMo API 地址                         |
| `MIMO_MODEL`                    | FL         | `mimo-v2.5-pro`                           | MiMo 模型名                           |
| `DEEPSEEK_API_KEY`              | 全部项目   | —                                         | DeepSeek API 密钥（备用）             |
| `DEEPSEEK_DAILY_BUDGET_CNY`     | invest     | `5.0`                                     | DeepSeek 每日预算上限（元）           |
| `DEEPSEEK_MAX_INPUT_CHARS`      | invest     | `8000`                                    | DeepSeek 输入字符上限                 |
| `DEEPSEEK_FAILURE_THRESHOLD`    | invest     | `5`                                       | DeepSeek 连续失败熔断阈值             |
| `DEEPSEEK_CIRCUIT_RECOVERY_SEC` | invest     | `900`                                     | 熔断恢复时间（秒）                    |
| `DEEPSEEK_FALLBACK_TO_MIMO`     | invest     | `true`                                    | DeepSeek 失败时回退到 MiMo            |
| `USE_MIMO`                      | 全部项目   | `true`                                    | 模型路由（true=MiMo，false=DeepSeek） |
| `AI_MODEL`                      | TrendRadar | `deepseek/deepseek-chat`                  | 覆盖模型名                            |
| `AI_API_BASE`                   | TrendRadar | —                                         | 覆盖 API 地址                         |
| `AI_TIMEOUT`                    | TrendRadar | —                                         | AI 请求超时时间（秒）                 |
| `AI_ANALYSIS_ENABLED`           | TrendRadar | —                                         | 启用 AI 分析                          |
| `AI_TRANSLATION_ENABLED`        | TrendRadar | —                                         | 启用 AI 翻译                          |

### 8.2 通知与推送

| 变量名                          | 使用方     | 默认值                            | 说明                                                    |
| ------------------------------- | ---------- | --------------------------------- | ------------------------------------------------------- |
| `DINGTALK_WEBHOOK`              | 全部项目   | —                                 | 钉钉机器人 Webhook 地址                                 |
| `DINGTALK_SECRET`               | 全部项目   | —                                 | 钉钉签名密钥                                            |
| `DINGTALK_WEBHOOK_URL`          | TrendRadar | —                                 | 钉钉 Webhook（多账号支持，优先级高于 DINGTALK_WEBHOOK） |
| `NOTIFICATION_CENTER_URL`       | invest     | `http://notification-center:5050` | 通知中心内部地址                                        |
| `FEISHU_WEBHOOK_URL`            | TrendRadar | —                                 | 飞书机器人 Webhook                                      |
| `WEWORK_WEBHOOK_URL`            | TrendRadar | —                                 | 企业微信 Webhook                                        |
| `TELEGRAM_BOT_TOKEN`            | TrendRadar | —                                 | Telegram 机器人 Token                                   |
| `TELEGRAM_CHAT_ID`              | TrendRadar | —                                 | Telegram 聊天 ID                                        |
| `EMAIL_HOST`                    | 全部项目   | `smtp.qq.com`                     | SMTP 服务器地址                                         |
| `EMAIL_PORT`                    | 全部项目   | `465`                             | SMTP 端口                                               |
| `EMAIL_USER` / `EMAIL_FROM`     | 全部项目   | —                                 | 发件邮箱                                                |
| `EMAIL_PASS` / `EMAIL_PASSWORD` | 全部项目   | —                                 | 邮箱授权码/密码                                         |
| `EMAIL_TO`                      | 全部项目   | —                                 | 收件邮箱                                                |
| `EMAIL_SMTP_SERVER`             | TrendRadar | —                                 | 备选 SMTP 服务器                                        |
| `EMAIL_SMTP_PORT`               | TrendRadar | —                                 | 备选 SMTP 端口                                          |
| `NTFY_SERVER_URL`               | TrendRadar | `https://ntfy.sh`                 | ntfy 服务器地址                                         |
| `NTFY_TOPIC`                    | TrendRadar | —                                 | ntfy 主题                                               |
| `NTFY_TOKEN`                    | TrendRadar | —                                 | ntfy 认证 Token                                         |
| `BARK_URL`                      | TrendRadar | —                                 | Bark 推送地址                                           |
| `SLACK_WEBHOOK_URL`             | TrendRadar | —                                 | Slack Webhook                                           |
| `GENERIC_WEBHOOK_URL`           | TrendRadar | —                                 | 通用 Webhook 地址                                       |
| `INVEST_API_URL`                | TrendRadar | —                                 | Invest 后端 API 地址                                    |
| `INVEST_API_KEY`                | TrendRadar | —                                 | Invest API 认证密钥                                     |

### 8.3 存储与 S3

| 变量名                   | 使用方             | 默认值 | 说明                              |
| ------------------------ | ------------------ | ------ | --------------------------------- |
| `STORAGE_BACKEND`        | TrendRadar         | `auto` | 存储后端类型（local/remote/auto） |
| `S3_ENDPOINT_URL`        | TrendRadar         | —      | S3 兼容存储端点                   |
| `S3_BUCKET_NAME`         | TrendRadar         | —      | S3 存储桶名                       |
| `S3_ACCESS_KEY_ID`       | TrendRadar         | —      | S3 访问密钥                       |
| `S3_SECRET_ACCESS_KEY`   | TrendRadar         | —      | S3 秘密密钥                       |
| `S3_REGION`              | TrendRadar         | —      | S3 区域                           |
| `STORAGE_RETENTION_DAYS` | trendradar（容器） | `30`   | 数据保留天数                      |
| `LOCAL_RETENTION_DAYS`   | TrendRadar         | `0`    | 本地保留天数（0=不限）            |
| `REMOTE_RETENTION_DAYS`  | TrendRadar         | `0`    | 远程保留天数（0=不限）            |
| `STORAGE_TXT_ENABLED`    | TrendRadar         | —      | 启用 TXT 快照                     |
| `STORAGE_HTML_ENABLED`   | TrendRadar         | —      | 启用 HTML 报告                    |
| `PULL_ENABLED`           | TrendRadar         | —      | 启动时自动拉取远程数据            |
| `PULL_DAYS`              | TrendRadar         | —      | 拉取最近 N 天数据                 |

### 8.4 Dashboard 仪表盘

| 变量名       | 使用方            | 默认值                                 | 说明           |
| ------------ | ----------------- | -------------------------------------- | -------------- |
| `DATA_BASE`  | dashboard（容器） | `/app/data`                            | 数据根目录     |
| `ANALYSE_DB` | dashboard（容器） | `/app/data/knowledge_base/analyzed.db` | 分析数据库路径 |
| `INVEST_DB`  | dashboard（容器） | `/app/data/invest/fund_data.db`        | 投资数据库路径 |

### 8.5 TrendRadar 专属

| 变量名                     | 使用方     | 默认值                       | 说明                 |
| -------------------------- | ---------- | ---------------------------- | -------------------- |
| `CONFIG_PATH`              | TrendRadar | `config/config.yaml`         | 配置文件路径         |
| `FREQUENCY_WORDS_PATH`     | TrendRadar | `config/frequency_words.txt` | 关键词文件路径       |
| `TIMEZONE`                 | TrendRadar | `Asia/Shanghai`              | 系统时区             |
| `DEBUG`                    | TrendRadar | `false`                      | 调试模式             |
| `SORT_BY_POSITION_FIRST`   | TrendRadar | —                            | 按位置优先排序       |
| `MAX_NEWS_PER_KEYWORD`     | TrendRadar | —                            | 每个关键词最大新闻数 |
| `PUSH_WINDOW_ENABLED`      | TrendRadar | —                            | 启用推送时间窗口     |
| `PUSH_WINDOW_START`        | TrendRadar | `08:00`                      | 推送窗口开始时间     |
| `PUSH_WINDOW_END`          | TrendRadar | `22:00`                      | 推送窗口结束时间     |
| `MAX_ACCOUNTS_PER_CHANNEL` | TrendRadar | `3`                          | 每个渠道最大账号数   |

### 8.6 运行时环境（全部项目）

| 变量名                      | 使用方          | 默认值 | 说明                 |
| --------------------------- | --------------- | ------ | -------------------- |
| `PYTHONUNBUFFERED=1`        | 全部 Docker     | —      | 禁用 Python 输出缓冲 |
| `PYTHONDONTWRITEBYTECODE=1` | analyser Docker | —      | 不生成 .pyc 文件     |
| `DOCKER_CONTAINER`          | TrendRadar      | —      | 强制标记 Docker 环境 |

---

## 9. 异常处理规则

每个项目的异常处理策略各不相同，以下是详细说明：

### 9.1 Feedback_and_Learning — 完整错误框架

**`error_handler.py`** — 10种错误类型 + 自动监控：

- **错误类型枚举**：API_ERROR、FILE_LOCK_ERROR、DATA_FORMAT_ERROR、BUSINESS_LOGIC_ERROR、NETWORK_ERROR、TIMEOUT_ERROR、AUTHENTICATION_ERROR、PERMISSION_ERROR、RESOURCE_ERROR、UNKNOWN_ERROR
- **自动告警**：API和认证错误立即告警；同类型错误1小时内超过5次触发告警
- **错误日志**：JSON文件存储，上限1000条，自动滚动
- **监控阈值**（配置于 `feedback_config.yaml`）：
  - 队列积压 >10 条
  - 处理延迟 >30 分钟
  - 错误率 >10%
  - 每日 Token 消耗 >1000万

**`retry_manager.py`** — 3种重试模式：

- `execute_with_retry()`：最多3次尝试，间隔 1分钟/5分钟/15分钟 递增
- `execute_with_fallback()`：尝试主函数，失败后调用回退函数
- `execute_with_timeout()`：基于线程的超时控制
- 装饰器版本：`@retry()`、`@with_fallback()`、`@with_timeout()`

**`file_lock.py`** — 跨平台文件锁：

- Windows：`msvcrt.locking()`
- Unix/Linux：`fcntl.flock()`
- `SharedLock`（共享读锁，多读者并行）和 `ExclusiveLock`（排他写锁，独占）
- 默认30秒超时，支持 `with` 上下文管理器

### 9.2 TrendRadar — 优雅降级

- **AIClient**：调用次数限制（`MAX_CALLS`，默认9999次）、最小间隔节流（`MIN_INTERVAL`，默认1秒）、备用模型链
- **存储管理器**：自动检测运行环境（本地/Docker/GitHub Actions），S3 导入失败时优雅降级，远程→本地级联
- **远程存储**：`HAS_BOTO3` 标志控制条件导入，`try/except` 包裹 boto3 操作，失败时打印详细配置调试信息
- **tenacity**：AI 调用使用 tenacity 自动重试瞬态故障
- **配置加载**：每个配置段都做校验，无效值回退到默认值（如 RSS 新鲜度配置无效时使用默认3天）

### 9.3 invest — AI 预算保护（3把锁）

**`ai_gateway.py`** — DeepSeek 财务安全系统：

1. **日预算锁**：`DEEPSEEK_DAILY_BUDGET_CNY`（默认5元），线程安全成本跟踪器，每日自动重置
2. **输入超长锁**：`DEEPSEEK_MAX_INPUT_CHARS`（默认8000），`validate_input()` 在 API 调用前拒绝超长输入
3. **熔断锁**：`DEEPSEEK_FAILURE_THRESHOLD`（默认5次连续失败），自动暂停15分钟，到期自动恢复

- 预算耗尽或熔断开启时，自动发送告警到 notification-center

### 9.4 analyse_information — 3级降级

- **AI 分析级联**：统一 Prompt（MiMo）→ 分步模式（先判断相关性→再翻译→再分类）→ 关键词匹配 + 加权评分
- **ThreadPoolExecutor**：3个并发线程，每项最多2次重试
- **Token 追踪**：线程安全计数器 + 费用估算，API 调用上限（默认50次）
- **内容截断**：智能截断 `_smart_truncate()`，按换行符分割，保留头尾各半

### 9.5 Docker 运维排障

```bash
# 容器内测试 tenacity 是否安装
docker exec trendradar python -c "import tenacity; print('ok')"

# 检查容器环境变量
docker exec trendradar env | grep MIMO_API_KEY

# 查看近期错误日志
docker logs --tail 50 trendradar 2>&1 | grep -i error

# 终止失控进程（如 label_historical）
ps aux | grep label_historical | grep -v grep | awk '{print $2}' | xargs kill

# 强制重建容器（跳过缓存）
docker compose build --no-cache trendradar && docker compose up -d trendradar

# Git pull 冲突处理
git stash && git pull && git stash pop

# LiteLLM 模型名修复（config.yaml 需要 openai/ 前缀）
# 错误: model: "mimo-v2.5-pro"
# 正确: model: "openai/mimo-v2.5-pro"
```

---

## 10. 关键配置文件

| 文件路径                                                     | 用途                                            | 主要配置段                                                   |
| ------------------------------------------------------------ | ----------------------------------------------- | ------------------------------------------------------------ |
| `TrendRadar/config/config.yaml`（约608行）                   | 热榜源、RSS源、AI模型、推送渠道、报告模式、存储 | `app`、`platforms`、`rss`、`ai`、`notification`、`storage`、`report` |
| `TrendRadar/config/frequency_words.txt`                      | 3层金字塔关键词                                 | 获利（重组/政策利好/业绩暴增）、先机（北向资金/龙虎榜）、趋势（AI/半导体/新能源） |
| `TrendRadar/config/ai_analysis_prompt.txt`                   | AI 分析系统提示词                               | —                                                            |
| `analyse_information/analyzer/config.yaml`                   | AI 分析配置、分类关键词、知识库路径             | `ai`、`categories`、`rss`、`knowledge_base`、`relevance`     |
| `invest/scripts/default_config.yaml`                         | 基金列表、交易参数、风险设置                    | `funds`、`trading_system`、`backtest`、`analysis`、`behavioral` |
| `Feedback_and_Learning/invest/scripts/config/feedback_config.yaml` | 反馈学习参数、资源限制、监控阈值                | `data_paths`、`feedback`、`retry`、`resource_limits`、`monitoring`、`logging` |

---

## 11. 数据库架构

| 数据库 | 文件位置                                              | 分区方式   | 包含表                                                       |
| ------ | ----------------------------------------------------- | ---------- | ------------------------------------------------------------ |
| 热榜   | `data/search_information/news/YYYY-MM-DD.db`          | 按日期分库 | `news_items`、`platforms`、`rank_history`、`crawl_records`、`push_records` |
| RSS    | `data/search_information/rss/YYYY-MM-DD.db`           | 按日期分库 | `rss_items`、`rss_feeds`、`rss_crawl_records`、`rss_push_records` |
| 分析   | `data/knowledge_base/analyzer.db`（或 `analyzed.db`） | 单文件     | `processed_urls`（含 FTS5 全文搜索）、`articles_fts`         |
| 系统   | `data/knowledge_base/system.db`                       | 单文件     | `signals`、`analysis`、`feedback`、`tasks`、`knowledge_notes`、`daily_digests` |
| 投资   | `data/invest/fund_data.db`                            | 单文件     | `fund_info`、`fund_nav`、`decisions`（按月分库）             |
| 反馈   | `data/invest/`                                        | JSON 文件  | `executions.json`、`lessons.json`、`patterns.json`、`rules.json` |

**数据库注意点：**

- analyse_information 的 `DB_PATH` 已从 `./shared/data/analyzer.db` 改为 `./knowledge_base/analyzer.db`，解决 Docker volume 挂载问题
- Dashboard 同时兼容 `processed_urls` 和 `analyzed` 两种表名
- 热榜和 RSS 数据库使用 `url + platform_id`（或 `url + feed_id`）唯一索引实现去重

---

## 12. 服务器与部署

| 服务器                 | IP                | 用途                                       |
| ---------------------- | ----------------- | ------------------------------------------ |
| 新加坡（DigitalOcean） | `188.166.249.182` | 8个 Docker 容器 + TrendRadar 采集          |
| 阿里云                 | `8.140.232.52`    | 场景生成器 v2.2-fast（4个API密钥、32线程） |
| AutoDL                 | 按需开通          | LoRA 训练（RTX 4090）                      |

```bash
# SSH 登录
ssh root@188.166.249.182

# 重新构建并启动全部
cd /root/projects && docker compose up -d --build

# 一键健康检查（12项）
bash /root/test_all_v2.sh
```

---

## 重要注意事项

- **所有投资均为模拟交易** — 未连接真实交易 API
- **MiMo API 特性**：`content` 可能为空（内容在 `reasoning_content` 字段），请始终同时检查：`text = msg.get("content", "").strip() or msg.get("reasoning_content", "").strip()`
- **LiteLLM 模型名**：需要 `openai/` 前缀（如 `openai/mimo-v2.5-pro`），但直接调用 API 不需要
- **服务器上的 vector_db.py**：ChromaDB 可能不可用（回退到 TF-IDF），文件实际为存根
- **sentiment_fetcher.py**：需要 litellm（TrendRadar 的 `__init__.py` 级联导入），裸 Python 环境可能失败
- **Dashboard 内嵌代码**：`server.py` 包含内联 HTML/CSS/JS（已移除 Jinja2 模板以避免 JS 语法冲突）
- **invest-backend 的 ThreadingHTTPServer**：已替换单线程 HTTPServer，防止外部扫描导致服务阻塞
- **Docker 缓存**：代码更新后需要加 `--no-cache` 标志重建
- **Git pull 冲突**：服务器上使用 `git stash && git pull && git stash pop`

---

## 13. 当前状态快照与已知问题（2026-06-03）

### 13.1 三服务器状态

| 服务器              | IP                | 内存          | 核心用途                             | 状态                   |
| ------------------- | ----------------- | ------------- | ------------------------------------ | ---------------------- |
| 新加坡 DigitalOcean | `188.166.249.182` | 4GB/2核       | 8个Docker容器运行中                  | ✅ 正常                 |
| 阿里云              | `8.140.232.52`    | 7.1GB         | v3.0场景生成器（--mode mix，12线程） | ✅ 运行中               |
| AutoDL              | 按需开通          | RTX 4090 24GB | LoRA训练                             | ⏸ 闲置（训练完即关机） |

### 13.2 新加坡8个容器状态

| 容器名              | 端口 | 内存   | 说明                          |
| ------------------- | ---- | ------ | ----------------------------- |
| trendradar          | --   | ~198MB | 热榜采集 + RSS（每30分钟）    |
| analyser            | --   | ~55MB  | AI分析 + 知识沉淀             |
| dashboard           | 8085 | ~23MB  | Web仪表盘（Basic Auth已启用） |
| invest-backend      | 5000 | ~50MB  | 投资后端（升级后不再OOM）     |
| invest-frontend     | 3000 | ~10MB  | Next.js前端                   |
| notification-center | 5050 | ~31MB  | 统一通知 + 健康监控           |
| semantic-search     | 5070 | ~71MB  | 语义搜索API                   |
| feedback-learner    | --   | ~21MB  | 反馈学习                      |

### 13.3 已知问题

| 问题                       | 严重度 | 状态     | 说明                                                         |
| -------------------------- | ------ | -------- | ------------------------------------------------------------ |
| RAG AI回答401 Unauthorized | 🔴 中   | ⏸ 暂停   | MiMo API密钥被限流，搜索功能正常，仅AI生成回答不可用         |
| 情绪指数一直显示50         | 🟡 中   | 📋 需开发 | 缺少定时收集情绪数据的任务（market_sentiment_index.py未定时跑） |
| 服务器目录结构不一致       | 🟢 低   | ⚠️ 已知   | 本地 `search_information/`  vs 服务器 `/root/projects/search_information/search_information/` |
| MiMo密钥可能到期           | 🔴 高   | ⚠️ 监控中 | 原计划约58天窗口，需提前准备备用模型                         |

### 13.4 数据里程碑

| 数据       | 当前量                                     | 目标                  | 来源             |
| ---------- | ------------------------------------------ | --------------------- | ---------------- |
| 合成数据   | 127万+（v2.2-fast历史） + 持续增长（v3.0） | 300~500万             | 阿里云生成器     |
| 真实数据   | ~1.6万（8,471已标注）                      | 3~5万                 | 新加坡TrendRadar |
| 已训练模型 | v3 已合并（279,695条，Qwen2.5-1.5B）       | V1.0（127万，进行中） | AutoDL           |

---

## 14. 综合优化路线图（9维度）

以下整合 `优化.md` 中9个角色的优化建议，按优先级排序：

### 14.1 Phase 1: 根基加固（2-3周，P0优先）

| 角色视角     | 优化项          | 具体动作                                       | 预期效果           |
| ------------ | --------------- | ---------------------------------------------- | ------------------ |
| 🗄️ 数据工程师 | AI响应缓存      | 输入哈希→SQLite缓存，TTL可配，预计命中率30-50% | 节省30-50% API费用 |
| 👨‍💻 DevOps    | CI加入自动测试  | pytest + ruff/lint，PR合并前必须通过           | 防止回归           |
| 👨‍💻 DevOps    | 统一日志聚合    | 容器JSON日志→Loki/Grafana                      | 故障排查效率提升   |
| 🔒 安全       | Dashboard加认证 | ✅ 已实现（Basic Auth）                         | 防止未授权访问     |
| 🔒 安全       | 敏感信息审计    | 扫描硬编码密钥→环境变量                        | ✅ 已实现（v3.4）   |
| 🗄️ 数据工程师 | 数据质量监控    | 空值率<5%、不重复率>95%，异常自动告警          | 避免GIGO           |
| 🤖 AI/ML      | Prompt版本管理  | 结构化Prompt + 版本号 + A/B测试                | Prompt迭代可追溯   |

### 14.2 Phase 2: 质量提升（2-3周）

| 角色视角 | 优化项         | 具体动作                                              |
| -------- | -------------- | ----------------------------------------------------- |
| 🧪 QA     | 核心单元测试   | decision_engine、execution_engine、pipeline_scheduler |
| 🎨 前端   | Web Vitals优化 | ISR/SSR迁移、代码分包懒加载                           |
| 🧪 QA     | 前端E2E测试    | Playwright：搜索基金→买入→持仓→日报                   |
| 🔒 安全   | HTTPS全站      | Let's Encrypt + nginx反向代理                         |
| 🤖 AI/ML  | 长文本成本分层 | <500字→规则引擎，500-2000字→DeepSeek，>2000字→MiMo    |

### 14.3 Phase 3: 架构升级（3-4周）

| 角色视角     | 优化项                | 具体动作                                    |
| ------------ | --------------------- | ------------------------------------------- |
| 🏗️ 架构师     | Flask→FastAPI异步化   | dashboard/notification/news_api三服务改造   |
| 🏗️ 架构师     | API统一网关           | nginx/traefik反向代理 + 限流 + 鉴权         |
| 🗄️ 数据工程师 | SQLite→PostgreSQL迁移 | 按日分库改为单库管理，支持跨日期JOIN        |
| 📈 投资分析师 | 多策略并行引擎        | 趋势跟踪+均值回归+事件驱动+动量策略综合投票 |
| 📈 投资分析师 | 因子权重自适应        | 滚动窗口IC排序动态调整权重                  |

### 14.4 Phase 4: 产品创新（3-4周）

| 角色视角     | 优化项           | 具体动作                               |
| ------------ | ---------------- | -------------------------------------- |
| 📱 产品经理   | 智能推送定制     | 频率/内容/渠道用户可配                 |
| 📱 产品经理   | 决策透明度       | 展示各因子评分+权重贡献+原文引用       |
| 📱 产品经理   | 个人投资报告     | 每周/每月自动生成收益率+回撤+胜率分析  |
| 📈 投资分析师 | 多源情绪指数增强 | 增加微博热搜/Twitter情绪/财报电话会NLP |

---

## 15. 模型训练与部署规划（v2）

### 15.1 战略定位变更

**v1（旧）：** 训练一个模型替代 MiMo/DeepSeek → 省钱 + 摆脱依赖

**v2（新）：** 不替代 API，用小模型做放大器和倍增器 → 做 API 做不了的事

| 能力     | 你的小模型（1.5B甚至更小） | MiMo/DeepSeek API     |
| -------- | -------------------------- | --------------------- |
| 推理成本 | ≈ 0（CPU都能跑）           | 按token付费           |
| 延迟     | 50-300ms（本地）           | 500ms-5s（网络+排队） |
| 并发     | 无限副本                   | 限速限频              |
| 嵌入性   | 可嵌入pipeline每个环节     | 只有一个endpoint      |
| 24×7     | 永远在线                   | 可能熔断/超时         |

**核心原则：** API做"质"的事（500条精选深度分析），小模型做"量"的事（10,000条初筛/分类/排序）。

### 15.2 四阶段执行方案

#### 阶段0：快筛哨兵（第1-2周）——并行路径A

**核心逻辑：** 训练一个极小模型（DistilBERT + ONNX，~70MB），直接部署在新加坡服务器CPU上做全量初筛。

| 任务                    | 文件                                      | 时间    | 前提             | 完成标志               |
| ----------------------- | ----------------------------------------- | ------- | ---------------- | ---------------------- |
| 0.1 准备分类器数据      | `scripts/prepare_classifier_data.py`      | 第1天   | 阿里云数据可访问 | 训练集100万+验证集10万 |
| 0.2 训练DistilBERT+ONNX | `scripts/train_news_classifier.py`        | 第2-3天 | 0.1完成          | AutoDL 2小时，F1>0.92  |
| 0.3 部署到新加坡        | `TrendRadar/scripts/classifier_server.py` | 第4天   | 0.2模型就绪      | CPU推理一条<10ms       |
| 0.4 接入pipeline跑全量  | 修改 `trendradar/__main__.py`             | 第5-7天 | 0.3完成          | 日处理5000+条，噪音<5% |

**模型输出：** `models/classifier/news_filter_v1.onnx`（~70MB，部署于新加坡）

#### 阶段1：真实数据蒸馏（第2-4周）——并行路径B，与A同时推进

**核心逻辑：** 在TrendRadar的AI分析代码中加钩子，每次调用API时自动保存（输入→输出）对，每周用真实数据增量微调。

| 任务             | 文件                                        | 时间            | 完成标志                                                     |
| ---------------- | ------------------------------------------- | --------------- | ------------------------------------------------------------ |
| 1.1 缓冲池钩子   | 修改 `trendradar/ai/analyzer.py` _call_ai() | 第2周           | 每日自动收集分析数据到 `data/training_buffer/buffer_YYYY-MM-DD.jsonl` |
| 1.2 每周增量训练 | `scripts/weekly_incremental_train.py`       | 第3周开始每周日 | 训练后验证loss不高于上周                                     |
| 1.3 影子模式对比 | 同上 + `scripts/evaluate_shadow.py`         | 第3周开始持续   | 每周对比报告：情绪一致率、打分MAE                            |

#### 阶段2：多LoRA嵌入Pipeline（第3-8周）——路径C，依赖A

**核心逻辑：** 同一个Qwen2.5-1.5B基座+5个LoRA adapter，在pipeline不同环节各司其职。

| LoRA | 任务                   | 训练数据                      | 输出位置                           |
| ---- | ---------------------- | ----------------------------- | ---------------------------------- |
| A    | 新闻相关性打分（0-10） | 合成数据100万条               | `models/loras/lora_a_relevance/`   |
| B    | 情绪分类（3类）        | 合成数据80万条                | `models/loras/lora_b_sentiment/`   |
| C    | 紧急度判断（3级）      | 历史推送记录                  | `models/loras/lora_c_urgency/`     |
| D    | 跨平台去重（二分类）   | 正负样本对                    | `models/loras/lora_d_dedup/`       |
| E    | 决策归因（多分类）     | Feedback_and_Learning历史数据 | `models/loras/lora_e_attribution/` |

**LoRA管理器：** `TrendRadar/scripts/lora_manager.py`，负责按任务切换adapter

#### 阶段3：多节点分布式（第6-12周，可选）

| 节点                        | 运行的模型            | 负责任务             |
| --------------------------- | --------------------- | -------------------- |
| 新加坡（4GB/2核）           | ONNX + LoRA A+D       | 全量初筛 + 去重      |
| 阿里云（7.1GB，v3.0停产后） | Qwen1.5B + LoRA B+C+E | 情绪 + 紧急度 + 归因 |

### 15.3 核心文件清单

| 文件                             | 位置                                     | 用途                         |
| -------------------------------- | ---------------------------------------- | ---------------------------- |
| `prepare_classifier_data.py`     | `search_information/scripts/`            | 从合成数据提取分类器训练数据 |
| `train_news_classifier.py`       | `search_information/scripts/`            | 训练DistilBERT + 导出ONNX    |
| `classifier_server.py`           | `search_information/TrendRadar/scripts/` | ONNX模型加载 + 推理接口      |
| `weekly_incremental_train.py`    | `search_information/scripts/`            | LLaMAFactory增量训练包装     |
| `lora_manager.py`                | `search_information/TrendRadar/scripts/` | LoRA切换管理                 |
| `evaluate_shadow.py`             | `search_information/scripts/`            | 影子模式对比分析             |
| `training_buffer/buffer_*.jsonl` | `search_information/TrendRadar/data/`    | 每日AI分析缓冲池             |

### 15.4 和v1规划的核心区别

| 维度         | v1（旧规划）               | v2（当前规划）                    |
| ------------ | -------------------------- | --------------------------------- |
| **目标**     | 训练模型替代API            | 用模型放大API覆盖能力             |
| **主力模型** | Qwen2.5-7B LoRA            | DistilBERT ONNX + Qwen1.5B LoRA群 |
| **训练数据** | 依赖一次性合成数据         | 合成数据启动 + 真实数据持续蒸馏   |
| **部署位置** | 未明确（原计划AutoDL推理） | 新加坡CPU + 阿里云7GB             |
| **核心指标** | 模型准确率>90%             | 系统覆盖20倍 + API成本降50-70%    |
| **最快见效** | 2个月后                    | 2周后（ONNX分类器上线）           |

---

## 16. 数据契约（服务间接口规范）

### 契约1: search_information → analyse_information

**位置：** `TrendRadar/output/summaries/ai_summaries.jsonl`

```json
{
  "title": "新闻标题",                    // string, 必填
  "summary": "AI摘要",                   // string, 必填（最长500字）
  "platform_id": "twitter",              // string, 必填
  "url": "https://...",                  // string, 必填
  "created_at": "2026-05-29T10:30:00Z",  // string, ISO 8601
  "keyword_hits": ["特斯拉"],             // array[string], 命中关键词
  "priority_level": 1                     // integer: 1=高 2=中 3=低
}
```

### 契约2: analyse_information → invest

**位置：** `knowledge_base/analyzed/*.json`

```json
{
  "ticker": "TSLA",                    // 标的代码
  "decision": "buy",                   // 投资建议
  "confidence": 0.85,                  // 置信度0-1
  "key_factors": ["财报超预期"],       // 关键因素列表
  "timeline": "3个月",                 // 时间框架
  "risk": {"level": "medium", "factors": ["估值偏高"]}
}
```

### 契约3: invest → Feedback_and_Learning

**位置：** `invest/data/results/executions.json`

```json
{
  "batch_id": "batch_20260529_001",
  "fund_code": "110011",
  "action": "buy",
  "amount": 1000.0,
  "nav_at_execution": 2.345,
  "status": "executed",
  "created_at": "2026-05-29T10:30:00Z"
}
```

### 契约4: Feedback_and_Learning → invest / search_information

**位置：** `invest/data/knowledge/lessons.json`、`patterns.json`、`rules.json`

```json
{
  "lessons": [{"type": "profit", "content": "...", "confidence": 0.85}],
  "patterns": [{"name": "高收益模式", "conditions": {...}, "frequency": 12}],
  "rules": [{"type": "阈值调整", "target": "BUY_THRESHOLD", "new_value": 0.58}]
}
```

> 完整JSON Schema定义见 `search_information/.trae/documents/接口契约表.md`

---

## 17. 统一规划执行路线图

### 四线并行推进

```
时间线      第1周        第2周        第3周        第4周        第5周        第6周        第7周        第8周
线A(哨兵)   0.1→0.2→0.3→0.4稳定运行 → → → → → → → → → → → → → → → → → → → → → → → →
线B(小偷)   ╰────1.1缓冲钩子→1.2每周增量训练(周日)→1.3影子模式持续运行→ → → → → → → → →
线C(LoRA)                          ╰────2.1→2.2→2.3+2.4→2.5部署验证→ → →
线D(优化)   根基加固(P0) ═══╗        质量提升(P1) ═══╗     架构升级(P2) ═══╗    产品创新 ═══╗
                             ║                         ║                      ║               ║
            每日4条推送正常  ║        测试覆盖核心模块  ║     FastAPI改造      ║    智能推送定制║
            CI已加入测试    ║        HTTPS已配置       ║     多策略并行引擎   ║    决策透明度  ║
```

### 各阶段完成标志

| 阶段         | 时间          | 完成标志                                       |
| ------------ | ------------- | ---------------------------------------------- |
| **哨兵上线** | 第2周末       | ONNX分类器部署到新加坡，日处理5000+条，噪音<5% |
| **数据蒸馏** | 第3周开始持续 | 缓冲池每日自动收集，每周日自动增量训练         |
| **LoRA覆盖** | 第8周         | 5个LoRA adapter覆盖pipeline 5个环节            |
| **根基加固** | 第3周         | CI+日志+测试+缓存 deployed                     |
| **质量提升** | 第6周         | 核心测试覆盖率>60%，HTTPS+限流已配置           |
| **架构升级** | 第10周        | FastAPI+PostgreSQL+API网关上线                 |

### 三台服务器的角色演变

```
当前:    新加坡(8容器)    阿里云(v3.0生成器)      AutoDL(训练)
第2周:   +ONNX分类器         +生成器继续           训练DistilBERT
第4周:   +LoRA A+D          生成器停机             增量训练Qwen1.5B
第8周:   所有LoRA运行        +LoRA B+C+E推理节点    按需训练
第12周:  持续优化            持续优化               可选节点
```

### 关键决策原则

1. **先做"不动代码"的优化**：AI响应缓存（输入哈希→SQLite）纯配置级改动，2小时上线，省30-50% API费用
2. **先用极小的模型**：DistilBERT（70MB）而不是Qwen1.5B（3GB），CPU可跑，2天部署
3. **数据和训练分离**：合成数据用于启动，真实数据用于迭代，两套数据管线互不干扰
4. **影子模式优先**：新模型先做影子输出对比，不替换现有流程，确认质量后再切换
5. **不追求模型替代API**：小模型做分类/排序/过滤，API做深度分析/复杂推理，各司其职

---

> 详细文档索引：
>
> - 完整项目总览 → `search_information/.trae/documents/整个项目.md`
> - 功能说明 → `search_information/.trae/documents/功能.md`
> - 注意事项 → `search_information/.trae/documents/注意.md`
> - 问题追踪 → `search_information/.trae/documents/问题.md`
> - 综合优化 → `search_information/.trae/documents/优化/综合优化文档.md`
> - 60天训练计划 → `search_information/.trae/documents/训练模型/60天训练计划.md`
> - 训练模型部署规划（v2）→ `训练模型目录 · 全面深度分析.md`
> - 接口契约 → `search_information/.trae/documents/接口契约表.md`
> - 执行命令手册 → `search_information/.trae/documents/执行.md`
> - 服务器状态 → `search_information/.trae/documents/训练模型/Digital_Ocean服务器.md`、`阿里云服务器.md`
