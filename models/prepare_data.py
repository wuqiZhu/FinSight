#!/usr/bin/env python3
"""
金融新闻情绪数据准备

从大规模金融新闻语料中提取情绪分析样本，
基于金融关键词规则自动打标 (正面/负面/中性)。

数据来源: v2.2 合成数据 (162 万条)
输出: 供 train_sentiment.py 使用的 JSONL 训练文件

用法:
    python3 prepare_data.py --input data.jsonl --output ./data/
"""
import json, re, random, argparse
from collections import Counter

# 情绪词典
STRONG_POS = ["暴涨","飙升","沸腾","涨停","创新高","井喷","暴增","翻倍","超预期","重大利好"]
STRONG_NEG = ["暴跌","熔断","崩盘","跌停","创新低","跳水","爆雷","踩雷","违约","破产","退市","巨亏"]
MEDIUM_POS = ["上涨","回升","反弹","回暖","复苏","增长","盈利","政策利好","净流入","突破","走强","领涨"]
MEDIUM_NEG = ["下跌","回落","下滑","走弱","疲软","利空","承压","净流出","减持","失守","跌破","亏损"]

def compute_sentiment(title):
    """基于关键词规则打分"""
    score, weight = 0.0, 0
    for w in STRONG_POS:
        if w in title: score += 1.0; weight += 1
    for w in STRONG_NEG:
        if w in title: score -= 1.0; weight += 1
    for w in MEDIUM_POS:
        if w in title: score += 0.6; weight += 1
    for w in MEDIUM_NEG:
        if w in title: score -= 0.6; weight += 1

    if weight == 0: return "中性", 0.3
    avg = score / weight
    if avg > 0.15: return "正面", round(min(abs(avg)*1.2, 1.0), 2)
    elif avg < -0.15: return "负面", round(min(abs(avg)*1.2, 1.0), 2)
    return "中性", 0.3

def extract_titles(data_path):
    """从原始数据提取新闻标题"""
    titles = []
    for line in open(data_path, encoding="utf-8"):
        d = json.loads(line)
        conv = d.get("conversations", [])
        if len(conv) < 2: continue
        human = conv[0].get("value", "")
        # 从 human prompt 提取标题
        for p in ["新闻：", "新闻:", "内容：", "内容:"]:
            if p in human:
                title = human.split(p)[-1].strip()
                if len(title) >= 4:
                    titles.append(title)
                break
    return titles

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="输入 JSONL 文件")
    parser.add_argument("--output", default="./data/", help="输出目录")
    args = parser.parse_args()

    os.makedirs(args.output, exist_ok=True)
    print(f"提取标题: {args.input}")
    titles = extract_titles(args.input)
    print(f"共提取 {len(titles)} 条标题")

    samples = []
    stats = Counter()
    for title in titles:
        label, intensity = compute_sentiment(title)
        stats[label] += 1
        samples.append({
            "title": title[:200],
            "sentiment": label,
            "intensity": intensity,
        })

    print(f"分布: 正面{stats['正面']} 负面{stats['负面']} 中性{stats['中性']}")

    random.shuffle(samples)
    split = int(len(samples) * 0.9)
    for name, data in [("train.jsonl", samples[:split]), ("val.jsonl", samples[split:])]:
        path = os.path.join(args.output, name)
        with open(path, "w", encoding="utf-8") as f:
            for s in data:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")
        print(f"写入 {path}: {len(data)} 条")

if __name__ == "__main__":
    import os
    main()
