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

# 用本地已有的情绪数据训练（已在 AutoDL 上）
DATA_PATH = "/root/lora_data/sentiment_v2/emotion_train.jsonl"
OUTPUT_DIR = "/root/models/risk_classifier"
os.makedirs(OUTPUT_DIR, exist_ok=True)

id_to_label = {0: "risk", 1: "normal"}
label_to_name = {0: "风险", 1: "正常"}

# 风险关键词
RISK_KW = ["风险","警告","预警","违约","破产","退市","爆雷","踩雷","暴跌","熔断","崩盘","处罚","制裁","调查","诉讼","叫停","暂停","约谈","罚款","降级","失信","坏账","亏损"]

print("提取风险样本...")
texts, labels = [], []
for line in open(DATA_PATH):
    d = json.loads(line)
    title = d["title"]
    is_risk = any(kw in title for kw in RISK_KW)
    if is_risk:
        texts.append(title)
        labels.append(0)
    elif len([l for l in labels if l == 1]) < 15000:
        texts.append(title)
        labels.append(1)

print(f"风险: {sum(1 for l in labels if l==0)}  正常: {sum(1 for l in labels if l==1)}  总计: {len(labels)}")

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
tests = ["业绩暴雷股价腰斩", "央行发布货币政策报告", "某公司涉嫌财务造假被立案调查", "今日市场震荡整理"]
inputs = tokenizer(tests, return_tensors="pt", padding=True, truncation=True)
inputs = {k: v.to(model.device) for k, v in inputs.items()}
preds = torch.argmax(model(**inputs).logits, dim=1)
for t, p in zip(tests, preds):
    print(f"  {t[:25]:25s} -> {id_to_label[p.item()]}")

print("导出ONNX...")
model.eval()
dummy = (torch.randint(0,1000,(1,128)), torch.ones(1,128,dtype=torch.long))
torch.onnx.export(model, dummy, os.path.join(OUTPUT_DIR,"model.onnx"),
    input_names=["input_ids","attention_mask"], output_names=["logits"],
    dynamic_axes={"input_ids":{0:"batch"},"attention_mask":{0:"batch"},"logits":{0:"batch"}}, opset_version=11)
tokenizer.save_pretrained(OUTPUT_DIR)
with open(os.path.join(OUTPUT_DIR,"model_config.json"),"w") as f:
    json.dump({"num_labels":2,"label2id":{"risk":0,"normal":1},"id2label":{"0":"risk","1":"normal"}}, f, indent=2)
import onnxruntime
s = onnxruntime.InferenceSession(os.path.join(OUTPUT_DIR,"model.onnx"))
print(f"OK: {os.path.getsize(os.path.join(OUTPUT_DIR,'model.onnx'))//1024}KB")
