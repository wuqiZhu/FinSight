#!/usr/bin/env python3
"""清洗合成数据：仅去重完全重复的指令-回复对，保留多样性"""
import json, os, hashlib, random
from collections import defaultdict

DATA_DIR = "/root/generated_v3"
OUTPUT_DIR = "/root/generated_v3_clean"
os.makedirs(OUTPUT_DIR, exist_ok=True)

files = sorted([f for f in os.listdir(DATA_DIR) if f.endswith(".jsonl")])
print(f"输入文件: {len(files)} 个")

all_samples = []
total = 0
seen_pair = set()
empty_count = 0
dup_count = 0
task_counts = defaultdict(int)
type_counts = defaultdict(int)

for fname in files:
    path = os.path.join(DATA_DIR, fname)
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                d = json.loads(line)
                conv = d.get("conversations", [])
                if len(conv) < 2:
                    continue
                human = conv[0].get("value", "")
                gpt = conv[1].get("value", "")
                if not gpt.strip():
                    empty_count += 1
                    continue
                # 仅对完全重复的 (human+gpt) 对去重
                pair_key = hashlib.md5((human + "|||" + gpt).encode()).hexdigest()
                if pair_key in seen_pair:
                    dup_count += 1
                    continue
                seen_pair.add(pair_key)
                all_samples.append(d)
                meta = d.get("meta", {})
                task_counts[meta.get("task", "unknown")] += 1
                type_counts[meta.get("type", "unknown")] += 1
            except Exception:
                continue

random.shuffle(all_samples)

output_file = os.path.join(OUTPUT_DIR, "train_v3_clean.jsonl")
with open(output_file, "w", encoding="utf-8") as f:
    for d in all_samples:
        f.write(json.dumps(d, ensure_ascii=False) + "\n")

print(f"\n{'='*50}")
print(f"清洗报告（仅去重完全相同的指令-回复对）")
print(f"{'='*50}")
print(f"原始总数:     {total}")
print(f"空回复过滤:   {empty_count}")
print(f"完全重复对:   {dup_count} ({dup_count/total*100:.1f}%)")
print(f"清洗后:       {len(all_samples)}")
print(f"输出文件:     {output_file}")
print(f"文件大小:     {os.path.getsize(output_file)/1024/1024:.1f} MB")
print()
print("任务分布:")
for task, count in sorted(task_counts.items(), key=lambda x: -x[1]):
    pct = count / len(all_samples) * 100
    bar = "█" * max(int(pct / 2), 1)
    print(f"  {task:<10s} {count:>6} ({pct:.1f}%) {bar}")
print()
print(f"长文本: {type_counts.get('long', 0)} ({type_counts.get('long',0)/len(all_samples)*100:.1f}%)")
print(f"短文本: {type_counts.get('short', 0)} ({type_counts.get('short',0)/len(all_samples)*100:.1f}%)")
