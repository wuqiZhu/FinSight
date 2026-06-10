#!/usr/bin/env python3
"""
训练 DistilBERT 情绪分类模型，导出 ONNX

从金融新闻标题中训练情绪分类器 (positive/negative/neutral)，
使用类别加权处理不平衡数据，最终导出 ONNX 部署到 CPU。

用法:
    python3 train_sentiment.py
"""
import json, os, time, random
from transformers import (
    AutoTokenizer, AutoModelForSequenceClassification,
    TrainingArguments, Trainer, DataCollatorWithPadding
)
from datasets import Dataset
import torch
from collections import Counter

# 数据路径（请根据实际位置修改）
DATA_DIR = os.environ.get("FIN_DATA_DIR", "./data")
TRAIN_PATH = os.path.join(DATA_DIR, "train.jsonl")
VAL_PATH = os.path.join(DATA_DIR, "val.jsonl")
OUTPUT_DIR = os.environ.get("FIN_OUTPUT_DIR", "./models/sentiment")

id_to_label = {0: "positive", 1: "negative", 2: "neutral"}
label_to_id = {"正面": 0, "负面": 1, "中性": 2}

def load_data(path):
    texts, labels = [], []
    for line in open(path):
        d = json.loads(line)
        texts.append(d["title"])
        labels.append(label_to_id[d["sentiment"]])
    return texts, labels

def balance_data(texts, labels):
    """平衡采样：负面上采样，中性下采样"""
    from collections import Counter
    idx = list(range(len(labels)))
    pos = [i for i in idx if labels[i] == 0]
    neg = [i for i in idx if labels[i] == 1]
    neu = [i for i in idx if labels[i] == 2]

    # 负面上采样到与正面持平
    target_neg = len(pos)
    neg_up = (neg * (target_neg // len(neg) + 1))[:target_neg]

    # 中性压缩
    max_neu = int((len(pos) + target_neg) * 0.6)
    random.shuffle(neu)
    neu_down = neu[:max_neu]

    keep = pos + neg_up + neu_down
    return [texts[i] for i in keep], [labels[i] for i in keep]

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    train_texts, train_labels = load_data(TRAIN_PATH)
    val_texts, val_labels = load_data(VAL_PATH)

    train_texts, train_labels = balance_data(train_texts, train_labels)

    dist = Counter(train_labels)
    print(f"训练: {len(train_texts)}  验证: {len(val_texts)}")
    print(f"分布: 正面{dist[0]} 负面{dist[1]} 中性{dist[2]}")

    tokenizer = AutoTokenizer.from_pretrained("distilbert-base-uncased")
    train_enc = tokenizer(train_texts, truncation=True, max_length=128, padding=False)
    val_enc = tokenizer(val_texts, truncation=True, max_length=128, padding=False)

    train_dataset = Dataset.from_dict({
        "input_ids": train_enc["input_ids"],
        "attention_mask": train_enc["attention_mask"],
        "labels": train_labels,
    })
    val_dataset = Dataset.from_dict({
        "input_ids": val_enc["input_ids"],
        "attention_mask": val_enc["attention_mask"],
        "labels": val_labels,
    })

    model = AutoModelForSequenceClassification.from_pretrained(
        "distilbert-base-uncased", num_labels=3
    )
    model.config.label2id = {"positive": 0, "negative": 1, "neutral": 2}
    model.config.id2label = {"0": "positive", "1": "negative", "2": "neutral"}

    # 类别权重
    class_weights = torch.tensor([1.0, 1.5, 0.8])

    class WeightedTrainer(Trainer):
        def compute_loss(self, model, inputs, return_outputs=False, **kwargs):
            labels = inputs.pop("labels")
            outputs = model(**inputs)
            loss_fn = torch.nn.CrossEntropyLoss(weight=class_weights.to(model.device))
            loss = loss_fn(outputs.logits, labels)
            return (loss, outputs) if return_outputs else loss

    args = TrainingArguments(
        output_dir=os.path.join(OUTPUT_DIR, "checkpoints"),
        per_device_train_batch_size=64,
        per_device_eval_batch_size=128,
        num_train_epochs=3,
        learning_rate=2e-5,
        warmup_ratio=0.1,
        logging_steps=50,
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=1,
        load_best_model_at_end=True,
        report_to="none",
        fp16=True,
    )

    trainer = WeightedTrainer(
        model=model, args=args,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
        tokenizer=tokenizer,
        data_collator=DataCollatorWithPadding(tokenizer),
    )

    trainer.train()
    trainer.evaluate()
    tokenizer.save_pretrained(OUTPUT_DIR)

    # 导出 ONNX
    model.eval()
    dummy = (torch.randint(0, 1000, (1, 128)), torch.ones(1, 128, dtype=torch.long))
    torch.onnx.export(model, dummy, os.path.join(OUTPUT_DIR, "model.onnx"),
        input_names=["input_ids", "attention_mask"],
        output_names=["logits"],
        dynamic_axes={
            "input_ids": {0: "batch"},
            "attention_mask": {0: "batch"},
            "logits": {0: "batch"},
        },
        opset_version=11,
    )
    print(f"Model exported to {OUTPUT_DIR}/model.onnx")

if __name__ == "__main__":
    main()
