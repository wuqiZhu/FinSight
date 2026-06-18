#!/usr/bin/env python3
"""
LoRA-B 情绪细粒度分类训练
基于 Qwen1.5-1.5B + LoRA
"""
import json, os, sys, logging, time
from transformers import (
    AutoModelForCausalLM, AutoTokenizer,
    TrainingArguments, Trainer, DataCollatorForSeq2Seq
)
from peft import LoraConfig, get_peft_model, TaskType
from datasets import Dataset
import torch

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
logger = logging.getLogger("train_lora_b")

MODEL_PATH = "/root/models/Qwen1.5-1.5B"
DATA_DIR = "/root/lora_data/sentiment"
OUTPUT_DIR = "/root/models/loras/lora_b_sentiment"
os.makedirs(OUTPUT_DIR, exist_ok=True)

def load_data(data_dir):
    train, val = [], []
    for fname, target in [("train.jsonl", train), ("val.jsonl", val)]:
        path = os.path.join(data_dir, fname)
        if not os.path.exists(path):
            logger.error(f"文件不存在: {path}")
            sys.exit(1)
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                target.append(json.loads(line))
    logger.info(f"加载数据: train={len(train)}, val={len(val)}")
    return train, val

def format_prompt(item):
    title = item.get("title", "")
    if item.get("sentiment"):
        return f"分析以下新闻的情绪：\n{title}\n\n情绪：{item['sentiment']}"
    elif item.get("score", 0) > 0:
        return f"评估以下新闻与投资的相关性（0-10分）：\n{title}\n\n评分：{item['score']}"
    elif item.get("category"):
        return f"将以下新闻分类：\n{title}\n\n类别：{item['category']}"
    return None

def main():
    train_data, val_data = load_data(DATA_DIR)

    train_texts = [format_prompt(x) for x in train_data if format_prompt(x)]
    val_texts = [format_prompt(x) for x in val_data if format_prompt(x)]
    logger.info(f"指令: train={len(train_texts)}, val={len(val_texts)}")

    tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    def tokenize_func(examples):
        texts = examples["text"]
        model_inputs = tokenizer(
            texts, max_length=256, truncation=True, padding=False
        )
        model_inputs["labels"] = model_inputs["input_ids"].copy()
        return model_inputs

    train_dataset = Dataset.from_dict({"text": train_texts})
    val_dataset = Dataset.from_dict({"text": val_texts})
    train_dataset = train_dataset.map(tokenize_func, batched=True, remove_columns=["text"])
    val_dataset = val_dataset.map(tokenize_func, batched=True, remove_columns=["text"])

    logger.info(f"加载模型: {MODEL_PATH}")
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_PATH,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True,
    )

    lora_config = LoraConfig(
        r=16, lora_alpha=32,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
        lora_dropout=0.05, bias="none",
        task_type=TaskType.CAUSAL_LM,
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    collator = DataCollatorForSeq2Seq(tokenizer, pad_to_multiple_of=8, padding=True)

    args = TrainingArguments(
        output_dir=os.path.join(OUTPUT_DIR, "checkpoints"),
        per_device_train_batch_size=32,
        per_device_eval_batch_size=64,
        num_train_epochs=1,
        learning_rate=2e-4,
        warmup_steps=50,
        logging_steps=10,
        eval_strategy="steps",
        eval_steps=50,
        save_strategy="steps",
        save_steps=50,
        save_total_limit=2,
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        report_to="none",
        fp16=True,
        dataloader_num_workers=2,
    )

    trainer = Trainer(
        model=model, args=args,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
        tokenizer=tokenizer,
        data_collator=collator,
    )

    logger.info("开始训练...")
    start = time.time()
    trainer.train()
    elapsed = time.time() - start
    logger.info(f"训练完成，耗时 {elapsed:.0f}s ({elapsed/60:.1f}min)")

    model.save_pretrained(OUTPUT_DIR)
    tokenizer.save_pretrained(OUTPUT_DIR)

    metrics = trainer.evaluate()
    logger.info(f"验证指标: {metrics}")

    config = {
        "task": "sentiment",
        "base_model": MODEL_PATH,
        "lora_config": {"r": 16, "alpha": 32, "target_modules": ["q_proj","k_proj","v_proj","o_proj"]},
        "training": {"epochs": 1, "batch_size": 32, "learning_rate": 2e-4, "elapsed_seconds": round(elapsed)},
        "metrics": {"val": metrics},
        "data": {"train_samples": len(train_texts), "val_samples": len(val_texts)},
    }
    with open(os.path.join(OUTPUT_DIR, "training_config.json"), "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    size_mb = sum(os.path.getsize(os.path.join(OUTPUT_DIR, f))
                  for f in os.listdir(OUTPUT_DIR) if os.path.isfile(os.path.join(OUTPUT_DIR, f))) / 1024 / 1024
    logger.info(f"✅ LoRA-B 训练完成!")
    logger.info(f"  adapter: {OUTPUT_DIR}")
    logger.info(f"  大小: {size_mb:.0f}MB")

if __name__ == "__main__":
    main()
