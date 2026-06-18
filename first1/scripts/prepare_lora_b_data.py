#!/usr/bin/env python3
"""从清洗后的合成数据中提取情绪/分类数据，准备LoRA-B训练"""
import json, os, random
from collections import defaultdict

# 阿里云上的清洗数据
CLEAN_FILE = "/root/generated_v3_clean/train_v3_clean.jsonl"
OUTPUT_DIR = "/root/lora_data/sentiment"
os.makedirs(OUTPUT_DIR, exist_ok=True)

sentiment_samples = []
task_stats = defaultdict(int)

with open(CLEAN_FILE, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
            conv = d.get("conversations", [])
            meta = d.get("meta", {})
            task = meta.get("task", "")
            task_stats[task] += 1

            if len(conv) < 2:
                continue

            human = conv[0].get("value", "")
            gpt = conv[1].get("value", "")

            # 提取标题（从human消息中提取新闻标题）
            title = human
            # 去掉指令前缀
            for prefix in ["新闻：", "内容：", "新闻："]:
                if prefix in human:
                    title = human.split(prefix)[-1].strip()
                    break

            # 情绪分析任务 → sentiment字段
            if task == "情绪分析":
                sentiment = gpt.strip()
                # 标准化情绪值
                if "正面" in sentiment or "积极" in sentiment:
                    sent_label = "正面"
                    score = 8
                elif "负面" in sentiment or "消极" in sentiment:
                    sent_label = "负面"
                    score = 3
                else:
                    sent_label = "中性"
                    score = 5
                sentiment_samples.append({
                    "title": title[:200],
                    "content": "",
                    "sentiment": sent_label,
                    "score": score,
                })

            # 相关性打分 → score字段
            elif task == "相关性打分":
                try:
                    score = int(''.join(filter(str.isdigit, gpt)) or 5)
                    score = max(0, min(10, score))
                    sentiment_samples.append({
                        "title": title[:200],
                        "content": "",
                        "sentiment": "",
                        "score": score,
                    })
                except:
                    pass

            # 新闻分类 → category字段
            elif task == "新闻分类":
                category = gpt.strip()[:30]
                sentiment_samples.append({
                    "title": title[:200],
                    "content": "",
                    "category": category,
                    "sentiment": "",
                    "score": 0,
                })

        except Exception:
            continue

print(f"任务分布:")
for t, c in sorted(task_stats.items(), key=lambda x: -x[1]):
    print(f"  {t}: {c}")

print(f"\n提取的情绪样本: {len(sentiment_samples)}")
print(f"  情绪分析: {sum(1 for s in sentiment_samples if s.get('sentiment'))}")
print(f"  相关性打分: {sum(1 for s in sentiment_samples if s.get('score',0)>0 and not s.get('sentiment'))}")
print(f"  新闻分类: {sum(1 for s in sentiment_samples if s.get('category'))}")

random.shuffle(sentiment_samples)

# 90% train, 10% val
split = int(len(sentiment_samples) * 0.9)
train = sentiment_samples[:split]
val = sentiment_samples[split:]

with open(os.path.join(OUTPUT_DIR, "train.jsonl"), "w", encoding="utf-8") as f:
    for s in train:
        f.write(json.dumps(s, ensure_ascii=False) + "\n")

with open(os.path.join(OUTPUT_DIR, "val.jsonl"), "w", encoding="utf-8") as f:
    for s in val:
        f.write(json.dumps(s, ensure_ascii=False) + "\n")

print(f"\n训练集: {len(train)} 条")
print(f"验证集: {len(val)} 条")
print(f"输出目录: {OUTPUT_DIR}")
print(f"输出大小: {os.path.getsize(os.path.join(OUTPUT_DIR, 'train.jsonl'))/1024/1024:.1f} MB")
