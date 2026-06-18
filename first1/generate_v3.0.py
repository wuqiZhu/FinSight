#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
场景生成器 v3.0 — 长文本 + 多领域 + 多任务

相比 v2.2 的核心改进：
  1. 新增 6 种长文本任务（回复 500-2000 字符），解决"回复太短"问题
  2. 新增港股/美股/宏观专项种子，解决领域覆盖不均
  3. 从 5 种任务扩展到 15+ 种
  4. 指令模板多样性提升 3x+
  5. 可控的长/短文本混合比例

运行方式（在阿里云服务器上）：
  python3 generate_v3.0.py                        # 生成长文本数据
  python3 generate_v3.0.py --mode mix             # 混合模式（长+短）
  python3 generate_v3.0.py --mode hk-stock        # 专门补港股
  python3 generate_v3.0.py --target 100000        # 生成 10 万条
"""

import json, os, requests, time, random, threading, argparse, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# ====== API 配置（从环境变量读取） ======
import os as _os
_keys_env = _os.environ.get('MIMO_API_KEYS', '')
API_KEYS = [k.strip() for k in _keys_env.split(',') if k.strip()] if _keys_env else []
if not API_KEYS:
    print("Error: 请设置 MIMO_API_KEYS 环境变量（逗号分隔多个key）")
    sys.exit(1)
API_URL = _os.environ.get('MIMO_API_URL', 'https://token-plan-cn.xiaomimimo.com/v1/chat/completions')
MODEL = _os.environ.get('MIMO_MODEL', 'mimo-v2.5-pro')
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "generated_v3")
_key_lock = threading.Lock()
_key_index = 0

def get_next_key():
    global _key_index
    with _key_lock:
        key = API_KEYS[_key_index % len(API_KEYS)]
        _key_index += 1
        return key

# ====== 基础配置 ======
MAX_WORKERS = 6  # 429限流严重，降低并发

# ====== 任务模板定义 ======
#
# 每条模板包含：
#   name:       任务名称
#   type:       short | long （长文本/短文本）
#   system:     AI 的系统提示
#   user:       用户问题模板（用 {title} 占位）
#   length:     期望长度描述，用于提示 AI
#   min_chars:  期望的最少字符数
#

TASK_TEMPLATES = [
    # ================================================================
    # 短文本任务（分类/评分类，单句即可，保留 v2.2 风格）
    # ================================================================
    {
        "name": "情绪分析",
        "type": "short",
        "system": "你是一个金融情绪分析专家。请准确判断新闻情绪。",
        "user": "判断以下新闻的情绪是正面、负面还是中性。\n新闻：{title}",
        "length": "1-10字",
        "min_chars": 2,
    },
    {
        "name": "相关性打分",
        "type": "short",
        "system": "你是金融分析师，评估新闻对投资的相关性。",
        "user": "评估以下内容对投资的相关性，请从0到10打分（0=无关，10=高度相关）。\n内容：{title}",
        "length": "1-10字",
        "min_chars": 1,
    },
    {
        "name": "新闻分类",
        "type": "short",
        "system": "你是一个金融新闻分类专家。",
        "user": "请将以下新闻分类：03-政策福利|04-行业动态|05-长期杠杆|06-嵌入式Linux|07-BSP开发|08-设备驱动|09-RISC-V|10-IoT|其他\n新闻：{title}",
        "length": "1-10字",
        "min_chars": 2,
    },
    {
        "name": "关键词提取",
        "type": "short",
        "system": "你是金融 NLP 专家，提取关键词。",
        "user": "从以下新闻中提取3-5个关键词。\n新闻：{title}",
        "length": "10-50字",
        "min_chars": 10,
    },

    # ================================================================
    # 中长文本任务（回复 >200 字符）
    # ================================================================
    {
        "name": "深度分析",
        "type": "long",
        "system": "你是一位资深金融分析师，有20年行业经验。请对以下新闻进行全面、深入的金融分析。分析要包含：1) 事件背景 2) 对相关公司/行业的具体影响 3) 市场各方反应 4) 未来趋势判断。要求分析有数据支撑、逻辑清晰、语言专业但不晦涩。",
        "user": "请对以下新闻进行全面深入的金融分析（200-300字）。\n新闻：{title}",
        "length": "200-300字",
        "min_chars": 200,
    },
    {
        "name": "投资建议",
        "type": "long",
        "system": "你是一位首席投资官，管理百亿级投资组合。请基于新闻事件，给出具体的投资操作建议。建议要包含：买入/卖出/持有的明确判断、具体的操作逻辑、风险点提示、预期持有周期。给出可执行、有逻辑支撑的建议，不要模棱两可。",
        "user": "基于以下新闻，请给出具体的投资操作建议（300-500字）。包括买入/卖出/持有的判断、操作逻辑和风险提示。\n新闻：{title}",
        "length": "300-500字",
        "min_chars": 300,
    },
    {
        "name": "风险提示",
        "type": "long",
        "system": "你是一位首席风险官（CRO），专门负责识别和评估金融市场的潜在风险。请基于新闻事件，从多角度分析可能的风险：基本面风险、市场风险、政策风险、黑天鹅事件。对每项风险给出概率评估和应对建议。",
        "user": "基于以下新闻，请从多角度分析潜在风险（300-500字）。包括基本面风险、市场风险、政策风险等，并给出应对建议。\n新闻：{title}",
        "length": "300-500字",
        "min_chars": 300,
    },
    {
        "name": "宏观解读",
        "type": "long",
        "system": "你是一位宏观经济分析师。请从宏观视角解读新闻事件，分析其对整体经济、货币政策、资本流动的影响。要求联系当前宏观经济背景（如通胀水平、利率环境、经济周期位置），给出有深度、有前瞻性的分析。",
        "user": "请从宏观经济视角解读以下新闻（300-500字）。联系当前经济背景，分析对政策、资本流动的影响。\n新闻：{title}",
        "length": "300-500字",
        "min_chars": 300,
    },
    {
        "name": "行业影响分析",
        "type": "long",
        "system": "你是一位行业研究主管。请分析新闻事件对相关行业的影响，包括：直接受益/受损的子行业、行业竞争格局变化、产业链传导效应、对头部公司的影响差异。要求有行业深度和专业洞察。",
        "user": "请分析以下新闻对相关行业的产业链影响（300-500字）。包括子行业传导、竞争格局变化、头部公司差异化影响。\n新闻：{title}",
        "length": "300-500字",
        "min_chars": 300,
    },
    {
        "name": "技术面分析",
        "type": "long",
        "system": "你是一位技术分析专家，精通K线、均线、MACD、RSI等技术指标。请基于消息面对相关股票的技术走势进行分析。分析要包含：支撑位/压力位判断、量价关系分析、技术指标信号、短期/中期走势预判。",
        "user": "请从技术分析角度解读以下新闻对相关股票走势的影响（300-500字）。包括关键价位、量价关系、技术指标信号。\n新闻：{title}",
        "length": "300-500字",
        "min_chars": 300,
    },
    {
        "name": "事件影响链",
        "type": "long",
        "system": "你是一位金融事件分析专家。请分析新闻事件可能引发的连锁反应和传导路径。从'第一波冲击->第二波传导->第三波扩散'的逻辑链条进行分析，涵盖不同市场和资产类别的传导。",
        "user": "请分析以下新闻事件可能引发的连锁反应和传导路径（300-500字）。按照冲击->传导->扩散的链条分析。\n新闻：{title}",
        "length": "300-500字",
        "min_chars": 300,
    },
    {
        "name": "财报解读",
        "type": "long",
        "system": "你是一位财务分析专家。请对公司的财务数据进行专业解读。包含：关键财务指标分析（营收/利润/毛利率/现金流等）、同比环比变化、与市场预期的对比、财务健康度评估、投资价值判断。",
        "user": "请对以下公司的财务数据进行专业解读（300-500字）。分析关键财务指标、变化趋势、投资价值。\n新闻：{title}",
        "length": "300-500字",
        "min_chars": 300,
    },
    {
        "name": "多标的对比",
        "type": "long",
        "system": "你是一位跨资产分析师。请从多维度进行对比分析：估值水平、成长性、风险收益比、行业地位、市场预期。给出清晰的对比结论和优先级排序。",
        "user": "请对以下新闻涉及的相关标的进行多维度对比分析（300-500字）。从估值、成长性、风险收益比等角度给出排序。\n新闻：{title}",
        "length": "300-500字",
        "min_chars": 300,
    },

    # ================================================================
    # 问答式任务（模拟多轮对话）
    # ================================================================
    {
        "name": "投资者问答",
        "type": "long",
        "system": "你是一位投资顾问，正在回答投资者的提问。回答要专业、易懂、有具体逻辑支撑，避免空泛的建议。",
        "user": "投资者问：\"{title}，请问你怎么看？对我持有的相关股票有什么影响？\"\n请以投资顾问身份回答（200-400字）。",
        "length": "200-400字",
        "min_chars": 200,
    },
    {
        "name": "数据分析",
        "type": "long",
        "system": "你是一位金融数据分析师。请对新闻中涉及的交易数据/市场数据进行专业解读。分析数据背后的含义、趋势、异常点和投资信号。",
        "user": "请对以下新闻中涉及的市场数据进行专业分析（200-400字）。解读数据含义、趋势和投资信号。\n新闻：{title}",
        "length": "200-400字",
        "min_chars": 200,
    },
    {
        "name": "总结简报",
        "type": "long",
        "system": "你是一位金融简报编辑。请将新闻整理为简洁、专业的投资简报格式。格式：📌 事件概述 -> 💡 核心要点 -> 📊 市场影响 -> 🎯 投资启示。语言精炼，要点突出。",
        "user": "请将以下新闻整理为投资简报格式（200-400字）。包含事件概述、核心要点、市场影响和投资启示。\n新闻：{title}",
        "length": "200-400字",
        "min_chars": 200,
    },
]

# ====== 种子管理 ======

# A股种子（保留 v2.2 核心种子）
SEEDS_A_SHARE = [
    "突发！某光伏龙头Q3净利润暴增340%",
    "震惊！知名基金经理清仓新能源",
    "重磅！央行突然降准0.5个百分点",
    "深夜公告：某芯片公司获国家大基金50亿注资",
    "炸裂！AI概念股批量涨停",
    "工信部等八部门联合印发《新型储能制造业高质量发展行动方案》",
    "北向资金连续7日净流入超600亿，创年内最长买入纪录",
    "某医药巨头ADC新药三期临床数据超预期，分析师上调目标价",
    "两市成交额连续第10个交易日破万亿，券商股掀涨停潮",
    "3天涨20%，某低空经济概念股遭交易所问询",
    "5月新能源汽车出口量同比增长180%，比亚迪单月出口破10万辆",
    "某公司回购10亿元股份，占总股本2%",
    "茅台提价传闻再起，白酒板块集体异动",
    "宁德时代发布神行超充电池PLUS，充电10分钟续航800公里",
    "华为宣布开源鸿蒙PC版，信创板块应声大涨",
    "特斯拉FSD入华获批，自动驾驶概念股全线爆发",
    "某券商发布研报：当前A股估值处于历史低位",
    "中证协发布《证券公司数字化转型评估办法》",
    "全球半导体销售额连续8个月同比增长，行业复苏确认",
    "ETF规模突破2万亿，被动投资时代来临",
    "某地产龙头预告半年亏损超200亿，债务重组方案仍未落地",
    "国际油价暴跌7%创年内新低，OPEC+减产协议执行存疑",
    "某公司财务造假被证监会顶格处罚，董事长被终身市场禁入",
    "低代码开发平台赛道融资火热，今年已有7家获亿元级投资",
    "中央汇金增持四大行股份，释放稳定市场信号",
    "沪指跌破3000点，市场情绪陷入冰点",
    "国务院印发《关于加强监管防范风险推动资本市场高质量发展的若干意见》",
    "多家券商宣布降薪，金融行业薪酬改革加速",
    "北交所做市商制度正式落地，流动性有望改善",
    "科创板八条措施出台，硬科技企业融资通道拓宽",
]

# 港股专用种子（补齐当前短板）
SEEDS_HK_STOCK = [
    "恒生指数跌破20000点，南向资金逆势抄底",
    "重磅！香港将下调股票印花税，港股市场流动性有望改善",
    "腾讯控股Q2净利润同比增长53%，游戏业务回暖超预期",
    "阿里巴巴宣布二次上市后首次年度分红，每股派息0.5美元",
    "港交所推出港币-人民币双柜台模式，首批24只股票参与",
    "美团季度营收同比增长22%，到店业务竞争格局改善",
    "香港金管局跟随美联储维持基准利率不变",
    "内地与香港利率互换互联互通正式上线",
    "比亚迪股份港股突破300港元，市值超越大众成全球第三",
    "香港证监会就虚拟资产交易平台监管发布新指引",
    "小米集团SU7发布后首个完整季度，智能汽车业务收入超预期",
    "香港政府发布《财政预算案》，加大科技创新投入",
    "中芯国际港股财报显示产能利用率回升至85%",
    "港股IPO市场回暖，今年累计募资额突破千亿港元",
    "香港楼市撤辣后成交量暴涨3倍，地产股集体走强",
    "港股通扩容，新增纳入约100只中小市值股票",
    "香港金管局推出数字人民币跨境试点",
    "李嘉诚旗下长实集团宣布百亿回购计划",
    "香港交易所与沙特证交所签署合作协议",
    "快手港股财报首次实现季度净利润转正",
    "香港金融科技周开幕，央行数字货币成为焦点",
    "美团斥资百亿持续回购，提振市场信心",
    "香港虚拟银行牌照扩围，蚂蚁银行等获批新业务",
    "港股REITs市场首只房托ETF上市，认购超募10倍",
    "香港推出家办税收优惠政策，吸引全球富豪家族办公室落户",
]

# 美股专用种子（补齐短板）
SEEDS_US_STOCK = [
    "美联储维持利率不变，但暗示年内仍有两次加息",
    "英伟达Q1财报超预期，数据中心业务同比增长427%",
    "苹果Vision Pro预售火爆，供应链加单至200万台",
    "特斯拉Cybertruck正式交付，订单量突破200万辆",
    "微软Copilot全面商用化，企业客户订阅量超预期",
    "亚马逊AWS推出新一代AI芯片Trainium2",
    "Meta宣布首次分红，股价盘后大涨15%",
    "Google Gemini Pro多模态模型发布，AI竞争白热化",
    "台积电3nm制程良率突破90%，获得苹果M4全部订单",
    "美国SEC批准比特币现货ETF，加密货币市场暴涨",
    "OpenAI估值突破3000亿美元，完成新一轮融资",
    "高通推出骁龙8 Gen 4芯片，AI算力提升4倍",
    "AMD MI300X AI芯片订单暴增，挑战英伟达霸主地位",
    "美国CPI数据连续三个月回落，市场押注9月降息",
    "Salesforce宣布裁员10%，同时加码AI投资",
    "甲骨文云业务营收增长超预期，股价创历史新高",
    "美国10年期国债收益率突破4.5%，科技股承压",
    "Adobe推出AI视频生成工具Firefly Video公测",
    "Palantir获美国国防部10亿美元AI合同",
    "英特尔获得德国政府百亿欧元芯片补贴获批",
    "Spotify首次实现全年盈利，播客业务成增长引擎",
    "美国就业数据高于预期，软着陆预期升温",
    "Netflix订阅用户突破3亿，广告套餐增长迅猛",
    "优步被纳入标普500指数，股价大涨",
    "波音获得阿联酋航空百架777X大额订单",
]

# 宏观与政策专用种子
SEEDS_MACRO = [
    "中国1-5月规模以上工业企业利润同比增长3.4%",
    "国务院发布促进创业投资高质量发展政策措施",
    "中国5月CPI同比上涨0.3%，PPI环比上涨0.2%",
    "央行设立科技创新和技术改造再贷款，额度5000亿",
    "财政部发行超长期特别国债，支持国家重大战略",
    "中国5月出口同比增长7.6%，超出市场预期",
    "中美金融工作组在上海举行第五次会议",
    "中国宣布将开展新一轮财税体制改革",
    "央行下调LPR利率，1年期降至3.35%",
    "国家统计局：5月社会消费品零售总额同比增长3.7%",
    "国务院发布推动大规模设备更新和消费品以旧换新方案",
    "中国5月官方制造业PMI为49.5，经济恢复基础尚不牢固",
    "中央深改委通过《关于完善中国特色现代企业制度的意见》",
    "全国碳市场扩容，水泥、电解铝行业纳入交易范围",
    "中国4月外汇储备32000亿美元，央行连续18个月增持黄金",
    "国务院国资委推动央企加快布局战略性新兴产业",
    "中国与东盟自贸区3.0版谈判实质性结束",
    "商务部：将进一步放宽外资准入，缩减负面清单",
    "中国首次发布《气候变化适应型城市评价标准》",
    "全国统一大市场建设加速，破除地方保护壁垒",
]

# 行业专用种子（补全行业维度）
SEEDS_INDUSTRY = [
    "国内首颗车规级7nm智能座舱芯片出货量突破百万",
    "国家药监局批准首款国产GLP-1减肥药上市",
    "中国商业航天首次完成海上发射任务",
    "全国一体化算力网建设启动，算力基础设施投资将超万亿",
    "宁德时代神行PLUS电池发布，充电速度再提升30%",
    "中国信通院：5G基站总数突破400万",
    "国产大飞机C919累计订单突破1500架",
    "全国碳市场碳价突破100元/吨，创历史新高",
    "比亚迪第1000万辆新能源汽车下线",
    "中国工业机器人密度超越德国，位居全球第三",
    "国内首个千万吨级CCUS项目在山东投产",
    "人形机器人产业政策出台，目标2027年形成完整产业链",
    "EUV光刻机国产化取得突破，90nm分辨率验证完成",
    "华为云发布盘古大模型5.0，参数规模突破万亿",
    "国家医保局集中带量采购覆盖药品扩围至500种",
    "国内首个百万千瓦级海上风电项目全容量并网",
    "预制菜国家标准正式出台，行业进入规范发展期",
    "全球首个商用核聚变研究设施在中国开工建设",
    "中国邮轮产业复苏，国产大型邮轮交付第二艘",
    "虚拟现实产业规模突破3500亿元，苹果Vision Pro生态落地",
]

ALL_SEEDS = SEEDS_A_SHARE + SEEDS_HK_STOCK + SEEDS_US_STOCK + SEEDS_MACRO + SEEDS_INDUSTRY


def call_mimo(prompt, system_prompt, max_tokens=1000, temperature=0.7):
    """调用 MiMo API 生成内容"""
    api_key = get_next_key()
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    for attempt in range(8):
        try:
            resp = requests.post(API_URL, headers=headers, json=payload, timeout=30)
            if resp.status_code == 429:
                # 429不傻等，立刻换密钥
                api_key = get_next_key()
                headers["Authorization"] = f"Bearer {api_key}"
                time.sleep(2 * (attempt + 1))
                continue
            resp.raise_for_status()
            data = resp.json()
            choices = data.get("choices", [])
            if choices:
                msg = choices[0].get("message", {})
                content = msg.get("content", "")
                if content and content.strip():
                    return content.strip()
                reasoning = msg.get("reasoning_content", "")
                if reasoning and reasoning.strip():
                    return reasoning.strip()
            return None
        except requests.exceptions.Timeout:
            api_key = get_next_key()
            headers["Authorization"] = f"Bearer {api_key}"
            time.sleep(1)
        except Exception as e:
            api_key = get_next_key()
            headers["Authorization"] = f"Bearer {api_key}"
            time.sleep(1)
    return None


def generate_titles_from_seed(seed, count=15):
    """从种子生成标题（更强调多样性）"""
    prompt = f"""你是财经记者。基于以下新闻种子，生成{count}条不同角度、不同表述风格的新闻标题。

要求多样化：
  - 有的短（10字以内），有的长（包含具体数据）
  - 覆盖不同情绪（正面/负面/中性）
  - 包含不同市场（A股/港股/美股）
  - 包含具体公司名、行业名、数字
  - 不要全部是"突发/震惊/重磅"开头，有些用陈述句

输出JSON数组，每项只有title字段：
[{{"title": "..."}}, ...]

种子：{seed}"""
    resp = call_mimo(prompt, None, max_tokens=2000, temperature=0.9)
    if not resp:
        return []

    titles = []
    try:
        start = resp.find('[')
        end = resp.rfind(']') + 1
        if start >= 0 and end > start:
            parsed = json.loads(resp[start:end])
            for t in parsed:
                if isinstance(t, dict) and t.get("title"):
                    titles.append(t["title"])
                elif isinstance(t, str) and len(t) > 3:
                    titles.append(t)
    except:
        pass
    return titles


def generate_single_sample(title, template):
    """用一条标题+一个模板生成一条训练样本"""
    user_msg = template["user"].format(title=title)
    system_prompt = template["system"]

    if template["type"] == "short":
        max_tokens = 50
        temperature = 0.1
    else:
        max_tokens = 500  # 降到500，减少超时
        temperature = 0.7

    response = call_mimo(user_msg, system_prompt, max_tokens=max_tokens, temperature=temperature)
    if not response:
        return None

    # 长度检查（放宽：有内容就行，不卡300字）
    min_c = template.get("min_chars", 0)
    if len(response) < 50:  # 实在太短才丢
        print(f"    回复过短({len(response)}字符<50)，丢弃", flush=True)
        return None

    return {
        "conversations": [
            {"from": "human", "value": user_msg},
            {"from": "gpt", "value": response},
        ],
        "meta": {
            "task": template["name"],
            "type": template["type"],
            "template_idx": TASK_TEMPLATES.index(template),
        },
    }


def process_seed_batch(seed, templates, samples_per_seed=30):
    """处理一个种子：生成所有任务的样本"""
    print(f"  种子: {seed[:40]}...", flush=True)

    # 生成标题
    titles = generate_titles_from_seed(seed, count=15)
    if not titles:
        print(f"    标题生成失败，跳过", flush=True)
        return []

    print(f"    生成了 {len(titles)} 条标题", flush=True)

    # 为每个标题分配任务
    samples = []
    assigned_tasks = []
    for i in range(samples_per_seed):
        title = titles[i % len(titles)]
        template = templates[i % len(templates)]
        assigned_tasks.append((title, template))

    # 批量生成
    for title, template in assigned_tasks:
        sample = generate_single_sample(title, template)
        if sample:
            samples.append(sample)
            print(f"    ✓ {template['name']}: {len(sample['conversations'][1]['value'])}字符", flush=True)
        else:
            print(f"    ✗ {template['name']}: 生成失败", flush=True)
        time.sleep(1.5)  # 限流保护：每个请求间隔1.5秒

    print(f"    完成: {len(samples)}/{samples_per_seed} 条", flush=True)
    return samples


def get_long_templates():
    """获取所有长文本模板"""
    return [t for t in TASK_TEMPLATES if t["type"] == "long"]


def get_short_templates():
    """获取所有短文本模板"""
    return [t for t in TASK_TEMPLATES if t["type"] == "short"]


def get_all_templates():
    return TASK_TEMPLATES[:]


def get_hk_stock_templates():
    """港股专用模板——重点用宏观解读、行业影响、风险提示"""
    preferred = ["宏观解读", "行业影响分析", "风险提示", "深度分析", "投资建议"]
    return [t for t in TASK_TEMPLATES if t["name"] in preferred]


def main():
    parser = argparse.ArgumentParser(description="场景生成器 v3.0")
    parser.add_argument("--mode", type=str, default="long",
                        choices=["long", "mix", "hk-stock", "us-stock", "macro", "short"])
    parser.add_argument("--target", type=int, default=100000,
                        help="目标样本数（默认 10 万）")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    args = parser.parse_args()

    print("=" * 60)
    print(f"场景生成器 v3.0 启动")
    print(f"模式: {args.mode} | 目标: {args.target:,} 条 | 并发: {args.workers}")
    print("=" * 60)

    # 选择种子和模板
    if args.mode == "hk-stock":
        seeds = SEEDS_HK_STOCK
        templates = get_long_templates() + get_hk_stock_templates()
        print(f"📌 港股补强模式: {len(seeds)} 种子, {len(templates)} 模板")
    elif args.mode == "us-stock":
        seeds = SEEDS_US_STOCK
        templates = get_long_templates()
        print(f"📌 美股补强模式: {len(seeds)} 种子, {len(templates)} 模板")
    elif args.mode == "macro":
        seeds = SEEDS_MACRO
        templates = get_long_templates()
        print(f"📌 宏观补强模式: {len(seeds)} 种子, {len(templates)} 模板")
    elif args.mode == "short":
        seeds = ALL_SEEDS
        templates = get_short_templates()
        print(f"📌 短文本模式: {len(seeds)} 种子, {len(templates)} 模板")
    elif args.mode == "mix":
        seeds = ALL_SEEDS
        templates = get_all_templates()
        print(f"📌 混合模式: {len(seeds)} 种子, {len(templates)} 模板（{len(get_long_templates())}长 + {len(get_short_templates())}短）")
    else:  # long - 默认模式
        seeds = ALL_SEEDS
        templates = get_long_templates()
        print(f"📌 长文本模式: {len(seeds)} 种子, {len(templates)} 模板")

    # 创建输出目录
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(OUTPUT_DIR, f"train_v3_{args.mode}_{timestamp}.jsonl")
    summary_file = os.path.join(OUTPUT_DIR, f"train_v3_{args.mode}_{timestamp}_summary.json")

    # 加载历史样本（断点续跑）
    all_samples = []
    # 检查目录下已有的同模式文件
    for fname in os.listdir(OUTPUT_DIR):
        if fname.startswith(f"train_v3_{args.mode}_") and fname.endswith(".jsonl"):
            fpath = os.path.join(OUTPUT_DIR, fname)
            with open(fpath, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            all_samples.append(json.loads(line))
                        except:
                            pass
            print(f"断点续跑: 从 {fname} 加载了已有样本", flush=True)
            break

    print(f"当前已有: {len(all_samples):,} 条样本 (目标: {args.target:,})", flush=True)

    # 主循环
    round_num = 0
    prev_count = len(all_samples)
    seeds_pool = seeds[:]
    random.shuffle(seeds_pool)

    while len(all_samples) < args.target:
        round_num += 1
        print(f"\n--- 第 {round_num} 轮 (种子池: {len(seeds_pool)}个) ---", flush=True)

        # 本轮的种子子集
        round_seeds = seeds_pool[:min(10, len(seeds_pool))]

        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futures = {}
            for seed in round_seeds:
                samples_needed = max(10, args.target - len(all_samples))
                per_seed = min(30, max(5, samples_needed // len(round_seeds)))
                future = ex.submit(process_seed_batch, seed, templates, per_seed)
                futures[future] = seed

            for future in as_completed(futures):
                try:
                    new_samples = future.result()
                    all_samples.extend(new_samples)
                except Exception as e:
                    print(f"  线程出错: {e}", flush=True)

        # 去重（精确去重）
        seen = set()
        unique = []
        for s in all_samples:
            # 用 human 指令做 key
            key = s["conversations"][0]["value"]
            if key not in seen:
                seen.add(key)
                unique.append(s)
        all_samples = unique

        # 保存中间结果
        with open(output_file, 'w', encoding='utf-8') as f:
            for s in all_samples:
                f.write(json.dumps(s, ensure_ascii=False) + '\n')

        current = len(all_samples)
        delta = current - prev_count
        prev_count = current
        reached_pct = current / args.target * 100
        print(f"本轮净增: {delta} 条 | 累计: {current:,} 条 ({reached_pct:.1f}%)", flush=True)

        if current >= args.target:
            break

        # 从已生成的样本中提取新种子，增加多样性
        if current > 50 and delta > 0:
            all_titles = set()
            for s in all_samples[-delta:]:
                msg = s["conversations"][0]["value"]
                if "\n" in msg:
                    title = msg.split("\n")[-1].strip()
                elif "：" in msg:
                    title = msg.split("：")[-1].strip()
                else:
                    title = msg[-60:]
                if len(title) > 10:
                    all_titles.add(title)

            # 补充新种子
            if all_titles:
                new_seeds = random.sample(list(all_titles), min(20, len(all_titles)))
                seeds_pool = seeds_pool + new_seeds
                random.shuffle(seeds_pool)
                seeds_pool = seeds_pool[:50]  # 保持种子池大小

    # 完成
    all_samples = all_samples[:args.target]
    with open(output_file, 'w', encoding='utf-8') as f:
        for s in all_samples:
            f.write(json.dumps(s, ensure_ascii=False) + '\n')

    # 生成摘要统计
    task_counts = {}
    type_counts = {"short": 0, "long": 0}
    total_chars = 0
    for s in all_samples:
        meta = s.get("meta", {})
        task = meta.get("task", "unknown")
        task_counts[task] = task_counts.get(task, 0) + 1
        ttype = meta.get("type", "unknown")
        type_counts[ttype] = type_counts.get(ttype, 0) + 1
        for msg in s["conversations"]:
            if msg["from"] == "gpt":
                total_chars += len(msg["value"])

    summary = {
        "mode": args.mode,
        "target": args.target,
        "actual": len(all_samples),
        "total_chars": total_chars,
        "avg_length": round(total_chars / len(all_samples), 1) if all_samples else 0,
        "task_distribution": task_counts,
        "type_distribution": type_counts,
        "output_file": output_file,
    }

    with open(summary_file, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n{'=' * 60}")
    print(f"🎉 完成！")
    print(f"输出文件: {output_file}")
    print(f"摘要文件: {summary_file}")
    print(f"总样本: {len(all_samples):,}")
    print(f"平均长度: {summary['avg_length']} 字符")
    print(f"长文本占比: {type_counts.get('long', 0) / len(all_samples) * 100:.1f}%")
    print(f"短文本占比: {type_counts.get('short', 0) / len(all_samples) * 100:.1f}%")
    print(f"任务类型: {len(task_counts)} 种")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
