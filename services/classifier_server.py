#!/usr/bin/env python3
"""
ONNX 多模型分类器服务（哨兵）

同时加载多个 ONNX 模型，在 CPU 上对新闻进行实时分类。
设计为三层架构的第一层（哨兵层）：快、轻、量大。

用法:
    python3 classifier_server.py                          # 启动服务
    curl http://localhost:5080/health                     # 健康检查
    curl "http://localhost:5080/?model=sentiment&text=暴" # GET 推理
    curl -X POST http://localhost:5080/ -H "Content-Type: application/json" \\
      -d '{"model":"sentiment","texts":["A股暴涨","美股暴跌"]}'  # POST 批量
"""
import json, os, sys, time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import numpy as np

MODELS_DIR = Path(os.environ.get("MODELS_DIR", "./models"))
DEFAULT_MODELS = {
    "sentiment": {"dir": "sentiment", "description": "情绪分类"},
    "category": {"dir": "category", "description": "新闻分类"},
    "relevance": {"dir": "relevance", "description": "相关度判定"},
}

class ONNXClassifier:
    def __init__(self, models_dir=None):
        self.models_dir = Path(models_dir) if models_dir else MODELS_DIR
        self.sessions = {}
        self.tokenizers = {}
        self.configs = {}
        self._load_all()

    def _load_all(self):
        import onnxruntime
        from tokenizers import Tokenizer

        for name, info in DEFAULT_MODELS.items():
            model_dir = self.models_dir / info["dir"]
            # 搜索模型文件
            model_path = None
            for f in ["model_quant.onnx", "model_new.onnx", "model.onnx"]:
                p = model_dir / f
                if p.exists(): model_path = p; break
            if not model_path: continue

            # 加载 ONNX
            so = onnxruntime.SessionOptions()
            so.intra_op_num_threads = 2
            session = onnxruntime.InferenceSession(
                str(model_path), so, providers=["CPUExecutionProvider"])

            # 加载 tokenizer
            tok_path = model_dir / "tokenizer.json"
            tokenizer = None
            if tok_path.exists():
                tokenizer = Tokenizer.from_file(str(tok_path))
                tokenizer.enable_padding(pad_id=0, pad_token="[PAD]", length=128)
                tokenizer.enable_truncation(max_length=128)

            # 加载配置
            config = {}
            cfg_path = model_dir / "model_config.json"
            if cfg_path.exists():
                config = json.load(open(cfg_path))

            self.sessions[name] = session
            self.tokenizers[name] = tokenizer
            self.configs[name] = config
            print(f"[哨兵] ✅ {name}: {model_path.stat().st_size/1e6:.0f}MB")

    def predict(self, name, texts):
        if name not in self.sessions:
            raise ValueError(f"未知模型: {name}")
        single = isinstance(texts, str)
        if single: texts = [texts]

        tok = self.tokenizers.get(name)
        if tok:
            enc = tok.encode_batch(texts)
            ids = np.array([e.ids for e in enc], dtype=np.int64)
            mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
        else:
            raise RuntimeError(f"{name}: tokenizer 未加载")

        outputs = self.sessions[name].run(None, {
            self.sessions[name].get_inputs()[0].name: ids,
            self.sessions[name].get_inputs()[1].name: mask,
        })
        logits = outputs[0]
        probs = np.exp(logits - logits.max(axis=1, keepdims=True))
        probs /= probs.sum(axis=1, keepdims=True)

        id2label = self.configs[name].get("id2label", {})
        results = []
        for i in range(len(texts)):
            pred = int(np.argmax(probs[i]))
            label = id2label.get(str(pred), f"class_{pred}")
            results.append({"label": label, "label_id": pred, "score": float(round(probs[i][pred], 4))})
        return results[0] if single else results

class Handler(BaseHTTPRequestHandler):
    classifier = None

    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        params = parse_qs(urlparse(self.path).query)
        if self.path == "/health":
            models = {k: "ok" for k in self.classifier.sessions}
            self._json(200, {"status": "ok", "models": models})
        else:
            model = params.get("model", ["sentiment"])[0]
            text = params.get("text", [None])[0]
            if not text: self._json(400, {"error": "missing text"})
            else: self._json(200, self.classifier.predict(model, text))

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        texts = data.get("texts", [data.get("text", "")])
        model = data.get("model", "sentiment")
        try:
            results = self.classifier.predict(model, texts)
            self._json(200, {"results": results} if isinstance(results, list) else results)
        except Exception as e:
            self._json(400, {"error": str(e)})

    def _json(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
    def log_message(self, fmt, *args): pass

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5080))
    Handler.classifier = ONNXClassifier()
    print(f"[哨兵] 启动: 0.0.0.0:{port}")
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
