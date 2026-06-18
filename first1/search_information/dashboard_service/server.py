"""统一 Web Dashboard 服务

聚合四个项目的数据，提供统一的 Web 界面。

使用方式：
    python -m dashboard_service.server
    # 访问 http://localhost:5060
"""

import os
import json
import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path

try:
    from flask import Flask, jsonify, render_template_string, request
except ImportError:
    print("请安装 Flask: pip install flask")
    raise

logger = logging.getLogger(__name__)

app = Flask(__name__)

# 数据库路径配置
DB_PATHS = {
    "trendradar": os.environ.get("TRENDRADAR_DB", "../TrendRadar/data/trendradar.db"),
    "rss": os.environ.get("RSS_DB", "../TrendRadar/data/rss.db"),
    "analyse": os.environ.get("ANALYSE_DB", "../analyse_information/data/analyzed.db"),
    "jobs": os.environ.get("JOBS_DB", "../find_job/data/jobs.db"),
    "invest": os.environ.get("INVEST_DB", "../invest/data/fund_data.db"),
}


def find_latest_db(directory: str, pattern: str = "*.db") -> str:
    """查找目录中最新的数据库文件"""
    try:
        dir_path = Path(directory)
        if not dir_path.exists():
            return ""
        db_files = sorted(dir_path.glob(pattern), key=lambda f: f.stat().st_mtime, reverse=True)
        return str(db_files[0]) if db_files else ""
    except Exception:
        return ""


def resolve_db_path(name: str, default_path: str, alternatives: list = None) -> str:
    """智能解析数据库路径，支持多个备选路径"""
    path = Path(default_path)
    if path.exists():
        return default_path
    if alternatives:
        for alt in alternatives:
            alt_path = Path(alt)
            if alt_path.exists():
                return alt
    return default_path


def query_db(db_path: str, sql: str, params: tuple = ()) -> list:
    """安全查询数据库"""
    try:
        path = Path(db_path)
        if not path.exists():
            return []
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(sql, params)
        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results
    except Exception as e:
        logger.warning(f"数据库查询失败 {db_path}: {e}")
        return []


# API 路由

@app.route('/api/today')
def api_today():
    """获取今日数据概览"""
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    # TrendRadar 今日数据
    trend_count = query_db(
        DB_PATHS["trendradar"],
        "SELECT COUNT(*) as count FROM news_items WHERE created_at >= ?",
        (today,)
    )
    trend_signals = query_db(
        DB_PATHS["trendradar"],
        "SELECT title, platform_id as source, url, created_at as date FROM news_items WHERE created_at >= ? AND platform_id NOT IN ('weibo', 'douyin') ORDER BY created_at DESC LIMIT 10",
        (today,)
    )
    if not trend_signals:
        trend_signals = query_db(
            DB_PATHS["trendradar"],
            "SELECT title, platform_id as source, url, created_at as date FROM news_items WHERE created_at >= ? ORDER BY created_at DESC LIMIT 10",
            (today,)
        )

    # RSS 数据
    rss_count = query_db(
        DB_PATHS["rss"],
        "SELECT COUNT(*) as count FROM rss_items WHERE created_at >= ?",
        (today,)
    )

    # 分析数据（兼容 analyzer.db 和 analyzed.db，表名 processed_urls 和 analyzed）
    analyse_db = DB_PATHS["analyse"]
    analyse_count = query_db(
        analyse_db,
        "SELECT COUNT(*) as count FROM processed_urls WHERE created_at >= ?",
        (today,)
    )
    if not analyse_count:
        analyse_count = query_db(
            analyse_db,
            "SELECT COUNT(*) as count FROM analyzed WHERE created_at >= ?",
            (today,)
        )
    analyse_high = query_db(
        analyse_db,
        "SELECT title, score, category FROM processed_urls WHERE created_at >= ? AND score >= 7 ORDER BY score DESC LIMIT 10",
        (today,)
    )
    if not analyse_high:
        analyse_high = query_db(
            analyse_db,
            "SELECT title, score, category FROM analyzed WHERE created_at >= ? AND score >= 7 ORDER BY score DESC LIMIT 10",
            (today,)
        )

    # 求职数据
    job_count = query_db(
        DB_PATHS["jobs"],
        "SELECT COUNT(*) as count FROM jobs WHERE scraped_at >= ?",
        (today,)
    )
    job_high = query_db(
        DB_PATHS["jobs"],
        "SELECT title, company, score, url FROM jobs WHERE scraped_at >= ? AND score >= 70 ORDER BY score DESC LIMIT 10",
        (today,)
    )

    # 投资数据（从现有表生成预警，alerts表不存在时自动降级）
    invest_alerts = query_db(
        DB_PATHS["invest"],
        "SELECT fund_name, alert_type, message FROM alerts WHERE date >= ? ORDER BY date DESC LIMIT 10",
        (today,)
    )
    if not invest_alerts:
        invest_alerts = []
        drawdown_alerts = query_db(
            DB_PATHS["invest"],
            "SELECT fi.fund_name, fa.max_drawdown, fa.annualized_return FROM fund_analysis fa JOIN fund_info fi ON fa.fund_code = fi.fund_code WHERE fa.max_drawdown < -10 ORDER BY fa.analysis_date DESC LIMIT 5"
        )
        for row in drawdown_alerts:
            invest_alerts.append({
                "fund_name": row.get("fund_name", ""),
                "alert_type": "回撤预警",
                "message": f"最大回撤 {row.get('max_drawdown', 0):.1f}%"
            })
        profit_alerts = query_db(
            DB_PATHS["invest"],
            "SELECT fi.fund_name, ir.profit, ir.profit_rate FROM invest_records ir JOIN fund_info fi ON ir.fund_code = fi.fund_code WHERE ir.profit_rate > 15 OR ir.profit_rate < -10 ORDER BY ir.update_time DESC LIMIT 5"
        )
        for row in profit_alerts:
            rate = row.get("profit_rate", 0)
            if rate > 15:
                invest_alerts.append({
                    "fund_name": row.get("fund_name", ""),
                    "alert_type": "止盈提醒",
                    "message": f"收益率 {rate:.1f}%，考虑止盈"
                })
            elif rate < -10:
                invest_alerts.append({
                    "fund_name": row.get("fund_name", ""),
                    "alert_type": "止损提醒",
                    "message": f"亏损 {rate:.1f}%，注意风险"
                })

    return jsonify({
        "date": today,
        "trendradar": {
            "count": trend_count[0]["count"] if trend_count else 0,
            "signals": trend_signals,
        },
        "rss": {
            "count": rss_count[0]["count"] if rss_count else 0,
        },
        "analyse": {
            "count": analyse_count[0]["count"] if analyse_count else 0,
            "high_score": analyse_high,
        },
        "jobs": {
            "count": job_count[0]["count"] if job_count else 0,
            "high_score": job_high,
        },
        "invest": {
            "alerts": invest_alerts,
        },
    })


@app.route('/api/stats')
def api_stats():
    """获取统计数据"""
    # 各库总数据量
    stats = {}
    for name, path in DB_PATHS.items():
        try:
            if name == "trendradar":
                count = query_db(path, "SELECT COUNT(*) as count FROM news_items")
            elif name == "rss":
                count = query_db(path, "SELECT COUNT(*) as count FROM rss_items")
            elif name == "analyse":
                count = query_db(path, "SELECT COUNT(*) as count FROM processed_urls")
                if not count:
                    count = query_db(path, "SELECT COUNT(*) as count FROM analyzed")
            elif name == "jobs":
                count = query_db(path, "SELECT COUNT(*) as count FROM jobs")
            elif name == "invest":
                count = query_db(path, "SELECT COUNT(*) as count FROM fund_info")
                if not count:
                    count = query_db(path, "SELECT COUNT(*) as count FROM fund_data")
            else:
                count = [{"count": 0}]
            stats[name] = count[0]["count"] if count else 0
        except Exception:
            stats[name] = 0

    return jsonify(stats)


@app.route('/api/health')
def api_health():
    """健康检查"""
    db_status = {}
    for name, path in DB_PATHS.items():
        db_status[name] = Path(path).exists()

    return jsonify({
        "status": "ok",
        "databases": db_status,
        "timestamp": datetime.now().isoformat(),
    })


@app.route('/api/portal')
def api_portal():
    """统一门户 - 聚合所有关键数据"""
    import datetime as dt
    now = dt.datetime.now()
    result = {
        "timestamp": now.isoformat(),
        "time": now.strftime("%Y-%m-%d %H:%M"),
    }

    # 1. 健康状态
    result["health"] = {"status": "ok", "databases": {}}
    for name, path in DB_PATHS.items():
        result["health"]["databases"][name] = Path(path).exists() if path else False

    # 2. 数据库统计
    try:
        invest_db = DB_PATHS.get("invest", "")
        if invest_db and Path(invest_db).exists():
            conn = sqlite3.connect(invest_db)
            ns = conn.execute("SELECT COUNT(*) FROM news_sentiment").fetchone()[0]
            fn = conn.execute("SELECT COUNT(*) FROM fund_nav").fetchone()[0]
            fc = conn.execute("SELECT COUNT(DISTINCT fund_code) FROM fund_nav").fetchone()[0]
            result["db_stats"] = {"情绪数据": ns, "净值数据": fn, "基金数量": fc}
            conn.close()
    except: pass

    # 3. 新闻数据库
    try:
        nd = Path(DB_PATHS.get("trendradar", ""))
        if nd.exists():
            size = nd.stat().st_size
            result["news_db"] = {"size_kb": round(size/1024), "date": nd.stem}
    except: pass

    # 4. 情绪指数
    try:
        sentiment_file = Path(str(DB_PATHS.get("invest", "")).replace("fund_data.db", "sentiment/sentiment_history.json"))
        if sentiment_file.exists():
            with open(sentiment_file, "r") as f:
                hist = json.load(f)
            if hist:
                result["sentiment"] = hist[-1]
                result["sentiment_trend"] = [{"date": x.get("date"), "index": x.get("index")} for x in hist[-7:]]
    except: pass

    # 5. 统一入口说明
    result["commands"] = [
        {"cmd": "python3 server_status.py", "label": "一键系统监控"},
        {"cmd": "python3 buffer_stats.py", "label": "训练数据缓冲池"},
        {"cmd": "python cli.py --digest", "label": "生成今日简报"},
        {"cmd": "python cli.py --topic <话题>", "label": "查看话题线索"},
    ]

    return jsonify(result)


@app.route('/api/archive')
def api_archive():
    """获取归档统计"""
    data_base = Path(os.environ.get("DATA_BASE", "/app/data"))
    archive_dir = data_base / "search_information" / "archive"

    if not archive_dir.exists():
        return jsonify({
            "total_archives": 0,
            "total_size_mb": 0,
            "archives": [],
        })

    archives = []
    total_size = 0
    for zip_file in sorted(archive_dir.glob("*.zip")):
        size = zip_file.stat().st_size
        total_size += size
        archives.append({
            "name": zip_file.name,
            "size_mb": round(size / (1024 * 1024), 2),
        })

    return jsonify({
        "total_archives": len(archives),
        "total_size_mb": round(total_size / (1024 * 1024), 2),
        "archives": archives,
    })


@app.route('/api/trend')
def api_trend():
    """获取历史趋势数据（用于图表）"""
    days = int(request.args.get('days', 7))
    data_base = Path(os.environ.get("DATA_BASE", "/app/data"))
    news_dir = data_base / "search_information" / "news"

    if not news_dir.exists():
        return jsonify({"labels": [], "datasets": []})

    result = {"labels": [], "news_count": [], "rss_count": []}

    for i in range(days - 1, -1, -1):
        date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        result["labels"].append(date)

        # 查询新闻数量
        db_file = news_dir / f"{date}.db"
        if db_file.exists():
            count = query_db(str(db_file), "SELECT COUNT(*) as count FROM news_items")
            result["news_count"].append(count[0]["count"] if count else 0)
        else:
            result["news_count"].append(0)

        # 查询 RSS 数量
        rss_dir = data_base / "search_information" / "rss"
        rss_db = rss_dir / f"{date}.db"
        if rss_db.exists():
            count = query_db(str(rss_db), "SELECT COUNT(*) as count FROM rss_items")
            result["rss_count"].append(count[0]["count"] if count else 0)
        else:
            result["rss_count"].append(0)

    return jsonify(result)


@app.route('/search', methods=['GET'])
def search_page():
    """搜索页面"""
    import os
    html_path = os.path.join(os.path.dirname(__file__), 'templates', 'search.html')
    if os.path.exists(html_path):
        return open(html_path, encoding='utf-8').read()
    return "搜索页面未找到", 404


@app.route('/logs')
def logs_page():
    """日志中心页面"""
    import os
    html_path = os.path.join(os.path.dirname(__file__), 'templates', 'logs.html')
    if os.path.exists(html_path):
        return open(html_path, encoding='utf-8').read()
    return "日志页面未找到", 404


@app.route('/api/search')
def api_search():
    """搜索新闻"""
    query = request.args.get('q', '')
    limit = int(request.args.get('limit', 50))

    if not query:
        return jsonify({"results": [], "total": 0})

    data_base = Path(os.environ.get("DATA_BASE", "/app/data"))
    news_dir = data_base / "search_information" / "news"

    results = []
    for db_file in sorted(news_dir.glob("*.db"), reverse=True)[:7]:  # 搜索最近7天
        rows = query_db(
            str(db_file),
            "SELECT title, platform_id as source, url, created_at as date FROM news_items WHERE title LIKE ? LIMIT ?",
            (f"%{query}%", limit - len(results))
        )
        results.extend(rows)
        if len(results) >= limit:
            break

    return jsonify({"results": results[:limit], "total": len(results)})


@app.route('/api/search/combined')
def api_search_combined():
    """多源搜索：新闻 + RSS + 分析库"""
    query = request.args.get('q', '')
    limit = int(request.args.get('limit', 30))
    source = request.args.get('source', 'all')  # all, news, rss, analysis

    if not query:
        return jsonify({"results": [], "total": 0})

    data_base = Path(os.environ.get("DATA_BASE", "/app/data"))
    results = []

    if source in ('all', 'news'):
        news_dir = data_base / "search_information" / "news"
        for db_file in sorted(news_dir.glob("*.db"), reverse=True)[:7]:
            rows = query_db(
                str(db_file),
                "SELECT title, platform_id as source, url, created_at as date, '_source' as _type FROM news_items WHERE title LIKE ? LIMIT ?",
                (f"%{query}%", limit)
            )
            for r in rows: r['_type'] = 'news'
            results.extend(rows)

    if source in ('all', 'rss'):
        rss_dir = data_base / "search_information" / "rss"
        for db_file in sorted(rss_dir.glob("*.db"), reverse=True)[:7]:
            rows = query_db(
                str(db_file),
                "SELECT title, feed_name as source, link as url, published as created_at, '_source' as _type FROM rss_items WHERE title LIKE ? LIMIT ?",
                (f"%{query}%", limit)
            )
            for r in rows:
                if r.get('source'): r['_type'] = 'rss'
            results.extend(rows)

    if source in ('all', 'analysis'):
        for db_path_candidate in [
            str(data_base / "knowledge_base" / "analyzer.db"),
            str(data_base / "knowledge_base" / "analyzed.db"),
        ]:
            rows = query_db(
                db_path_candidate,
                "SELECT title, source, url, created_at FROM processed_urls WHERE title LIKE ? LIMIT ?",
                (f"%{query}%", limit)
            )
            for r in rows:
                if r.get('title'): r['_type'] = 'analysis'
            results.extend(rows)
            if len(results) >= limit:
                break

    results.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    return jsonify({"results": results[:limit], "total": len(results)})


@app.route('/api/search/predictions')
def api_search_predictions():
    """搜索预测注册表（通过invest-backend代理）"""
    query = request.args.get('q', '').strip()
    invest_url = os.environ.get('INVEST_API_URL', 'http://invest-backend:5000')
    try:
        import requests
        if query:
            resp = requests.get(f"{invest_url}/api/predictions", params={"limit": 30}, timeout=10)
            if resp.ok:
                data = resp.json()
                flags = data.get('flags', []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                # 客户端过滤
                ql = query.lower()
                matched = [f for f in flags if ql in (f.get('content','') or '').lower()]
                return jsonify({"predictions": matched, "total": len(matched)})
        else:
            resp = requests.get(f"{invest_url}/api/predictions", params={"limit": 20, "sort": "deadline", "dir": "ASC"}, timeout=10)
            if resp.ok:
                data = resp.json()
                flags = data.get('flags', []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                return jsonify({"predictions": flags, "total": len(flags)})
    except Exception as e:
        logger.warning(f"预测搜索代理失败: {e}")
    return jsonify({"predictions": [], "total": 0})


@app.route('/api/search/analyze', methods=['POST'])
def api_search_analyze():
    """AI解读搜索结果"""
    data = request.get_json(silent=True)
    query = (data or {}).get('query', '').strip()
    results = (data or {}).get('results', [])

    if not query:
        return jsonify({"analysis": "", "error": "请输入查询关键词"}), 400

    if not results:
        return jsonify({"analysis": f"关于「{query}」没有找到相关资讯，无法生成分析。"})

    # 准备上下文
    snippets = []
    for r in results[:8]:
        title = r.get('title', '')
        source = r.get('source', r.get('_type', '未知'))
        snippets.append(f"- [{source}] {title}")
    context = "\n".join(snippets)

    try:
        import urllib.request, json as _json
        api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("MIMO_API_KEY", "")
        api_base = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
        model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

        prompt = f"""你是一个金融资讯分析师。用户搜索了「{query}」，以下是相关的资讯标题列表：

{context}

请根据以上资讯，生成一份简洁的分析报告（200字以内）：
1. 这些资讯主要围绕什么主题？
2. 整体情绪偏向正面还是负面？
3. 对投资者有什么值得关注的信号？"""

        req_data = _json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 500,
        }).encode()

        req = urllib.request.Request(
            f"{api_base}/chat/completions",
            data=req_data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }
        )
        resp = urllib.request.urlopen(req, timeout=30)
        resp_data = _json.loads(resp.read().decode())
        analysis = resp_data.get("choices", [{}])[0].get("message", {}).get("content", "")

        return jsonify({"analysis": analysis, "query": query})
    except Exception as e:
        logger.warning(f"AI解读生成失败: {e}")
        return jsonify({"analysis": "", "error": f"AI解读暂时不可用: {str(e)[:50]}"})


@app.route('/api/semantic-search', methods=['POST'])
def api_semantic_search():
    """语义搜索（调用语义搜索API服务）"""
    data = request.get_json(silent=True)
    if not data or not data.get('query'):
        return jsonify({'error': '缺少query参数'}), 400

    semantic_search_url = os.environ.get('SEMANTIC_SEARCH_URL', 'http://semantic-search:5070')
    
    # 保持原始参数名
    search_params = {
        'query': data.get('query'),
        'top_k': data.get('top_k', data.get('limit', 10))
    }
    
    try:
        import requests
        response = requests.post(
            f"{semantic_search_url}/api/semantic-search",
            json=search_params,
            timeout=15
        )
        return jsonify(response.json())
    except ImportError:
        return jsonify({'error': 'requests模块未安装'}), 500
    except Exception as e:
        logger.error(f"语义搜索失败: {e}")
        return jsonify({'error': f'语义搜索服务不可用: {str(e)}'}), 503


@app.route('/api/rag-ask', methods=['POST'])
def api_rag_ask():
    """RAG问答（调用语义搜索API服务）"""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': '无效的JSON数据'}), 400
    question = data.get('question') or data.get('query')
    if not question:
        return jsonify({'error': '缺少question参数'}), 400

    semantic_search_url = os.environ.get('SEMANTIC_SEARCH_URL', 'http://semantic-search:5070')
    
    # 保持原始参数名
    ask_params = {
        'question': question,
        'top_k': data.get('top_k', 5)
    }
    
    try:
        import requests
        response = requests.post(
            f"{semantic_search_url}/api/rag-ask",
            json=ask_params,
            timeout=30
        )
        return jsonify(response.json())
    except ImportError:
        return jsonify({'error': 'requests模块未安装'}), 500
    except Exception as e:
        logger.error(f"RAG问答失败: {e}")
        return jsonify({'error': f'语义搜索服务不可用: {str(e)}'}), 503


@app.route('/api/market-sentiment')
def api_market_sentiment():
    """代理转发市场情绪API（解决前端跨域问题）"""
    invest_url = os.environ.get('INVEST_API_URL', 'http://invest-backend:5000')
    action = request.args.get('action', 'latest')
    try:
        import requests
        if action == 'history':
            days = request.args.get('days', 30)
            resp = requests.get(f"{invest_url}/api/market-sentiment", params={'action': 'history', 'days': days}, timeout=10)
        else:
            resp = requests.get(f"{invest_url}/api/market-sentiment", timeout=10)
        return jsonify(resp.json())
    except Exception as e:
        logger.warning(f"市场情绪API不可用: {e}")
        return jsonify({'error': f'市场情绪服务不可用: {str(e)}'}), 503


@app.route('/api/learning-stats')
def api_learning_stats():
    """反馈学习统计"""
    data_base = Path(os.environ.get("DATA_BASE", "/app/data"))
    knowledge_file = data_base / "invest" / "knowledge" / "lessons.json"
    stats = {"lessons": 0, "patterns": 0, "rules": 0, "recent_lessons": []}
    try:
        if knowledge_file.exists():
            import json as _json
            with open(knowledge_file) as f:
                d = _json.load(f)
            stats["lessons"] = len(d.get("lessons", []))
            stats["patterns"] = len(d.get("patterns", []))
            stats["rules"] = len(d.get("rules", []))
            stats["recent_lessons"] = d.get("lessons", [])[-3:]
            for l in stats["recent_lessons"]:
                l["content"] = l.get("content", "")[:80]
        else:
            # fallback: 从invest-backend读
            import requests
            resp = requests.get("http://invest-backend:5000/api/knowledge/stats", timeout=5)
            if resp.ok:
                stats.update(resp.json())
    except Exception as e:
        logger.warning(f"反馈学习统计不可用: {e}")
    return jsonify(stats)


@app.route('/api/prediction-summary')
def api_prediction_summary():
    """预测注册表概览（通过invest-backend代理）"""
    invest_url = os.environ.get('INVEST_API_URL', 'http://invest-backend:5000')
    try:
        import requests
        resp = requests.get(f"{invest_url}/api/predictions/stats", timeout=10)
        if resp.ok:
            return jsonify(resp.json())
    except Exception as e:
        logger.warning(f"预测统计代理失败: {e}")
    # fallback: 尝试直接读DB
    summary = {"total": 0, "pending": 0, "confirmed": 0, "rejected": 0, "accuracy": 0}
    for p in [Path(os.environ.get("DATA_BASE", "/app/data")) / "invest" / "prediction_registry" / "predictions.db",
              Path("/root/projects/data/invest/prediction_registry/predictions.db")]:
        if p.exists():
            try:
                import sqlite3
                conn = sqlite3.connect(str(p))
                summary["total"] = conn.execute("SELECT COUNT(*) FROM flags").fetchone()[0]
                rows = conn.execute("SELECT status, COUNT(*) as c FROM flags GROUP BY status").fetchall()
                for s, c in rows:
                    if s in summary: summary[s] = c
                conf = conn.execute("SELECT COUNT(*) FROM flags WHERE status='confirmed'").fetchone()[0]
                rej = conn.execute("SELECT COUNT(*) FROM flags WHERE status='rejected'").fetchone()[0]
                tv = conf + rej
                summary["accuracy"] = round(conf / tv * 100, 1) if tv else 0
                conn.close()
                break
            except: pass
    return jsonify(summary)


@app.route('/api/recent-analyses')
def api_recent_analyses():
    """最近AI分析结果（从知识库读取）"""
    data_base = Path(os.environ.get("DATA_BASE", "/app/data"))
    results = []
    for db_name in ["analyzer.db", "analyzed.db"]:
        db_path = data_base / "knowledge_base" / db_name
        if db_path.exists():
            try:
                rows = query_db(
                    str(db_path),
                    "SELECT title, summary, source, created_at, sentiment_score, url, analysis FROM processed_urls WHERE analysis IS NOT NULL AND analysis != '' ORDER BY created_at DESC LIMIT 15"
                )
                for r in rows:
                    r['_type'] = 'analysis'
                    if r.get('analysis') and len(r['analysis']) > 200:
                        r['analysis'] = r['analysis'][:200] + '...'
                results.extend(rows)
            except Exception as e:
                logger.warning(f"查询{db_name}失败: {e}")
    return jsonify({"analyses": results[:15], "total": len(results)})


@app.route('/api/portfolio')
def api_portfolio():
    """日志API"""
    invest_url = os.environ.get('INVEST_API_URL', 'http://invest-backend:5000')
    try:
        import requests
        resp = requests.get(f"{invest_url}/api/portfolio", timeout=10)
        return jsonify(resp.json())
    except Exception as e:
        logger.warning(f"持仓API不可用: {e}")
        return jsonify({'error': f'持仓服务不可用: {str(e)}'}), 503


@app.route('/api/invest-stats')
def api_invest_stats():
    """代理转发投资统计API"""
    invest_url = os.environ.get('INVEST_API_URL', 'http://invest-backend:5000')
    try:
        import requests
        resp = requests.get(f"{invest_url}/api/stats", timeout=10)
        return jsonify(resp.json())
    except Exception as e:
        logger.warning(f"投资统计API不可用: {e}")
        return jsonify({'error': f'投资统计服务不可用: {str(e)}'}), 503


@app.route('/api/backtest-report')
def api_backtest_report():
    """获取回测报告"""
    data_base = Path(os.environ.get("DATA_BASE", "/app/data"))
    report_dir = data_base / "invest" / "backtest"
    if not report_dir.exists():
        report_dir = data_base / "invest" / "reports"
    if not report_dir.exists():
        return jsonify({"error": "回测报告目录不存在", "reports": []})

    reports = []
    for f in sorted(report_dir.glob("*"), key=lambda x: x.stat().st_mtime, reverse=True)[:10]:
        reports.append({
            "name": f.name,
            "size_kb": round(f.stat().st_size / 1024, 1),
            "modified": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
        })

    if not reports:
        return jsonify({"reports": [], "message": "暂无回测报告"})

    latest = report_dir / reports[0]["name"]
    content = ""
    try:
        content = latest.read_text(encoding="utf-8")[:10000]
    except Exception:
        content = "无法读取报告内容"

    return jsonify({"reports": reports, "latest_content": content})


@app.route('/api/funds', methods=['GET'])
def api_get_funds():
    """获取基金列表"""
    invest_url = os.environ.get('INVEST_API_URL', 'http://invest-backend:5000')
    try:
        import requests
        resp = requests.get(f"{invest_url}/api/portfolio", timeout=10)
        data = resp.json()
        holdings = data.get("holdings", data.get("funds", []))
        return jsonify({"funds": holdings})
    except Exception:
        config_path = Path(os.environ.get("INVEST_CONFIG", "/app/invest/config/user_config.yaml"))
        if not config_path.exists():
            config_path = Path(os.environ.get("INVEST_CONFIG", "/app/invest/config/default_config.yaml"))
        if config_path.exists():
            import yaml
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                return jsonify({"funds": config.get("funds", [])})
            except Exception:
                pass
        return jsonify({"funds": []})


@app.route('/api/funds', methods=['POST'])
def api_add_fund():
    """添加基金"""
    data = request.get_json(silent=True)
    if not data or not data.get('code'):
        return jsonify({'error': '缺少基金代码'}), 400

    config_path = Path(os.environ.get("INVEST_CONFIG", "/app/invest/config/user_config.yaml"))
    if not config_path.exists():
        config_path = Path(os.environ.get("INVEST_CONFIG", "/app/invest/config/default_config.yaml"))

    import yaml
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}

        funds = config.get("funds", [])
        for f in funds:
            if f.get("code") == data["code"]:
                return jsonify({'error': '基金已存在'}), 400

        funds.append({
            "code": data["code"],
            "name": data.get("name", ""),
            "monthly_invest": data.get("monthly_invest", 200),
            "enabled": True,
        })
        config["funds"] = funds

        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

        return jsonify({"success": True, "message": f"基金 {data['code']} 已添加"})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/funds/<code>', methods=['DELETE'])
def api_delete_fund(code):
    """删除基金"""
    config_path = Path(os.environ.get("INVEST_CONFIG", "/app/invest/config/user_config.yaml"))
    if not config_path.exists():
        config_path = Path(os.environ.get("INVEST_CONFIG", "/app/invest/config/default_config.yaml"))

    import yaml
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}

        funds = config.get("funds", [])
        config["funds"] = [f for f in funds if f.get("code") != code]

        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

        return jsonify({"success": True, "message": f"基金 {code} 已删除"})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/logs')
def api_logs():
    """获取各容器最近日志（Docker SDK）"""
    import json as _json
    lines = int(request.args.get('lines', 15))
    containers = request.args.get('containers', '').split(',')

    all_names = ['trendradar', 'dashboard', 'invest-backend', 'notification-center',
                 'semantic-search', 'analyser', 'feedback-learner']
    targets = [c for c in all_names if not containers[0] or any(t in c for t in containers)]

    result = {}
    try:
        import docker
        client = docker.from_env()
        for container in client.containers.list(all=True):
            name = container.name
            if name in targets:
                try:
                    logs = container.logs(tail=lines, timestamps=True).decode('utf-8', errors='replace')
                    lines_out = [l for l in logs.split('\n') if l.strip()]
                    result[name] = lines_out[-lines:] if lines_out else ['(no logs)']
                except Exception as e:
                    result[name] = [f'(error: {e})']
    except Exception as e:
        return _json.dumps({"error": str(e), "logs": {}}, ensure_ascii=False)
    return _json.dumps({"logs": result, "containers": targets}, ensure_ascii=False)


@app.route('/api/logs/search')
def api_logs_search():
    """搜索所有容器日志（Docker SDK）"""
    import json as _json
    q = request.args.get('q', '').strip()
    lines = int(request.args.get('lines', 50))
    if not q:
        return _json.dumps({"error": "缺少查询关键词"}), 400

    result = {}
    try:
        import docker
        client = docker.from_env()
        for container in client.containers.list(all=True):
            if container.name in ['trendradar','dashboard','invest-backend','notification-center',
                                  'semantic-search','analyser','feedback-learner']:
                try:
                    logs = container.logs(tail=lines).decode('utf-8', errors='replace')
                    matched = [l for l in logs.split('\n') if q.lower() in l.lower()]
                    if matched:
                        result[container.name] = matched[:15]
                except:
                    pass
    except Exception as e:
        return _json.dumps({"error": str(e), "logs": {}}, ensure_ascii=False)
    return _json.dumps({"logs": result, "query": q}, ensure_ascii=False)


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>百器模型 · 投资情报系统</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f0f1a; color: #e0e0e0; }
        .header { background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 24px 20px; border-bottom: 1px solid #2a2a4a; }
        .header h1 { font-size: 20px; color: #fff; }
        .header .sub { font-size: 13px; color: #8888aa; margin-top: 4px; }
        .header .time { font-size: 12px; color: #666; float: right; margin-top: -20px; }
        .container { max-width: 1200px; margin: 0 auto; padding: 16px; }

        /* 状态栏 */
        .status-bar { display: flex; gap: 10px; margin-bottom: 16px; flex-wrap: wrap; }
        .status-item { background: #1a1a2e; border-radius: 8px; padding: 12px 16px; flex: 1; min-width: 120px; border: 1px solid #2a2a4a; }
        .status-item .val { font-size: 22px; font-weight: 700; }
        .status-item .lbl { font-size: 11px; color: #8888aa; margin-top: 2px; }
        .green { color: #4ade80; } .yellow { color: #fbbf24; } .red { color: #f87171; } .blue { color: #60a5fa; }

        /* 卡片网格 */
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; margin-bottom: 16px; }
        .card { background: #1a1a2e; border-radius: 10px; padding: 16px; border: 1px solid #2a2a4a; transition: 0.2s; }
        .card:hover { border-color: #4a4a7a; }
        .card h3 { font-size: 13px; color: #8888aa; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px; }
        .card .big { font-size: 28px; font-weight: 700; }
        .card .row { display: flex; justify-content: space-between; padding: 6px 0; font-size: 13px; border-bottom: 1px solid #222244; }
        .card .row:last-child { border: none; }
        .card .tag { font-size: 11px; padding: 2px 8px; border-radius: 4px; }
        .tag-hot { background: #3b1a1a; color: #f87171; }
        .tag-cold { background: #1a1a3b; color: #60a5fa; }
        .tag-warn { background: #3b3a1a; color: #fbbf24; }

        /* 命令列表 */
        .cmd-list { background: #1a1a2e; border-radius: 10px; padding: 16px; border: 1px solid #2a2a4a; margin-bottom: 16px; }
        .cmd-list h3 { font-size: 13px; color: #8888aa; margin-bottom: 10px; text-transform: uppercase; }
        .cmd-item { padding: 8px 0; border-bottom: 1px solid #222244; font-size: 13px; display: flex; justify-content: space-between; align-items: center; }
        .cmd-item:last-child { border: none; }
        .cmd-item code { background: #222244; padding: 2px 8px; border-radius: 4px; font-size: 12px; color: #4ade80; }
        .cmd-item .desc { color: #ccc; }

        /* 话题线索 */
        .topic { display: inline-block; padding: 4px 12px; margin: 3px; border-radius: 6px; font-size: 12px; cursor: pointer; }
        .topic-red { background: #3b1a1a; color: #f87171; border: 1px solid #5a2a2a; }
        .topic-yellow { background: #3b3a1a; color: #fbbf24; border: 1px solid #5a5a2a; }
        .topic-green { background: #1a3b1a; color: #4ade80; border: 1px solid #2a5a2a; }
        .topic-blue { background: #1a1a3b; color: #60a5fa; border: 1px solid #2a2a5a; }
        .topic-muted { background: #222244; color: #8888aa; border: 1px solid #333355; }

        /* 图表容器 */
        .chart-box { background: #1a1a2e; border-radius: 10px; padding: 16px; border: 1px solid #2a2a4a; margin-bottom: 16px; min-height: 200px; }

        .footer { text-align: center; padding: 20px; font-size: 11px; color: #555; }

        @media (max-width: 600px) {
            .status-item { min-width: calc(50% - 5px); }
            .grid { grid-template-columns: 1fr; }
            .header .time { float: none; display: block; margin-top: 4px; }
        }
    </style>
</head>
<body>
<div class="header">
    <h1>📡 投资情报系统</h1>
    <div class="sub">采集 · 分析 · 决策 · 学习</div>
    <div class="time" id="headerTime"></div>
</div>
<div class="container">

    <!-- 状态栏 -->
    <div class="status-bar" id="statusBar">
        <div class="status-item"><div class="val green" id="sSentiment">--</div><div class="lbl">情绪指数</div></div>
        <div class="status-item"><div class="val blue" id="sNews">--</div><div class="lbl">今日新闻</div></div>
        <div class="status-item"><div class="val yellow" id="sFunds">--</div><div class="lbl">基金跟踪</div></div>
        <div class="status-item"><div class="val" id="sHealth" style="color:#4ade80">✓</div><div class="lbl">系统状态</div></div>
    </div>

    <!-- 核心数据 -->
    <div class="grid" id="gridData">
        <div class="card"><h3>📈 情绪指数</h3><div id="cardSentiment" class="big">加载中...</div></div>
        <div class="card"><h3>🗄️ 数据库</h3><div id="cardDB">加载中...</div></div>
        <div class="card"><h3>📰 最新数据</h3><div id="cardNews">加载中...</div></div>
    </div>

    <!-- 话题线索 -->
    <div class="card" style="margin-bottom:16px">
        <h3>🔗 话题线索</h3>
        <div id="topicCloud">
            <span class="topic topic-red">半导体 🔴</span>
            <span class="topic topic-yellow">美联储 🟡</span>
            <span class="topic topic-green">新能源 ✅</span>
            <span class="topic topic-blue">AI ⚪</span>
            <span class="topic topic-yellow">房地产 🟡</span>
            <span class="topic topic-muted">消费</span>
            <span class="topic topic-red">地缘政治 🔴</span>
            <span class="topic topic-blue">医药</span>
            <span class="topic topic-green">光伏</span>
            <span class="topic topic-muted">更多+</span>
        </div>
        <div style="font-size:12px;color:#666;margin-top:8px">点击话题查看关联信息链 · 颜色 = 当前关注度</div>
    </div>

    <!-- 近期趋势 -->
    <div class="chart-box">
        <h3 style="font-size:13px;color:#8888aa;margin-bottom:10px;">📊 情绪趋势（近7天）</h3>
        <div id="trendChart" style="height:120px;display:flex;align-items:flex-end;gap:8px;padding:0 4px;"></div>
    </div>

    <!-- 统一命令入口 -->
    <div class="cmd-list">
        <h3>🎯 快捷操作</h3>
        <div class="cmd-item"><span class="desc">📊 一键监控</span><code>python3 server_status.py</code></div>
        <div class="cmd-item"><span class="desc">📦 缓冲池状态</span><code>python3 buffer_stats.py</code></div>
        <div class="cmd-item"><span class="desc">📝 生成今日简报</span><code>python cli.py --digest</code></div>
        <div class="cmd-item"><span class="desc">🔗 查看话题线索</span><code>python cli.py --topic 半导体</code></div>
    </div>

    <div class="footer">投资有风险，过往业绩不代表未来表现 · 数据仅供参考</div>
</div>

<script>
async function loadPortal() {
    try {
        let r = await fetch('/api/portal');
        let d = await r.json();
        document.getElementById('headerTime').textContent = d.time || '';

        // 状态栏
        let sentiment = d.sentiment || {};
        document.getElementById('sSentiment').textContent = sentiment.index != null ? sentiment.index : '--';
        document.getElementById('sSentiment').className = 'val ' + (
            sentiment.index > 60 ? 'green' : sentiment.index > 40 ? 'yellow' : 'red'
        );

        let db = d.db_stats || {};
        document.getElementById('sNews').textContent = db['情绪数据'] || '--';
        document.getElementById('sFunds').textContent = db['基金数量'] || '--';

        // 情绪卡片
        let cardS = document.getElementById('cardSentiment');
        if (sentiment.index != null) {
            let level = sentiment.level || '';
            let trend = sentiment.trend || '';
            cardS.innerHTML = `${sentiment.index} <span style="font-size:14px;color:#888">${level}</span>
                <div style="font-size:12px;color:#666;margin-top:4px">趋势: ${trend} · ${sentiment.date || ''}</div>`;
        }

        // 数据库卡片
        let cardDB = document.getElementById('cardDB');
        let dbHTML = '';
        for (let k in db) { dbHTML += `<div class="row"><span>${k}</span><span>${db[k]}</span></div>`; }
        cardDB.innerHTML = dbHTML || '暂无数据';

        // 反馈学习统计
        try {
            const lr = await (await fetch('/api/learning-stats')).json();
            const lc = document.getElementById('learningContent');
            if (lr.lessons != null) {
                lc.innerHTML = `
                    <div style="display:flex;gap:20px;margin-bottom:10px">
                        <div><b>📝 ${lr.lessons}</b> 条经验</div>
                        <div><b>🔄 ${lr.patterns}</b> 个模式</div>
                        <div><b>⚙️ ${lr.rules}</b> 条规则</div>
                    </div>
                    ${(lr.recent_lessons||[]).slice(-2).map(l =>
                        `<div style="font-size:13px;color:#666;border-left:3px solid #4A6CF7;padding:4px 10px;margin:4px 0">${l.content||''}</div>`
                    ).join('')}
                `;
            }
        } catch(e) { console.log('学习统计加载失败:', e); }

        // 预测统计
        try {
            const pr = await (await fetch('/api/prediction-summary')).json();
            const pc = document.getElementById('predictionContent');
            if (pr.total != null) {
                const barW = pr.total > 0 ? (pr.total - pr.pending) / pr.total * 100 : 0;
                pc.innerHTML = `
                    <div style="display:flex;gap:20px;margin-bottom:10px">
                        <div><b>🏁 ${pr.total}</b> 面旗</div>
                        <div><b>⏳ ${pr.pending}</b> 待验证</div>
                        <div><b>✅ ${pr.confirmed}</b> 确认 ✓</div>
                        <div><b>❌ ${pr.rejected}</b> 拒绝 ✗</div>
                        <div><b>🎯 ${pr.accuracy}%</b> 准确率</div>
                    </div>
                    <div style="height:8px;background:#e8e8e8;border-radius:4px;overflow:hidden;margin-top:6px">
                        <div style="height:100%;width:${barW}%;background:linear-gradient(90deg,#4A6CF7,#00c853);border-radius:4px"></div>
                    </div>
                `;
            }
        } catch(e) { console.log('预测统计加载失败:', e); }

        // 新闻数据卡片
        let nd = d.news_db || {};
        let cardNews = document.getElementById('cardNews');
        cardNews.innerHTML = nd.date ? `<div class="row"><span>最新数据库</span><span>${nd.date}</span></div>
            <div class="row"><span>大小</span><span>${nd.size_kb} KB</span></div>` : '暂无数据';

        // 趋势图
        let trend = d.sentiment_trend || [];
        let chartEl = document.getElementById('trendChart');
        if (trend.length > 0) {
            let maxV = Math.max(...trend.map(t => t.index || 0), 60);
            let minV = Math.min(...trend.map(t => t.index || 0), 40);
            let range = Math.max(maxV - minV, 10);
            chartEl.innerHTML = trend.map(t => {
                let h = ((t.index || 50) - minV) / range * 100;
                let color = t.index > 60 ? '#4ade80' : t.index > 40 ? '#fbbf24' : '#f87171';
                return `<div style="flex:1;display:flex;flex-direction:column;align-items:center;">
                    <div style="height:${h}%;background:${color};width:60%;border-radius:4px 4px 0 0;min-height:4px;transition:0.3s;"></div>
                    <span style="font-size:10px;color:#666;margin-top:4px">${(t.date || '').slice(-5)}</span>
                    <span style="font-size:10px;color:#aaa">${t.index || ''}</span>
                </div>`;
            }).join('');
        } else {
            chartEl.innerHTML = '<div style="color:#666;padding:20px;text-align:center">暂无趋势数据</div>';
        }

    } catch(e) {
        document.getElementById('statusBar').innerHTML =
            `<div class="status-item"><div class="val red">!</div><div class="lbl">加载失败: ${e.message}</div></div>`;
    }
}

// 话题点击
document.getElementById('topicCloud').addEventListener('click', function(e) {
    if (e.target.classList.contains('topic')) {
        let topic = e.target.textContent.trim().replace(/[🔴🟡✅⚪]$/, '').trim();
        alert('话题「' + topic + '」的详细信息将在 cli.py --topic 中查看\n\n命令: python cli.py --topic ' + topic);
    }
});

loadPortal();
setInterval(loadPortal, 30000);
</script>
</body>
</html>
        .badge-source { background: #eef; color: #006; }
        .empty { text-align: center; padding: 40px; color: #999; }
        .refresh-btn { background: #1a1a2e; color: white; border: none; padding: 10px 20px; border-radius: 6px; cursor: pointer; }
        .refresh-btn:hover { background: #16213e; }
        .item-title a { color: #1a1a2e; text-decoration: none; }
        .item-title a:hover { color: #e94560; text-decoration: underline; }
        .portfolio-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 15px; }
        .portfolio-card { background: #f8f9fa; border-radius: 8px; padding: 15px; border-left: 4px solid #1a1a2e; }
        .portfolio-card.profit { border-left-color: #00cc44; }
        .portfolio-card.loss { border-left-color: #ff4444; }
        .portfolio-card .fund-name { font-weight: 600; font-size: 15px; }
        .portfolio-card .fund-detail { font-size: 13px; color: #666; margin-top: 8px; line-height: 1.6; }
        .portfolio-card .pnl { font-size: 20px; font-weight: bold; margin-top: 5px; }
        .pnl.positive { color: #00cc44; }
        .pnl.negative { color: #ff4444; }
        .backtest-content { background: #f8f9fa; border-radius: 6px; padding: 15px; font-family: monospace; font-size: 13px; white-space: pre-wrap; max-height: 400px; overflow-y: auto; line-height: 1.5; }
    </style>
</head>
<body>
    <div class="header">
        <h1>Dashboard - 信息分析系统</h1>
        <p id="date">加载中...</p>
    </div>

    <div class="container">
        <div style="text-align: right; margin-bottom: 15px;">
            <button class="refresh-btn" onclick="loadData()">刷新数据</button>
        </div>

        <div class="stats">
            <div class="stat-card">
                <h3>热榜信号</h3>
                <div class="number" id="trend-count">-</div>
                <div class="label">今日匹配</div>
            </div>
            <div class="stat-card">
                <h3>RSS 文章</h3>
                <div class="number" id="rss-count">-</div>
                <div class="label">今日抓取</div>
            </div>
            <div class="stat-card">
                <h3>分析文章</h3>
                <div class="number" id="analyse-count">-</div>
                <div class="label">今日分析</div>
            </div>
            <div class="stat-card">
                <h3>求职岗位</h3>
                <div class="number" id="job-count">-</div>
                <div class="label">今日抓取</div>
            </div>
        </div>

        <div class="section">
            <h2>数据趋势（最近7天）</h2>
            <canvas id="trendChart" height="200"></canvas>
        </div>

        <div class="section" id="sectionLearning">
            <h2>📝 反馈学习</h2>
            <div id="learningContent" style="font-size:14px;line-height:1.8;color:#555">
                <div class="empty">加载中...</div>
            </div>
        </div>

        <div class="section" id="sectionPredictions">
            <h2>🔮 预测注册表</h2>
            <div id="predictionContent" style="font-size:14px;line-height:1.8;color:#555">
                <div class="empty">加载中...</div>
            </div>
        </div>

        <div class="section">
            <h2>搜索新闻</h2>
            <div style="display: flex; gap: 10px; margin-bottom: 15px;">
                <input type="text" id="searchInput" placeholder="输入关键词搜索..." style="flex: 1; padding: 10px; border: 1px solid #ddd; border-radius: 6px;">
                <button class="refresh-btn" onclick="searchNews()">搜索</button>
            </div>
            <div id="search-results"><div class="empty">输入关键词后点击搜索</div></div>
        </div>

        <div class="section">
            <h2>语义搜索</h2>
            <p style="color: #666; font-size: 14px; margin-bottom: 15px;">使用AI理解语义，找到相关内容</p>
            <div style="display: flex; gap: 10px; margin-bottom: 15px;">
                <input type="text" id="semanticInput" placeholder="输入自然语言查询，如：最近半导体行业有什么新闻？" style="flex: 1; padding: 10px; border: 1px solid #ddd; border-radius: 6px;">
                <button class="refresh-btn" onclick="semanticSearch()">语义搜索</button>
            </div>
            <div id="semantic-results"><div class="empty">输入自然语言查询后点击语义搜索</div></div>
        </div>

        <div class="section">
            <h2>智能问答</h2>
            <p style="color: #666; font-size: 14px; margin-bottom: 15px;">基于知识库的AI问答，支持复杂问题</p>
            <div style="display: flex; gap: 10px; margin-bottom: 15px;">
                <input type="text" id="askInput" placeholder="输入问题，如：上周有哪些关于嵌入式的重要新闻？" style="flex: 1; padding: 10px; border: 1px solid #ddd; border-radius: 6px;">
                <button class="refresh-btn" onclick="ragAsk()">提问</button>
            </div>
            <div id="ask-results"><div class="empty">输入问题后点击提问</div></div>
        </div>

        <div class="section">
            <h2>今日热榜信号</h2>
            <div id="trend-signals"><div class="empty">加载中...</div></div>
        </div>

        <div class="section">
            <h2>高分分析文章</h2>
            <div id="analyse-high"><div class="empty">加载中...</div></div>
        </div>

        <div class="section">
            <h2>高分求职岗位</h2>
            <div id="job-high"><div class="empty">加载中...</div></div>
        </div>

        <div class="section">
            <h2>持仓日报</h2>
            <div id="portfolio-summary" style="margin-bottom: 15px; font-size: 14px; color: #666;">加载中...</div>
            <div id="portfolio-cards" class="portfolio-grid"><div class="empty">加载中...</div></div>
        </div>

        <div class="section">
            <h2>投资预警</h2>
            <div id="invest-alerts"><div class="empty">加载中...</div></div>
        </div>

        <div class="section">
            <h2>市场情绪指数（Fear & Greed Index）</h2>
            <div style="display: flex; gap: 20px; align-items: center; margin-bottom: 15px;">
                <div style="text-align: center; min-width: 120px;">
                    <div id="sentiment-gauge" style="font-size: 48px; font-weight: bold; color: #ffcc00;">--</div>
                    <div id="sentiment-level" style="font-size: 16px; font-weight: 500; margin-top: 5px;">加载中</div>
                    <div id="sentiment-trend" style="font-size: 12px; color: #999; margin-top: 3px;"></div>
                </div>
                <div style="flex: 1;">
                    <canvas id="sentimentRadar" height="200"></canvas>
                </div>
            </div>
            <div id="sentiment-details" style="font-size: 13px; color: #666;"></div>
            <div style="margin-top: 10px;">
                <canvas id="sentimentTrend" height="150"></canvas>
            </div>
        </div>

        <div class="section">
            <h2>数据归档</h2>
            <div id="archive-info"><div class="empty">加载中...</div></div>
        </div>

        <div class="section">
            <h2>回测报告</h2>
            <div id="backtest-info"><div class="empty">加载中...</div></div>
        </div>

        <div class="section">
            <h2>基金管理</h2>
            <div style="display: flex; gap: 10px; margin-bottom: 15px; flex-wrap: wrap;">
                <input type="text" id="fundCode" placeholder="基金代码 如 110011" style="width: 120px; padding: 8px; border: 1px solid #ddd; border-radius: 6px;">
                <input type="text" id="fundName" placeholder="基金名称（可选）" style="width: 180px; padding: 8px; border: 1px solid #ddd; border-radius: 6px;">
                <input type="number" id="fundAmount" placeholder="每月定投" value="200" style="width: 100px; padding: 8px; border: 1px solid #ddd; border-radius: 6px;">
                <button class="refresh-btn" onclick="addFund()">添加基金</button>
            </div>
            <div id="fund-list"><div class="empty">加载中...</div></div>
        </div>
    </div>

    <script>
        async function loadData() {
            try {
                const resp = await fetch('/api/today');
                const data = await resp.json();

                document.getElementById('date').textContent = data.date;
                document.getElementById('trend-count').textContent = data.trendradar.count;
                document.getElementById('rss-count').textContent = data.rss.count;
                document.getElementById('analyse-count').textContent = data.analyse.count;
                document.getElementById('job-count').textContent = data.jobs.count;

                renderList('trend-signals', data.trendradar.signals, item =>
                    `<div class="item"><div class="item-title">${item.url ? `<a href="${item.url}" target="_blank" rel="noopener">${item.title}</a>` : item.title}</div><div class="item-meta"><span class="badge badge-source">${item.source}</span> ${item.date}</div></div>`
                );

                renderList('analyse-high', data.analyse.high_score, item =>
                    `<div class="item"><div class="item-title">${item.title}</div><div class="item-meta"><span class="badge badge-score">评分 ${item.score}</span> ${item.category}</div></div>`
                );

                renderList('job-high', data.jobs.high_score, item =>
                    `<div class="item"><div class="item-title">${item.url ? `<a href="${item.url}" target="_blank" rel="noopener">${item.title}</a>` : item.title} - ${item.company}</div><div class="item-meta"><span class="badge badge-score">匹配度 ${item.score}%</span></div></div>`
                );

                renderList('invest-alerts', data.invest.alerts, item =>
                    `<div class="item"><div class="item-title">${item.fund_name}</div><div class="item-meta"><span class="badge badge-hot">${item.alert_type}</span> ${item.message}</div></div>`
                );

                loadArchive();
                loadTrend();
            } catch (e) {
                console.error('加载失败:', e);
            }
        }

        function renderList(id, items, template) {
            const el = document.getElementById(id);
            if (!items || items.length === 0) {
                el.innerHTML = '<div class="empty">暂无数据</div>';
                return;
            }
            el.innerHTML = items.map(template).join('');
        }

        async function loadTrend() {
            try {
                if (typeof Chart === 'undefined') {
                    console.log('Chart.js 尚未加载，跳过图表渲染');
                    return;
                }
                const resp = await fetch('/api/trend?days=7');
                const data = await resp.json();

                const ctx = document.getElementById('trendChart').getContext('2d');
                if (window.trendChart) {
                    window.trendChart.destroy();
                }
                window.trendChart = new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: data.labels,
                        datasets: [
                            {
                                label: '热榜新闻',
                                data: data.news_count,
                                borderColor: '#1a1a2e',
                                backgroundColor: 'rgba(26, 26, 46, 0.1)',
                                tension: 0.4,
                                fill: true
                            },
                            {
                                label: 'RSS 文章',
                                data: data.rss_count,
                                borderColor: '#e94560',
                                backgroundColor: 'rgba(233, 69, 96, 0.1)',
                                tension: 0.4,
                                fill: true
                            }
                        ]
                    },
                    options: {
                        responsive: true,
                        plugins: {
                            legend: {
                                position: 'top',
                            }
                        },
                        scales: {
                            y: {
                                beginAtZero: true,
                                ticks: {
                                    stepSize: 1
                                }
                            }
                        }
                    }
                });
            } catch (e) {
                console.error('加载趋势数据失败:', e);
            }
        }

        async function searchNews() {
            const query = document.getElementById('searchInput').value.trim();
            if (!query) {
                document.getElementById('search-results').innerHTML = '<div class="empty">请输入搜索关键词</div>';
                return;
            }

            try {
                const resp = await fetch(`/api/search?q=${encodeURIComponent(query)}&limit=20`);
                const raw = await resp.json();
                const results = (Array.isArray(raw) ? raw
                              : Array.isArray(raw.results) ? raw.results
                              : Array.isArray(raw.data) ? raw.data
                              : []);
                const el = document.getElementById('search-results');

                if (results.length === 0) {
                    el.innerHTML = `<div class="empty">未找到包含"${query}"的新闻</div>`;
                    return;
                }

                el.innerHTML = `<div class="item"><div class="item-title">找到 ${results.length} 条结果</div></div>` +
                    results.map(item =>
                        `<div class="item"><div class="item-title">${item.url ? `<a href="${item.url}" target="_blank" rel="noopener">${item.title}</a>` : item.title}</div><div class="item-meta"><span class="badge badge-source">${item.source}</span> ${item.date}</div></div>`
                    ).join('');
            } catch (e) {
                console.error('搜索失败:', e);
            }
        }

        async function semanticSearch() {
            const query = document.getElementById('semanticInput').value.trim();
            if (!query) {
                document.getElementById('semantic-results').innerHTML = '<div class="empty">请输入自然语言查询</div>';
                return;
            }

            const el = document.getElementById('semantic-results');
            el.innerHTML = '<div class="empty">正在语义搜索...</div>';

            try {
                const resp = await fetch('/api/semantic-search', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({query: query, top_k: 10})
                });
                const data = await resp.json();

                if (data.error) {
                    el.innerHTML = `<div class="empty" style="color:#c00;">${data.error}</div>`;
                    return;
                }

                const results = data.results || [];
                if (results.length === 0) {
                    el.innerHTML = '<div class="empty">未找到相关内容</div>';
                    return;
                }

                el.innerHTML = `<div class="item"><div class="item-title">找到 ${results.length} 条相关结果</div></div>` +
                    results.map(item =>
                        `<div class="item">
                            <div class="item-title">${item.title || '无标题'}</div>
                            <div style="font-size:13px; color:#555; margin:4px 0;">${(item.summary || item.content || '').substring(0, 150)}...</div>
                            <div class="item-meta">
                                <span class="badge badge-score">相关度 ${((item.score || 0) * 100).toFixed(0)}%</span>
                                ${item.category ? `<span class="badge badge-source">${item.category}</span>` : ''}
                                ${item.date || ''}
                            </div>
                        </div>`
                    ).join('');
            } catch (e) {
                console.error('语义搜索失败:', e);
                el.innerHTML = `<div class="empty" style="color:#c00;">语义搜索服务不可用</div>`;
            }
        }

        async function ragAsk() {
            const question = document.getElementById('askInput').value.trim();
            if (!question) {
                document.getElementById('ask-results').innerHTML = '<div class="empty">请输入问题</div>';
                return;
            }

            const el = document.getElementById('ask-results');
            el.innerHTML = '<div class="empty">正在思考中...</div>';

            try {
                const resp = await fetch('/api/rag-ask', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({question: question, top_k: 5})
                });
                const data = await resp.json();

                if (data.error) {
                    el.innerHTML = `<div class="empty" style="color:#c00;">${data.error}</div>`;
                    return;
                }

                let html = `<div class="item">
                    <div class="item-title" style="font-size:15px; line-height:1.8;">${(data.answer || '').replace(/\\n/g, '<br>')}</div>
                    <div class="item-meta" style="margin-top:10px;">
                        <span class="badge badge-score">置信度 ${((data.confidence || 0) * 100).toFixed(0)}%</span>
                    </div>
                </div>`;

                if (data.sources && data.sources.length > 0) {
                    html += `<div style="margin-top:10px; padding-top:10px; border-top:1px solid #eee;">
                        <div style="font-size:12px; color:#999; margin-bottom:8px;">参考来源：</div>
                        ${data.sources.map((s, i) =>
                            `<div class="item" style="padding:5px 0;">
                                <span style="color:#1a1a2e; font-weight:500;">[${i+1}]</span>
                                ${s.title || ''}
                                ${s.category ? `<span class="badge badge-source" style="margin-left:5px;">${s.category}</span>` : ''}
                                ${s.date ? `<span style="color:#999; font-size:11px; margin-left:5px;">${s.date}</span>` : ''}
                            </div>`
                        ).join('')}
                    </div>`;
                }

                el.innerHTML = html;
            } catch (e) {
                console.error('RAG问答失败:', e);
                el.innerHTML = `<div class="empty" style="color:#c00;">问答服务不可用</div>`;
            }
        }

        document.getElementById('semanticInput').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') semanticSearch();
        });
        document.getElementById('askInput').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') ragAsk();
        });

        // 回车搜索
        document.getElementById('searchInput').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                searchNews();
            }
        });

        async function loadArchive() {
            try {
                const resp = await fetch('/api/archive');
                const data = await resp.json();
                const el = document.getElementById('archive-info');
                if (data.total_archives === 0) {
                    el.innerHTML = '<div class="empty">暂无归档数据（数据保留30天后自动归档）</div>';
                    return;
                }
                let html = `<div class="item"><div class="item-title">共 ${data.total_archives} 个归档文件，总大小 ${data.total_size_mb} MB</div></div>`;
                data.archives.forEach(a => {
                    html += `<div class="item"><div class="item-title">${a.name}</div><div class="item-meta">${a.size_mb} MB</div></div>`;
                });
                el.innerHTML = html;
            } catch (e) {
                console.error('加载归档信息失败:', e);
            }
        }

        async function loadPortfolio() {
            try {
                const resp = await fetchWithTimeout('/api/portfolio', {}, 8000);
                if (!resp.ok) return;
                const data = await resp.json();
                if (data.error) {
                    document.getElementById('portfolio-summary').textContent = '持仓服务暂不可用';
                    document.getElementById('portfolio-cards').innerHTML = '<div class="empty">' + data.error + '</div>';
                    return;
                }

                const holdings = data.holdings || data.funds || [];
                const summary = data.summary || {};
                const summaryEl = document.getElementById('portfolio-summary');
                const cardsEl = document.getElementById('portfolio-cards');

                if (summary.total_assets !== undefined) {
                    const pnlClass = (summary.total_pnl || 0) >= 0 ? 'positive' : 'negative';
                    const pnlSign = (summary.total_pnl || 0) >= 0 ? '+' : '';
                    summaryEl.innerHTML = `总资产: <b>¥${(summary.total_assets || 0).toLocaleString()}</b> | 总盈亏: <span class="pnl ${pnlClass}">${pnlSign}¥${(summary.total_pnl || 0).toLocaleString()}</span> (${pnlSign}${(summary.total_pnl_pct || 0).toFixed(2)}%)`;
                }

                if (!holdings || holdings.length === 0) {
                    cardsEl.innerHTML = '<div class="empty">暂无持仓数据</div>';
                    return;
                }

                cardsEl.innerHTML = holdings.map(h => {
                    const pnl = h.pnl || h.profit_loss || 0;
                    const pnlPct = h.pnl_pct || h.profit_loss_pct || 0;
                    const isProfit = pnl >= 0;
                    const sign = isProfit ? '+' : '';
                    return `<div class="portfolio-card ${isProfit ? 'profit' : 'loss'}">
                        <div class="fund-name">${h.fund_name || h.name || '--'}</div>
                        <div class="fund-detail">
                            代码: ${h.fund_code || h.code || '--'} | 持有: ${h.shares || '--'}份<br>
                            成本: ¥${(h.cost || h.avg_cost || 0).toFixed(4)} | 现价: ¥${(h.nav || h.current_nav || h.price || 0).toFixed(4)}
                        </div>
                        <div class="pnl ${isProfit ? 'positive' : 'negative'}">${sign}¥${pnl.toFixed(2)} (${sign}${pnlPct.toFixed(2)}%)</div>
                    </div>`;
                }).join('');

                loadInvestAlerts();
            } catch (e) {
                console.log('持仓数据加载跳过:', e.message);
                document.getElementById('portfolio-summary').textContent = '持仓服务暂不可用';
            }
        }

        async function loadInvestAlerts() {
            try {
                const resp = await fetchWithTimeout('/api/invest-stats', {}, 5000);
                if (!resp.ok) return;
                const data = await resp.json();
                if (data.alerts && data.alerts.length > 0) {
                    renderList('invest-alerts', data.alerts, item =>
                        `<div class="item"><div class="item-title">${item.fund_name || ''}</div><div class="item-meta"><span class="badge badge-hot">${item.alert_type || '预警'}</span> ${item.message || ''}</div></div>`
                    );
                }
            } catch (e) {
                console.log('投资预警加载跳过:', e.message);
            }
        }

        async function loadBacktest() {
            try {
                const resp = await fetch('/api/backtest-report');
                const data = await resp.json();
                const el = document.getElementById('backtest-info');

                if (data.error && (!data.reports || data.reports.length === 0)) {
                    el.innerHTML = `<div class="empty">${data.error || data.message || '暂无回测报告'}</div>`;
                    return;
                }

                let html = '';
                if (data.reports && data.reports.length > 0) {
                    html += `<div style="margin-bottom:10px;">共 ${data.reports.length} 份报告</div>`;
                    data.reports.forEach(r => {
                        html += `<div class="item"><div class="item-title">${r.name}</div><div class="item-meta">${r.size_kb} KB | ${r.modified}</div></div>`;
                    });
                }
                if (data.latest_content) {
                    html += `<div style="margin-top:15px;"><div style="font-weight:500; margin-bottom:8px;">最新报告内容：</div><div class="backtest-content">${data.latest_content}</div></div>`;
                }
                el.innerHTML = html || '<div class="empty">暂无回测报告</div>';
            } catch (e) {
                console.log('回测报告加载跳过:', e.message);
            }
        }

        async function loadFunds() {
            try {
                const resp = await fetch('/api/funds');
                const data = await resp.json();
                const el = document.getElementById('fund-list');
                const funds = data.funds || [];

                if (funds.length === 0) {
                    el.innerHTML = '<div class="empty">暂无基金，请添加</div>';
                    return;
                }

                el.innerHTML = funds.map(f => {
                    const code = f.fund_code || f.code || '';
                    const name = f.fund_name || f.name || '--';
                    const amount = f.monthly_invest || '--';
                    const nav = f.nav || f.current_nav || f.price || '';
                    const pnl = f.pnl || f.profit || 0;
                    const pnlPct = f.pnl_pct || f.profit_rate || 0;
                    const pnlClass = pnl >= 0 ? 'positive' : 'negative';
                    const sign = pnl >= 0 ? '+' : '';
                    return `<div class="portfolio-card ${pnl >= 0 ? 'profit' : 'loss'}" style="display:flex; justify-content:space-between; align-items:center;">
                        <div>
                            <div class="fund-name">${name}</div>
                            <div class="fund-detail">代码: ${code} | 定投: ¥${amount}/月${nav ? ' | 净值: ¥' + Number(nav).toFixed(4) : ''}</div>
                            ${pnl ? `<div class="pnl ${pnlClass}" style="font-size:16px;">${sign}¥${pnl.toFixed(2)} (${sign}${pnlPct.toFixed(2)}%)</div>` : ''}
                        </div>
                        <button onclick="deleteFund('${code}')" style="background:#ff4444; color:white; border:none; padding:6px 12px; border-radius:4px; cursor:pointer; font-size:12px;">删除</button>
                    </div>`;
                }).join('');
            } catch (e) {
                console.log('基金列表加载失败:', e.message);
            }
        }

        async function addFund() {
            const code = document.getElementById('fundCode').value.trim();
            const name = document.getElementById('fundName').value.trim();
            const amount = parseInt(document.getElementById('fundAmount').value) || 200;

            if (!code) {
                alert('请输入基金代码');
                return;
            }

            try {
                const resp = await fetch('/api/funds', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({code, name, monthly_invest: amount})
                });
                const data = await resp.json();
                if (data.error) {
                    alert(data.error);
                } else {
                    alert(data.message || '添加成功');
                    document.getElementById('fundCode').value = '';
                    document.getElementById('fundName').value = '';
                    loadFunds();
                }
            } catch (e) {
                alert('添加失败: ' + e.message);
            }
        }

        async function deleteFund(code) {
            if (!confirm(`确定删除基金 ${code}？`)) return;
            try {
                const resp = await fetch(`/api/funds/${code}`, {method: 'DELETE'});
                const data = await resp.json();
                if (data.error) {
                    alert(data.error);
                } else {
                    alert(data.message || '删除成功');
                    loadFunds();
                }
            } catch (e) {
                alert('删除失败: ' + e.message);
            }
        }

        async function fetchWithTimeout(url, options = {}, timeout = 5000) {
            const controller = new AbortController();
            const id = setTimeout(() => controller.abort(), timeout);
            try {
                const resp = await fetch(url, {...options, signal: controller.signal});
                clearTimeout(id);
                return resp;
            } catch(e) {
                clearTimeout(id);
                throw e;
            }
        }

        async function loadSentiment() {
            try {
                if (typeof Chart === 'undefined') {
                    console.log('Chart.js 尚未加载，跳过情绪图表');
                    return;
                }

                const resp = await fetchWithTimeout('/api/market-sentiment', {}, 5000);
                if (!resp.ok) return;
                const data = await resp.json();
                if (data.error) { console.log('情绪数据不可用:', data.error); return; }

                const gauge = document.getElementById('sentiment-gauge');
                const level = document.getElementById('sentiment-level');
                const trend = document.getElementById('sentiment-trend');
                const details = document.getElementById('sentiment-details');

                gauge.textContent = data.index.toFixed(0);
                level.textContent = data.level;
                trend.textContent = `趋势: ${data.trend || '平稳'}`;

                const colorMap = {
                    '极度恐惧': '#00cc44', '恐惧': '#88cc00', '中性': '#ffcc00',
                    '贪婪': '#ff8800', '极度贪婪': '#ff4444'
                };
                gauge.style.color = colorMap[data.level] || '#ffcc00';

                if (data.components) {
                    const comp = data.components;
                    const labels = ['新闻情绪', '市场动量', '波动率', '技术信号', '社交情绪'];
                    const keys = ['news_sentiment', 'market_momentum', 'volatility', 'technical_signals', 'social_sentiment'];
                    const scores = keys.map(k => (comp[k]?.score || 0) * 100);

                    if (window.sentimentRadarChart) window.sentimentRadarChart.destroy();
                    const ctx = document.getElementById('sentimentRadar').getContext('2d');
                    window.sentimentRadarChart = new Chart(ctx, {
                        type: 'radar',
                        data: {
                            labels: labels,
                            datasets: [{
                                label: '情绪维度',
                                data: scores,
                                backgroundColor: 'rgba(26, 26, 46, 0.15)',
                                borderColor: '#1a1a2e',
                                pointBackgroundColor: '#1a1a2e',
                            }]
                        },
                        options: {
                            responsive: true,
                            scales: { r: { min: 0, max: 100, ticks: { stepSize: 20 } } },
                            plugins: { legend: { display: false } }
                        }
                    });

                    details.innerHTML = keys.map((k, i) => {
                        const nameMap = {news_sentiment:'新闻情绪',market_momentum:'市场动量',volatility:'波动率',technical_signals:'技术信号',social_sentiment:'社交情绪'};
                        const d = comp[k] || {};
                        return `<span style="margin-right:15px;">${nameMap[k]}: <b>${scores[i].toFixed(0)}</b> (${(d.weight*100).toFixed(0)}%)</span>`;
                    }).join('');
                }

                const histResp = await fetchWithTimeout('/api/market-sentiment?action=history&days=30', {}, 5000);
                if (histResp.ok) {
                    const histData = await histResp.json();
                    const history = histData.history || [];
                    if (history.length > 1) {
                        if (window.sentimentTrendChart) window.sentimentTrendChart.destroy();
                        const ctx2 = document.getElementById('sentimentTrend').getContext('2d');
                        window.sentimentTrendChart = new Chart(ctx2, {
                            type: 'line',
                            data: {
                                labels: history.map(h => h.date ? h.date.substring(5) : ''),
                                datasets: [{
                                    label: '情绪指数',
                                    data: history.map(h => h.index),
                                    borderColor: '#1a1a2e',
                                    backgroundColor: 'rgba(26, 26, 46, 0.1)',
                                    tension: 0.4, fill: true,
                                }]
                            },
                            options: {
                                responsive: true,
                                scales: { y: { min: 0, max: 100 } },
                                plugins: { legend: { display: false } }
                            }
                        });
                    }
                }
            } catch (e) {
                console.log('市场情绪指数加载跳过:', e.message);
            }
        }

        loadData();
        loadSentiment();
        loadPortfolio();
        loadBacktest();
        loadFunds();
        setInterval(loadData, 60000);
        setInterval(loadSentiment, 300000);
        setInterval(loadPortfolio, 300000);

        var chartUrls = [
            'https://cdn.bootcdn.net/ajax/libs/Chart.js/4.4.7/chart.umd.min.js',
            'https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js',
            'https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.7/chart.umd.min.js'
        ];
        function loadChartScript(idx) {
            if (idx >= chartUrls.length) return;
            var s = document.createElement('script');
            s.src = chartUrls[idx];
            s.onload = function() {
                console.log('Chart.js 加载成功: ' + chartUrls[idx]);
                loadTrend();
                loadSentiment();
            };
            s.onerror = function() {
                console.log('Chart.js 加载失败: ' + chartUrls[idx] + '，尝试下一个');
                loadChartScript(idx + 1);
            };
            document.body.appendChild(s);
        }
        loadChartScript(0);
    </script>
</body>
</html>"""


@app.route('/')
def dashboard():
    """Dashboard 主页（优先加载模板文件，fallback到内嵌HTML）"""
    html_path = os.path.join(os.path.dirname(__file__), 'templates', 'dashboard.html')
    if os.path.exists(html_path):
        return open(html_path, encoding='utf-8').read()
    return DASHBOARD_HTML


def create_app():
    """创建 Flask 应用"""
    # 加载 .env
    env_path = Path(__file__).parent.parent / '.env'
    if env_path.exists():
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    if key and key not in os.environ:
                        os.environ[key] = value

    # 认证配置
    auth_token = os.environ.get("DASHBOARD_AUTH_TOKEN", "")
    auth_enabled = auth_token != ""

    if auth_enabled:
        logger.info("Dashboard 认证已启用")

        @app.before_request
        def check_auth():
            """检查请求认证"""
            # 健康检查端点不需要认证
            if request.path == '/health':
                return None

            # 静态资源不需要认证
            if request.path.startswith('/static/'):
                return None

            # 从 header 或 query 参数获取 token
            token = request.headers.get('Authorization', '').replace('Bearer ', '')
            if not token:
                token = request.args.get('token', '')

            if token != auth_token:
                return jsonify({"error": "未授权访问", "message": "请提供有效的认证token"}), 401

    # 健康检查端点
    @app.route('/health')
    def health():
        """健康检查"""
        return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()})

    # 更新数据库路径（支持自动查找最新数据库）
    # 优先使用环境变量，然后查找最新的数据库文件
    data_base = Path(os.environ.get("DATA_BASE", "/app/data"))

    # TrendRadar 热榜数据库（按日期存储：news/2026-05-27.db）
    trendradar_news_dir = data_base / "search_information" / "news"
    if trendradar_news_dir.exists():
        DB_PATHS["trendradar"] = find_latest_db(str(trendradar_news_dir))
    else:
        DB_PATHS["trendradar"] = os.environ.get("TRENDRADAR_DB", "")

    # RSS 数据库（按日期存储：rss/2026-05-27.db）
    rss_dir = data_base / "search_information" / "rss"
    if rss_dir.exists():
        DB_PATHS["rss"] = find_latest_db(str(rss_dir))
    else:
        DB_PATHS["rss"] = os.environ.get("RSS_DB", "")

    # 分析数据库（兼容 analyzer.db 和 analyzed.db）
    analyse_default = os.environ.get("ANALYSE_DB", str(data_base / "knowledge_base" / "analyzed.db"))
    DB_PATHS["analyse"] = resolve_db_path("analyse", analyse_default, [
        str(data_base / "knowledge_base" / "analyzer.db"),
        str(data_base / "knowledge_base" / "analyzed.db"),
        str(data_base / "shared" / "data" / "analyzer.db"),
    ])

    # 求职数据库
    DB_PATHS["jobs"] = os.environ.get("JOBS_DB", str(data_base / "find_job" / "jobs.db"))

    # 投资数据库
    DB_PATHS["invest"] = os.environ.get("INVEST_DB", str(data_base / "invest" / "fund_data.db"))

    logger.info(f"数据库路径: {DB_PATHS}")

    return app


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    app = create_app()
    app.run(host='0.0.0.0', port=5060, debug=False)
