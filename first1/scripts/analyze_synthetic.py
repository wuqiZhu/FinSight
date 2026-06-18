#!/usr/bin/env python3
"""分析阿里云上的合成数据质量"""
import json, os
from collections import defaultdict, Counter

DATA_DIR = "/root/generated_v3"
files = sorted([f for f in os.listdir(DATA_DIR) if f.endswith(".jsonl")])

total = 0
task_counts = defaultdict(int)
type_counts = defaultdict(int)
total_chars = 0
min_chars = float("inf")
max_chars = 0
short_samples = 0
dup_human = set()
dup_gpt = set()
human_dup = 0
gpt_dup = 0
chars_dist = {"<50": 0, "50-200": 0, "200-500": 0, "500+": 0}

for fname in files:
    path = os.path.join(DATA_DIR, fname)
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                total += 1
                meta = d.get("meta", {})
                task = meta.get("task", "unknown")
                ttype = meta.get("type", "unknown")
                task_counts[task] += 1
                type_counts[ttype] += 1

                conv = d.get("conversations", [])
                if len(conv) >= 2:
                    human = conv[0].get("value", "")
                    gpt = conv[1].get("value", "")
                    chars = len(gpt)
                    total_chars += chars

                    if chars < min_chars:
                        min_chars = chars
                    if chars > max_chars:
                        max_chars = chars

                    if chars < 50:
                        short_samples += 1
                        chars_dist["<50"] += 1
                    elif chars < 200:
                        chars_dist["50-200"] += 1
                    elif chars < 500:
                        chars_dist["200-500"] += 1
                    else:
                        chars_dist["500+"] += 1

                    if human in dup_human:
                        human_dup += 1
                    dup_human.add(human)

                    gpt_key = gpt[:100]
                    if gpt_key in dup_gpt:
                        gpt_dup += 1
                    dup_gpt.add(gpt_key)
            except Exception:
                pass

print(f"总样本: {total}")
print()

if total > 0:
    print(f"平均长度: {total_chars/total:.0f} 字符")
    print(f"最短: {min_chars}  最长: {max_chars}")
    print()

    print("字数分布:")
    for r, c in sorted(chars_dist.items()):
        bar = "█" * min(c // max(total // 40, 1), 40)
        print(f"  {r}: {c:>6} ({c/total*100:.1f}%) {bar}")

    print()
    print(f"指令去重: {human_dup} 条重复 ({human_dup/total*100:.1f}%)")
    print(f"回复去重: {gpt_dup} 条重复")
    print(f"过短(<50字符): {short_samples} 条 ({short_samples/total*100:.1f}%)")
    print()

    print("任务分布:")
    for task, count in sorted(task_counts.items(), key=lambda x: -x[1]):
        bar = "█" * min(count // max(total // 40, 1), 40)
        print(f"  {task}: {count:>5} ({count/total*100:.1f}%) {bar}")

    print()
    print("类型:")
    for t, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"  {t}: {count} ({count/total*100:.1f}%)")
else:
    print("!!! 没有数据")
