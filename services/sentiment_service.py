#!/usr/bin/env python3
"""
PyTorch 情绪分析服务

加载训练好的 DistilBERT 模型，提供 REST API 情绪分类。
替代 ONNX 哨兵中的情绪模型，精度更高。

用法:
    python3 sentiment_service.py          # 启动服务 (端口 5083)
    curl http://localhost:5083/health     # 健康检查
    curl -X POST http://localhost:5083/infer \\
      -H "Content-Type: application/json" \\
      -d '{"texts":["A股暴涨5%","美股暴跌"]}'
"""
import torch, json
from http.server import HTTPServer, BaseHTTPRequestHandler
from transformers import AutoTokenizer, AutoModelForSequenceClassification

MODEL_PATH = "/root/models/sentiment_pytorch"
PORT = 5083
id2label = {0: "positive", 1: "negative", 2: "neutral"}

model = None
tokenizer = None

def load_model():
    global model, tokenizer
    model = AutoModelForSequenceClassification.from_pretrained(MODEL_PATH)
    model.eval()
    tokenizer = AutoTokenizer.from_pretrained("distilbert-base-uncased")

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_json({"status": "ok"})
        else:
            self.send_error(404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        texts = body.get("texts", body.get("text", []))
        if isinstance(texts, str):
            texts = [texts]

        inputs = tokenizer(texts, return_tensors="pt",
                          padding=True, truncation=True, max_length=128)
        with torch.no_grad():
            logits = model(**inputs).logits
            preds = torch.argmax(logits, dim=1)

        results = []
        for i, p in enumerate(preds):
            prob = torch.softmax(logits[i], dim=0)[p].item()
            results.append({
                "label": id2label[p.item()],
                "score": round(prob, 4),
            })
        self.send_json({"results": results})

    def send_json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def log_message(self, fmt, *args):
        pass

if __name__ == "__main__":
    print(f"Loading model from {MODEL_PATH}...")
    load_model()
    print(f"Starting server on port {PORT}...")
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
