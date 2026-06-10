# 资讯捕手 · AI 金融分析系统 (FinSight)

> **三台服务器协同的全自动金融情报流水线**  
> 数据采集 → AI 分析 → 投资决策 → 反馈学习, 7×24 小时无人值守

---

## 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                     Layer 1: 哨兵 (ONNX)                     │
│           新加坡 4GB CPU, 10ms/条, 日处理 5000+ 条           │
│    情绪分类(256KB) + 新闻分类(130MB) + 相关度(130MB)        │
└─────────────────────────┬───────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│                  Layer 2: 榫卯 (LoRA)                        │
│                  阿里云 7GB, 2-60s/条                        │
│        相关评分 + 紧急度判断 + 情绪细粒度                    │
└─────────────────────────┬───────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│                 Layer 3: 深度分析 (API)                       │
│              DeepSeek / MiMo, 500ms-5s/条                   │
│             个性化建议 + 市场情绪 + 风险预警                 │
└─────────────────────────┬───────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│                   决策与反馈                                  │
│    8因子加权决策 → 状态机执行 → 反馈学习 → 规则优化         │
└─────────────────────────────────────────────────────────────┘
```

## 核心技术栈

| 层 | 技术 | 部署 |
|----|------|------|
| 采集 | Python, SQLite, 11平台热搜+20RSS源 | Docker (新加坡) |
| 哨兵推理 | ONNX Runtime, CPU 10ms | 新加坡 4GB |
| 精排推理 | Qwen1.5B + LoRA (PEFT) | 阿里云 7GB |
| 深度分析 | DeepSeek / MiMo API | API 服务 |
| 模型训练 | PyTorch, DistilBERT, Optimum | AutoDL GPU |
| 数据工程 | 自研两代生成器, 162 万条 | 阿里云 |
| 推送 | 钉钉机器人 × 9 渠道 | 通知中心 |
| 仪表盘 | Next.js, Chart.js, Zustand | invest-frontend |
| 部署 | Docker, systemd, SSH 隧道 | 三服务器 |

## 数据流水线

```
热搜榜 11 平台 ──→  ONNX 哨兵(10ms分类) ──→ LoRA 精排
(RSS 20 金融源)        (情绪/分类/相关)      (相关/紧急度)
                            │
                      DeepSeek 深度分析
                      (个性化建议/预警)
                            │
                     决策引擎(8因子)
                     执行引擎(状态机)
                     反馈学习(模式识别)
```

## 模型清单

| 模型 | 类型 | 大小 | 任务 | 状态 |
|------|------|------|------|------|
| Sentiment v3 | DistilBERT ONNX | 256MB | 情绪分类(positive/negative/neutral) | ✅ 在线 |
| Category | DistilBERT ONNX | 130MB | 新闻分类(科技/政策/综合) | ✅ 在线 |
| Relevance | DistilBERT ONNX | 130MB | 相关度判定(relevant/irrelevant) | ✅ 在线 |
| Relevance LoRA | Qwen1.5B + LoRA | 166MB | 精细相关评分(0-10) | ✅ 在线 |
| Urgency LoRA | Qwen1.5B + LoRA | 341MB | 紧急度判断(高/中/低) | ✅ 在线 |

## 部署架构

```
新加坡 DigitalOcean (4GB/2核)
├── trendradar          → 采集+AI分析
├── invest-backend      → 决策引擎
├── notification-center → 钉钉推送
├── dashboard           → Web仪表盘
├── semantic-search     → RAG检索
├── invest-frontend     → Next.js
├── feedback-learner    → 反馈学习
├── classifier-server   → ONNX哨兵
└── sentiment-service   → PyTorch情绪

阿里云 ECS (7GB)
├── LoRA 推理服务
├── 合成数据生成器
└── SSH 隧道 → 新加坡

AutoDL (按需 GPU)
└── DistilBERT/LoRA 训练
```

## 快速开始

```bash
# 训练情绪分类模型
python3 models/train_sentiment.py

# 启动 ONNX 哨兵服务
python3 services/classifier_server.py --serve --port 5080

# 启动 PyTorch 情绪服务
python3 services/sentiment_service.py

# 全量 Docker 部署
cd deploy && docker compose up -d
```

## 项目亮点

1. **多层推理架构**：ONNX(10ms) → LoRA(秒级) → API(500ms)，在 4GB 低配服务器实现替代 3GB 大模型的方案
2. **162 万条自研数据**：两代生成器产出大规模金融新闻训练数据，支撑模型迭代
3. **全自动化**：8 个 Docker 容器无人值守，每天自动采集→分析→决策→推送→学习
4. **全栈独立开发**：从数据工程、模型训练、服务部署到前端仪表盘，均为个人完成

> 📌 本项目为个人独立项目，所有投资决策均为模拟交易，不构成投资建议。
