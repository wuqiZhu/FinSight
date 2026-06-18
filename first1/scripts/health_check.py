# -*- coding: utf-8 -*-
"""
百器系统 — 全功能健康检查

一键检查所有服务和功能是否正常。

用法:
    python3 health_check.py                  # 完整检查
    python3 health_check.py --quick          # 快速检查（30秒）
    python3 health_check.py --slack          # 输出到钉钉/通知
    python3 health_check.py --watch          # 持续监控（每60秒刷新）
"""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

# ── 颜色 ──
G = "\033[92m"   # green
Y = "\033[93m"   # yellow
R = "\033[91m"   # red
B = "\033[94m"   # blue
N = "\033[0m"    # reset

# ── 配置 ──
SERVERS = {
    "新加坡": {"host": "188.166.249.182", "user": "root"},
    "阿里云": {"host": "8.140.232.52", "user": "root"},
}

CONTAINERS = [
    "trendradar", "dashboard", "invest-backend", "semantic-search",
    "analyser", "invest-frontend", "feedback-learner", "notification-center",
]

APIS = {
    "invest-backend": "http://localhost:5000/api/health",
    "semantic-search": "http://localhost:5070/health",
    "notification-center": "http://localhost:5050/health",
    "dashboard": "http://localhost:5060/api/health",
}

EXPECTED_MODELS = ["sentiment", "category", "relevance"]


class HealthCheck:
    def __init__(self, quick=False):
        self.quick = quick
        self.results = []
        self.start_time = time.time()

    def log(self, status: str, item: str, detail: str = ""):
        """记录检查结果"""
        icons = {"✅": "✅", "⚠️": "⚠️", "❌": "❌", "ℹ️": "ℹ️"}
        colors = {"✅": G, "⚠️": Y, "❌": R, "ℹ️": B}
        icon = icons.get(status, "ℹ️")
        color = colors.get(status, N)
        ts = datetime.now().strftime("%H:%M:%S")
        msg = f"{color}{icon} [{ts}] {item}{N}"
        if detail:
            msg += f" — {detail}"
        print(msg)
        self.results.append({"status": status, "item": item, "detail": detail, "ts": ts})

    def run_cmd(self, cmd: str, timeout: int = 15) -> tuple:
        """运行 SSH 命令"""
        try:
            r = subprocess.run(
                ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5",
                 "server"] + cmd.split(),
                capture_output=True, text=True, timeout=timeout,
            )
            return r.returncode, r.stdout.strip(), r.stderr.strip()
        except subprocess.TimeoutExpired:
            return -1, "", "timeout"
        except Exception as e:
            return -1, "", str(e)

    def run_docker(self, cmd: str, timeout: int = 15) -> tuple:
        """在新加坡容器内执行命令"""
        return self.run_cmd(f"docker exec trendradar {cmd}", timeout)

    def http_get(self, url: str, timeout: int = 10) -> tuple:
        """HTTP GET 请求"""
        try:
            r = urllib.request.urlopen(url, timeout=timeout)
            return r.status, r.read().decode()[:200]
        except Exception as e:
            return 0, str(e)

    # ── 检查项 ──

    def check_server(self, name: str, host: str):
        """服务器连通性"""
        try:
            r = subprocess.run(
                ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5",
                 "-o", "BatchMode=yes", f"root@{host}", "echo ok"],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0:
                self.log("✅", f"服务器 {name} ({host})", "连通正常")
            else:
                self.log("⚠️", f"服务器 {name} ({host})", f"SSH失败: {r.stderr[:100]}")
        except Exception as e:
            self.log("❌", f"服务器 {name} ({host})", str(e)[:100])

    def check_container(self, name: str):
        """单个容器状态"""
        code, out, err = self.run_cmd(f"docker ps --filter name={name} --format '{{{{.Status}}}}'")
        if code == 0 and out:
            if "Up" in out:
                uptime = out.replace("Up ", "").split()[0]
                self.log("✅", f"容器 {name}", f"运行中 ({uptime})")
            elif "Restarting" in out:
                self.log("❌", f"容器 {name}", f"重启循环! {out}")
            else:
                self.log("⚠️", f"容器 {name}", out)
        else:
            self.log("❌", f"容器 {name}", "未运行")
        return out

    def check_containers(self):
        """所有容器状态"""
        self.log("ℹ️", "检查容器状态...")
        code, out, err = self.run_cmd("docker ps --format '{{.Names}} {{.Status}}'")
        if code == 0:
            running = []
            for line in out.split("\n"):
                parts = line.split()
                if parts:
                    name = parts[0]
                    status = " ".join(parts[1:])
                    if "Up" in status:
                        self.log("✅", f"  容器 {name}", status.split()[0])
                        running.append(name)
                    else:
                        self.log("❌", f"  容器 {name}", status)

            # 检查是否所有容器都在运行
            for c in CONTAINERS:
                if c not in running:
                    self.log("❌", f"  容器 {c}", "未运行!")
        else:
            self.log("❌", "Docker", "无法连接")

    def check_resources(self):
        """服务器资源"""
        self.log("ℹ️", "检查服务器资源...")
        code, out, err = self.run_cmd("free -h | grep Mem")
        if code == 0:
            parts = out.split()
            if len(parts) >= 3:
                total = parts[1]
                used = parts[2]
                # 解析数值
                used_val = float(used.replace("Gi", "").replace("Mi", ""))
                total_val = float(total.replace("Gi", "").replace("Mi", ""))
                pct = used_val / total_val * 100 if total_val > 0 else 0
                if pct > 85:
                    self.log("⚠️", f"  内存", f"{used}/{total} ({pct:.0f}%)")
                else:
                    self.log("✅", f"  内存", f"{used}/{total} ({pct:.0f}%)")

        code, out, err = self.run_cmd("df -h / | tail -1")
        if code == 0:
            parts = out.split()
            if len(parts) >= 5:
                self.log("✅", f"  磁盘", f"{parts[3]}/{parts[1]} ({parts[4]})")

    def check_sentinel(self):
        """第1层 哨兵模型"""
        self.log("ℹ️", "检查第1层 哨兵...")
        code, out, err = self.run_docker(
            "python3 -c \"from classifier_server import get_classifier; c=get_classifier(); "
            "print(';'.join(c.sessions.keys())); print(sum(1 for _ in c.sessions));\"",
            timeout=30,
        )
        if code == 0:
            lines = out.strip().split("\n")
            models = lines[0].split(";") if ";" in lines[0] else []
            count = len(models)
            missing = [m for m in EXPECTED_MODELS if m not in models]
            if not missing:
                self.log("✅", f"  哨兵模型", f"{count}个全部加载: {', '.join(models)}")
            else:
                self.log("⚠️", f"  哨兵模型", f"缺 {missing}")
        else:
            self.log("❌", "  哨兵模型", f"加载失败: {err[:100]}")

    def check_ai_analysis(self):
        """第3层 AI 分析"""
        self.log("ℹ️", "检查第3层 DeepSeek...")
        # 检查最近一次 AI 分析是否成功
        code, out, err = self.run_docker(
            "grep -E 'AI.*分析完成|AI.*分析失败' /proc/1/fd/1 2>/dev/null | tail -3 || "
            "docker logs trendradar 2>&1 | grep -E 'AI.*分析完成|AI.*分析失败' | tail -3"
        )
        if "分析完成" in out:
            self.log("✅", "  DeepSeek 分析", "最近一次成功")
        elif "分析失败" in out:
            self.log("❌", "  DeepSeek 分析", f"最近失败: {out[:100]}")
        else:
            self.log("⚠️", "  DeepSeek 分析", "无最近记录（可能还没运行）")

    def check_cache(self):
        """AI 响应缓存"""
        self.log("ℹ️", "检查 AI 缓存...")
        code, out, err = self.run_docker(
            "python3 -c \"from trendradar.ai.response_cache import get_cache; "
            "s=get_cache().get_stats(); print(f'entries={s[\\\"total_entries\\\"]} hits={s[\\\"hits\\\"]} misses={s[\\\"misses\\\"]} rate={s[\\\"hit_rate\\\"]}')\"",
            timeout=10,
        )
        if code == 0 and "entries=" in out:
            parts = out.split()
            entries = parts[0].split("=")[1]
            rate = parts[3].split("=")[1]
            self.log("✅", f"  AI 缓存", f"{entries} 条, 命中率 {rate}%")
        else:
            self.log("⚠️", "  AI 缓存", f"查询失败: {err[:100]}")

    def check_training_buffer(self):
        """训练数据缓冲池"""
        self.log("ℹ️", "检查数据缓冲池...")
        code, out, err = self.run_docker(
            "python3 -c \"from trendradar.ai.training_buffer import get_buffer; "
            "s=get_buffer().get_stats(); print(f'today={s[\\\"today_unexported\\\"]} total={s[\\\"total_unexported\\\"]} exported={s[\\\"total_exported\\\"]}')\"",
            timeout=10,
        )
        if code == 0 and "today=" in out:
            parts = out.split()
            today = parts[0].split("=")[1]
            exported = parts[2].split("=")[1]
            self.log("✅", f"  缓冲池", f"今日 {today} 条, 已导出 {exported} 条")
        else:
            self.log("⚠️", "  缓冲池", "查询失败")

    def check_invest_api(self):
        """投资后端 API"""
        self.log("ℹ️", "检查投资后端...")
        code, out, err = self.run_cmd(
            "curl -s --connect-timeout 5 http://localhost:5000/api/health"
        )
        if "ok" in out.lower() or "health" in out.lower():
            self.log("✅", "  invest-backend API", "响应正常")
        else:
            self.log("❌", "  invest-backend API", f"异常: {out[:100]}")

        # 持仓数据
        code, out, err = self.run_cmd(
            "curl -s --connect-timeout 5 http://localhost:5000/api/portfolio"
        )
        if code == 0 and out:
            try:
                data = json.loads(out)
                holdings = data.get("holdings", [])
                profit = data.get("total_profit", 0)
                self.log("✅", f"  持仓数据", f"{len(holdings)} 只基金, 总盈亏 {profit:+.0f}元")
            except:
                self.log("⚠️", "  持仓数据", "解析失败")

        # 市场情绪
        code, out, err = self.run_cmd(
            "curl -s --connect-timeout 5 http://localhost:5000/api/market-sentiment?action=current"
        )
        if code == 0 and out:
            try:
                data = json.loads(out)
                idx = data.get("index", "?")
                level = data.get("level", "?")
                self.log("✅", f"  市场情绪", f"{level}({idx})")
            except:
                self.log("⚠️", "  市场情绪", "解析失败")

    def check_prediction_registry(self):
        """预测注册表"""
        self.log("ℹ️", "检查预测注册表...")
        db_path = "/root/projects/invest/data/prediction_registry/predictions.db"
        if os.path.exists(db_path):
            try:
                conn = sqlite3.connect(db_path)
                total = conn.execute("SELECT COUNT(*) FROM flags").fetchone()[0]
                verified = conn.execute("SELECT COUNT(*) FROM flags WHERE accuracy IS NOT NULL").fetchone()[0]
                avg_acc = conn.execute("SELECT AVG(accuracy) FROM flags WHERE accuracy IS NOT NULL").fetchone()[0] or 0
                conn.close()
                self.log("✅", f"  预测注册表", f"{total} 面旗, 已验证 {verified}, 准确率 {avg_acc*100:.0f}%")
            except Exception as e:
                self.log("⚠️", "  预测注册表", f"数据库异常: {e}")
        else:
            self.log("⚠️", "  预测注册表", "数据库未创建（还没插过旗）")

    def check_dingtalk(self):
        """钉钉推送"""
        self.log("ℹ️", "检查钉钉推送...")
        # 从日志查最近推送
        code, out, err = self.run_cmd(
            "docker logs trendradar 2>&1 | grep -E '推送.*发送|钉钉.*发送|消息分为' | tail -3"
        )
        if out:
            for line in out.strip().split("\n")[:2]:
                self.log("✅", f"  最近推送", line[:80])
        else:
            # 查通知中心
            code, out, err = self.run_cmd(
                "curl -s --connect-timeout 5 http://localhost:5050/health 2>&1"
            )
            if code == 0:
                self.log("✅", "  通知中心", "运行中（等待下次推送）")
            else:
                self.log("⚠️", "  通知中心", "未响应")

    def check_pipeline_freshness(self):
        """检查流水线数据新鲜度"""
        self.log("ℹ️", "检查数据新鲜度...")
        # 检查今天有没有新闻数据
        today = datetime.now().strftime("%Y-%m-%d")
        code, out, err = self.run_cmd(
            f"docker exec trendradar python3 -c \"import sqlite3,os; "
            f"p='/app/output/news/{today}.db'; "
            f"print(os.path.exists(p)); "
            f"if os.path.exists(p): conn=sqlite3.connect(p); print(conn.execute('SELECT COUNT(*) FROM news_items').fetchone()[0]); conn.close()"
        )
        if code == 0:
            lines = out.strip().split("\n")
            if len(lines) >= 2 and lines[0] == "True":
                self.log("✅", f"  今日数据", f"数据库存在, {lines[1]} 条新闻")

        # RSS
        code, out, err = self.run_cmd(
            f"docker exec trendradar python3 -c \"import sqlite3,os; "
            f"p='/app/output/rss/{today}.db'; "
            f"print(os.path.exists(p)); "
            f"if os.path.exists(p): conn=sqlite3.connect(p); print(conn.execute('SELECT COUNT(*) FROM rss_items').fetchone()[0]); conn.close()"
        )
        if code == 0:
            lines = out.strip().split("\n")
            if len(lines) >= 2 and lines[0] == "True":
                self.log("✅", f"  今日 RSS", f"数据库存在, {lines[1]} 条")

    def check_aliyun_lora(self):
        """阿里云 LoRA 服务"""
        self.log("ℹ️", "检查阿里云 LoRA...")
        code, out, err = self.run_cmd(
            "curl -s --connect-timeout 5 http://8.140.232.52:5075/health 2>&1"
        )
        if "ok" in out:
            try:
                data = json.loads(out)
                adapters = data.get("available_adapters", [])
                current = data.get("current_adapter", "")
                self.log("✅", f"  LoRA 服务", f"{len(adapters)}个适配器: {', '.join(adapters)}, 当前: {current}")
            except:
                self.log("✅", "  LoRA 服务", "响应正常")
        else:
            self.log("⚠️", "  LoRA 服务", "不可达（防火墙或未运行）")

    # ── 报告 ──

    def generate_report(self) -> str:
        """生成文本报告"""
        elapsed = time.time() - self.start_time
        ok = sum(1 for r in self.results if r["status"] == "✅")
        warn = sum(1 for r in self.results if r["status"] == "⚠️")
        err = sum(1 for r in self.results if r["status"] == "❌")
        total = len(self.results)

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        score = ok / total * 100 if total > 0 else 0

        lines = [
            f"📋 **百器系统健康报告** ({timestamp})",
            "",
            f"🟢 正常: {ok}/{total}  ⚠️ 警告: {warn}  ❌ 故障: {err}",
            f"📊 健康分: {score:.0f}%  ⏱️ 耗时: {elapsed:.0f}s",
            "",
        ]

        # 按类别分组
        categories = {
            "✅": {"title": "正常", "items": []},
            "⚠️": {"title": "警告", "items": []},
            "❌": {"title": "故障", "items": []},
        }
        for r in self.results:
            cat = categories.get(r["status"])
            if cat:
                cat["items"].append(r)

        for status, cat in categories.items():
            if cat["items"]:
                lines.append(f"**{cat['title']}**")
                for r in cat["items"]:
                    lines.append(f"  {status} {r['item']}")
                    if r["detail"]:
                        lines.append(f"    {r['detail']}")
                lines.append("")

        return "\n".join(lines)

    def push_to_dingtalk(self, report: str):
        """推送到钉钉"""
        webhook = os.environ.get("DINGTALK_WEBHOOK_URL") or ""
        if not webhook:
            webhook = input("钉钉 Webhook URL: ").strip()
        if not webhook:
            print("跳过推送")
            return
        data = json.dumps({
            "msgtype": "markdown",
            "markdown": {"title": "📋 系统健康报告", "text": report},
        }).encode()
        try:
            r = json.loads(urllib.request.urlopen(
                urllib.request.Request(webhook, data=data,
                    headers={"Content-Type": "application/json"}), timeout=10
            ).read())
            if r.get("errcode") == 0:
                print("✅ 推送成功")
            else:
                print(f"⚠️ {r.get('errmsg','')}")
        except Exception as e:
            print(f"❌ {e}")

    def run_all(self):
        """执行全部检查"""
        print(f"\n{'='*60}")
        print(f"  🔍 百器系统健康检查")
        print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}\n")

        # ── 服务器层 ──
        self.check_server("新加坡", "188.166.249.182")
        self.check_server("阿里云", "8.140.232.52")

        if not self.quick:
            self.check_resources()

        # ── 容器层 ──
        self.check_containers()

        # ── 第1层 哨兵 ──
        if not self.quick:
            self.check_sentinel()

        # ── 数据层 ──
        if not self.quick:
            self.check_pipeline_freshness()
            self.check_cache()
            self.check_training_buffer()

        # ── 第3层 AI ──
        self.check_ai_analysis()

        # ── 投资后端 ──
        self.check_invest_api()

        # ── 预测 ──
        self.check_prediction_registry()

        # ── 推送 ──
        self.check_dingtalk()

        # ── 阿里云 LoRA ──
        if not self.quick:
            self.check_aliyun_lora()

        # ── 报告 ──
        print(f"\n{'='*60}")
        report = self.generate_report()
        print(report)
        print(f"{'='*60}\n")

        return report


def main():
    parser = argparse.ArgumentParser(description="百器系统健康检查")
    parser.add_argument("--quick", action="store_true", help="快速检查（跳过耗时项）")
    parser.add_argument("--push", action="store_true", help="推送到钉钉")
    parser.add_argument("--watch", type=int, metavar="SECONDS", help="持续监控模式")
    args = parser.parse_args()

    if args.watch:
        print(f"📡 持续监控模式 (间隔 {args.watch}s, Ctrl+C 退出)")
        try:
            while True:
                os.system("clear" if os.name == "posix" else "cls")
                hc = HealthCheck(quick=True)
                hc.run_all()
                time.sleep(args.watch)
        except KeyboardInterrupt:
            print("\n退出")
        return

    hc = HealthCheck(quick=args.quick)
    report = hc.run_all()

    if args.push:
        hc.push_to_dingtalk(report)


if __name__ == "__main__":
    main()
