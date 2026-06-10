#!/usr/bin/env python3
"""
训练风险提示二分类 ONNX 模型
从 v2.2 数据中提取"风险提示"样本 vs 其他新闻，判断是否涉及风险。
"""
import json, os, time, random, re
from transformers import AutoTokenizer, AutoModelForSequenceClassification, TrainingArguments, Trainer, DataCollatorWithPadding
from datasets import Dataset
import torch, numpy as np
from collections import Counter

DATA_PATH = "/root/train_scenarios_v2.2.jsonl"
OUTPUT_DIR = "/root/models/risk_classifier"
os.makedirs(OUTPUT_DIR, exist_ok=True)

id_to_label = {0: "risk", 1: "normal"}
label_to_name = {0: "风险", 1: "正常"}

# 风险关键词
RISK_KW = ["风险","警告","预警","违约","破产","退市","爆雷","踩雷","暴跌","熔断","崩盘","处罚","制裁","调查","诉讼","叫停","暂停","约谈","罚款","降级","失信","坏账","亏损"]

print("扫描 v2.2 数据中的风险样本...")
texts, labels = [], []
risk_count = 0
normal_count = 0
with open(DATA_PATH) as f:
    for i, line in enumerate(f):
        if "风险" not in line and "risk" not in line.lower():
            if normal_count >= 30000: continue
        d = json.loads(line)
        human = d["conversations"][0]["value"]
        for p in ["新闻：", "新闻:", "内容：", "内容:"]:
            if p in human:
                title = human.split(p)[-1].strip()
                break
        else:
            title = human.strip()
        if len(title) < 4: continue

        # 判断是否风险相关
        is_risk = any(kw in title for kw in RISK_KW) or "风险" in human
        if is_risk:
            labels.append(0)
            risk_count += 1
        else:
            if normal_count >= 30000: continue
            labels.append(1)
            normal_count += 1
        texts.append(title[:200])

        if risk_count >= 15000 and normal_count >= 15000:
            break

print(f"风险: {risk_count}  正常: {normal_count}  总计: {len(texts)}")

random.shuffle(list(zip(texts, labels)))
data = list(zip(texts, labels))
random.shuffle(data)
split = int(len(data) * 0.9)
train_texts = [x[0] for x in data[:split]]
train_labels = [x[1] for x in data[:split]]
val_texts = [x[0] for x in data[split:]]
val_labels = [x[1] for x in data[split:]]
print(f"训练:{len(train_texts)} 验证:{len(val_texts)}")

tokenizer = AutoTokenizer.from_pretrained("distilbert-base-uncased")
train_enc = tokenizer(train_texts, truncation=True, max_length=128, padding=False)
val_enc = tokenizer(val_texts, truncation=True, max_length=128, padding=False)
train_dataset = Dataset.from_dict({"input_ids": train_enc["input_ids"], "attention_mask": train_enc["attention_mask"], "labels": train_labels})
val_dataset = Dataset.from_dict({"input_ids": val_enc["input_ids"], "attention_mask": val_enc["attention_mask"], "labels": val_labels})

model = AutoModelForSequenceClassification.from_pretrained("distilbert-base-uncased", num_labels=2)
model.config.label2id = {"risk": 0, "normal": 1}
model.config.id2label = {"0": "risk", "1": "normal"}

args = TrainingArguments(
    output_dir=os.path.join(OUTPUT_DIR, "checkpoints"),
    per_device_train_batch_size=64, per_device_eval_batch_size=128,
    num_train_epochs=3, learning_rate=2e-5, warmup_ratio=0.1,
    logging_steps=50, eval_strategy="epoch", save_strategy="epoch",
    save_total_limit=1, load_best_model_at_end=True, report_to="none", fp16=True,
)
trainer = Trainer(model=model, args=args, train_dataset=train_dataset, eval_dataset=val_dataset,
                  tokenizer=tokenizer, data_collator=DataCollatorWithPadding(tokenizer))

print("训练...")
t0 = time.time()
trainer.train()
print(f"完成:{time.time()-t0:.0f}s")

# 测试
tests = ["业绩暴雷股价腰斩", "央行发布货币政策报告", "A股三大指数小幅上涨", "某公司涉嫌财务造假被立案调查", "今日市场震荡整理"]
inputs = tokenizer(tests, return_tensors="pt", padding=True, truncation=True)
inputs = {k: v.to(model.device) for k, v in inputs.items()}
preds = torch.argmax(model(**inputs).logits, dim=1)
for t, p in zip(tests, preds):
    print(f"  {t[:25]:25s} -> {id_to_label[p.item()]}")

# 导出 ONNX
print("导出ONNX...")
model.eval()
dummy = (torch.randint(0,1000,(1,128)), torch.ones(1,128,dtype=torch.long))
torch.onnx.export(model, dummy, os.path.join(OUTPUT_DIR,"model.onnx"),
    input_names=["input_ids","attention_mask"], output_names=["logits"],
    dynamic_axes={"input_ids":{0:"batch"},"attention_mask":{0:"batch"},"logits":{0:"batch"}}, opset_version=11)
tokenizer.save_pretrained(OUTPUT_DIR)
with open(os.path.join(OUTPUT_DIR,"model_config.json"),"w") as f:
    json.dump({"num_labels":2,"label2id":{"risk":0,"normal":1},"id2label":{"0":"risk","1":"normal"}}, f, indent=2)
size = os.path.getsize(os.path.join(OUTPUT_DIR,"model.onnx")) // 1024
print(f"OK: {size}KB")
