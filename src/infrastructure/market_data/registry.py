"""Data Source Registry — v7.4. Structured catalog of all data sources.

7 layers, 30+ sources. Each source has explicit:
  - trust tier (official > commercial > community)
  - update frequency
  - access method
  - rate limits
  - what the AI can use it for

This registry is consumed by:
  - Data Feed architecture (which source for which data)
  - AI Evidence chain ("来源: 巨潮资讯")
  - Data Trust scoring (official sources get higher base trust)
  - Frontend data status display
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TrustTier(str, Enum):
    OFFICIAL = "official"       # Government/exchange — highest trust
    DISCLOSURE = "disclosure"   # Official company filings
    COMMERCIAL = "commercial"   # Licensed commercial data
    COMMUNITY = "community"     # Open-source community maintained
    NEWS = "news"               # News media — variable trust
    COMPANY = "company"         # Company self-published


class AccessMethod(str, Enum):
    API = "api"
    WEB_SCRAPE = "web_scrape"
    FILE_DOWNLOAD = "file_download"
    SDK = "sdk"
    RSS = "rss"


@dataclass
class DataSource:
    """A single data source in the registry."""
    id: str = ""                       # Machine-readable: "sse_official"
    name: str = ""                     # Human-readable: "上海证券交易所"
    name_en: str = ""                  # "Shanghai Stock Exchange"
    url: str = ""
    layer: str = ""                    # market / exchange / disclosure / news / macro / industry / company
    tier: TrustTier = TrustTier.COMMUNITY
    access: AccessMethod = AccessMethod.API
    category: str = ""                 # quote / kline / financial / news / macro / announcement
    provides: list[str] = field(default_factory=list)  # Key data fields
    update_frequency: str = ""         # realtime / daily / weekly / monthly / adhoc
    rate_limit: str = ""               # "unlimited" / "25/day" / "60/min"
    requires_auth: bool = False
    requires_vpn: bool = False         # For GFW-blocked sources
    is_free: bool = True
    language: str = "zh"               # zh / en / bilingual
    base_trust: float = 0.7            # Starting trust before validation
    integration_status: str = "planned"  # active / planned / deprecated
    notes: str = ""


# ================================================================
# The Complete Registry — 7 Layers, 30+ Sources
# ================================================================

DATA_SOURCE_REGISTRY: dict[str, DataSource] = {
    # ═══════════════════════════════════════════
    # LAYER 1: Exchange Data (★★★★★)
    # ═══════════════════════════════════════════
    "sse_official": DataSource(
        id="sse_official", name="上海证券交易所", name_en="Shanghai Stock Exchange",
        url="https://www.sse.com.cn", layer="exchange", tier=TrustTier.OFFICIAL,
        access=AccessMethod.WEB_SCRAPE, category="announcement",
        provides=["公告", "上市规则", "财报", "ETF列表", "指数成分"],
        update_frequency="daily", rate_limit="unlimited",
        is_free=True, base_trust=0.98,
        integration_status="planned",
        notes="A股最权威的官方数据来源。AI证据链首选标注来源。",
    ),
    "szse_official": DataSource(
        id="szse_official", name="深圳证券交易所", name_en="Shenzhen Stock Exchange",
        url="https://www.szse.cn", layer="exchange", tier=TrustTier.OFFICIAL,
        access=AccessMethod.WEB_SCRAPE, category="announcement",
        provides=["公告", "互动易问答", "财务数据", "创业板数据"],
        update_frequency="daily", rate_limit="unlimited",
        is_free=True, base_trust=0.98,
        integration_status="planned",
        notes="深市官方公告+互动易投资者问答平台。",
    ),
    "bse_official": DataSource(
        id="bse_official", name="北京证券交易所", name_en="Beijing Stock Exchange",
        url="https://www.bse.cn", layer="exchange", tier=TrustTier.OFFICIAL,
        access=AccessMethod.WEB_SCRAPE, category="announcement",
        provides=["公告", "北交所上市公司数据"],
        update_frequency="daily", rate_limit="unlimited",
        is_free=True, base_trust=0.98,
        integration_status="planned",
    ),

    # ═══════════════════════════════════════════
    # LAYER 2: Disclosure / Filings (★★★★★)
    # ═══════════════════════════════════════════
    "cninfo": DataSource(
        id="cninfo", name="巨潮资讯网", name_en="CNINFO",
        url="https://www.cninfo.com.cn", layer="disclosure", tier=TrustTier.DISCLOSURE,
        access=AccessMethod.WEB_SCRAPE, category="announcement",
        provides=["年报", "半年报", "季报", "临时公告", "分红", "回购", "股东减持", "定增"],
        update_frequency="daily", rate_limit="unlimited",
        is_free=True, base_trust=0.97,
        integration_status="planned",
        notes="证监会指定信息披露平台。所有上市公司公告最全来源。",
    ),
    "csrc": DataSource(
        id="csrc", name="中国证监会", name_en="CSRC",
        url="https://www.csrc.gov.cn", layer="disclosure", tier=TrustTier.OFFICIAL,
        access=AccessMethod.WEB_SCRAPE, category="announcement",
        provides=["监管政策", "处罚决定", "IPO审核", "法规"],
        update_frequency="daily", rate_limit="unlimited",
        is_free=True, base_trust=0.99,
        integration_status="planned",
    ),
    "sec_edgar": DataSource(
        id="sec_edgar", name="SEC EDGAR", name_en="SEC EDGAR",
        url="https://www.sec.gov/edgar", layer="disclosure", tier=TrustTier.OFFICIAL,
        access=AccessMethod.API, category="announcement",
        provides=["10-K", "10-Q", "8-K", "13F", "Proxy"],
        update_frequency="daily", rate_limit="10/sec",
        is_free=True, base_trust=0.99, language="en",
        integration_status="planned",
        notes="美股最权威财报+公告来源。",
    ),

    # ═══════════════════════════════════════════
    # LAYER 3: Market Data (★★★★★)
    # ═══════════════════════════════════════════
    "akshare": DataSource(
        id="akshare", name="东方财富 (AkShare)", name_en="AkShare",
        url="https://github.com/akfamily/akshare", layer="market", tier=TrustTier.COMMUNITY,
        access=AccessMethod.SDK, category="quote",
        provides=["日K", "实时行情", "指数", "板块", "龙虎榜", "北向资金", "财务数据"],
        update_frequency="realtime", rate_limit="取决于东方财富API限制",
        is_free=True, base_trust=0.85,
        integration_status="active",
        notes="国内个人量化最常用的开源工具。数据来源于东方财富。",
    ),
    "tushare": DataSource(
        id="tushare", name="Tushare Pro", name_en="Tushare",
        url="https://tushare.pro", layer="market", tier=TrustTier.COMMUNITY,
        access=AccessMethod.SDK, category="quote",
        provides=["日K", "分钟K", "财务数据", "指数", "基金", "期货"],
        update_frequency="realtime", rate_limit="积分制，基础免费",
        is_free=True, requires_auth=True, base_trust=0.88,
        integration_status="planned",
        notes="需要注册获取token。积分制限制部分高级接口。",
    ),
    "baostock": DataSource(
        id="baostock", name="BaoStock", name_en="BaoStock",
        url="http://baostock.com", layer="market", tier=TrustTier.COMMUNITY,
        access=AccessMethod.SDK, category="quote",
        provides=["日K", "分钟线", "财务数据"],
        update_frequency="daily", rate_limit="unlimited",
        is_free=True, base_trust=0.82,
        integration_status="planned",
        notes="纯免费，无积分限制。更新频率不如AkShare。适合作为备份源。",
    ),
    "yahoo_finance": DataSource(
        id="yahoo_finance", name="Yahoo Finance", name_en="Yahoo Finance",
        url="https://finance.yahoo.com", layer="market", tier=TrustTier.COMMERCIAL,
        access=AccessMethod.API, category="quote",
        provides=["美股行情", "港股行情", "ETF", "历史K线"],
        update_frequency="realtime", rate_limit="免费额度有限",
        is_free=True, base_trust=0.82, language="en",
        integration_status="planned",
    ),
    "stooq": DataSource(
        id="stooq", name="Stooq", name_en="Stooq",
        url="https://stooq.com", layer="market", tier=TrustTier.COMMUNITY,
        access=AccessMethod.API, category="quote",
        provides=["全球历史行情"],
        update_frequency="daily", rate_limit="unlimited",
        is_free=True, base_trust=0.78, language="en",
        integration_status="planned",
    ),

    # ═══════════════════════════════════════════
    # LAYER 4: Macroeconomic (★★★★★)
    # ═══════════════════════════════════════════
    "nbs": DataSource(
        id="nbs", name="国家统计局", name_en="National Bureau of Statistics",
        url="https://www.stats.gov.cn", layer="macro", tier=TrustTier.OFFICIAL,
        access=AccessMethod.WEB_SCRAPE, category="macro",
        provides=["GDP", "CPI", "PPI", "PMI", "工业增加值", "社会消费品零售总额"],
        update_frequency="monthly", rate_limit="unlimited",
        is_free=True, base_trust=0.99,
        integration_status="planned",
        notes="中国宏观经济最权威数据。",
    ),
    "pbc": DataSource(
        id="pbc", name="中国人民银行", name_en="People's Bank of China",
        url="https://www.pbc.gov.cn", layer="macro", tier=TrustTier.OFFICIAL,
        access=AccessMethod.WEB_SCRAPE, category="macro",
        provides=["利率", "LPR", "存款准备金率", "货币政策报告", "金融统计数据"],
        update_frequency="monthly", rate_limit="unlimited",
        is_free=True, base_trust=0.99,
        integration_status="planned",
    ),
    "safe": DataSource(
        id="safe", name="国家外汇管理局", name_en="SAFE",
        url="https://www.safe.gov.cn", layer="macro", tier=TrustTier.OFFICIAL,
        access=AccessMethod.WEB_SCRAPE, category="macro",
        provides=["外汇储备", "汇率", "国际收支"],
        update_frequency="monthly", rate_limit="unlimited",
        is_free=True, base_trust=0.99,
        integration_status="planned",
    ),
    "mof": DataSource(
        id="mof", name="财政部", name_en="Ministry of Finance",
        url="https://www.mof.gov.cn", layer="macro", tier=TrustTier.OFFICIAL,
        access=AccessMethod.WEB_SCRAPE, category="macro",
        provides=["财政收支", "税收政策", "国债发行"],
        update_frequency="monthly", rate_limit="unlimited",
        is_free=True, base_trust=0.99,
        integration_status="planned",
    ),
    "fred": DataSource(
        id="fred", name="FRED", name_en="Federal Reserve Economic Data",
        url="https://fred.stlouisfed.org", layer="macro", tier=TrustTier.OFFICIAL,
        access=AccessMethod.API, category="macro",
        provides=["美国GDP", "CPI", "失业率", "利率", "汇率"],
        update_frequency="daily", rate_limit="120/min",
        is_free=True, base_trust=0.99, language="en",
        integration_status="planned",
    ),
    "federal_reserve": DataSource(
        id="federal_reserve", name="Federal Reserve", name_en="Federal Reserve",
        url="https://www.federalreserve.gov", layer="macro", tier=TrustTier.OFFICIAL,
        access=AccessMethod.WEB_SCRAPE, category="macro",
        provides=["FOMC声明", "利率决议", "经济预测"],
        update_frequency="adhoc", rate_limit="unlimited",
        is_free=True, base_trust=0.99, language="en",
        integration_status="planned",
    ),

    # ═══════════════════════════════════════════
    # LAYER 5: Industry Policy (★★★★★)
    # ═══════════════════════════════════════════
    "miit": DataSource(
        id="miit", name="工业和信息化部", name_en="MIIT",
        url="https://www.miit.gov.cn", layer="industry", tier=TrustTier.OFFICIAL,
        access=AccessMethod.WEB_SCRAPE, category="policy",
        provides=["产业政策", "行业准入", "技术标准", "半导体/机器人/新能源政策"],
        update_frequency="adhoc", rate_limit="unlimited",
        is_free=True, base_trust=0.98,
        integration_status="planned",
        notes="科技、半导体、机器人、通信等行业的政策源头。",
    ),
    "nea": DataSource(
        id="nea", name="国家能源局", name_en="National Energy Administration",
        url="https://www.nea.gov.cn", layer="industry", tier=TrustTier.OFFICIAL,
        access=AccessMethod.WEB_SCRAPE, category="policy",
        provides=["新能源政策", "光伏", "风电", "储能", "电力数据"],
        update_frequency="adhoc", rate_limit="unlimited",
        is_free=True, base_trust=0.98,
        integration_status="planned",
    ),
    "ndrc": DataSource(
        id="ndrc", name="国家发改委", name_en="NDRC",
        url="https://www.ndrc.gov.cn", layer="industry", tier=TrustTier.OFFICIAL,
        access=AccessMethod.WEB_SCRAPE, category="policy",
        provides=["产业规划", "价格政策", "重大项目审批"],
        update_frequency="adhoc", rate_limit="unlimited",
        is_free=True, base_trust=0.98,
        integration_status="planned",
    ),
    "nhsa": DataSource(
        id="nhsa", name="国家医保局", name_en="NHSA",
        url="https://www.nhsa.gov.cn", layer="industry", tier=TrustTier.OFFICIAL,
        access=AccessMethod.WEB_SCRAPE, category="policy",
        provides=["医保目录", "药品集采", "医疗政策"],
        update_frequency="adhoc", rate_limit="unlimited",
        is_free=True, base_trust=0.98,
        integration_status="planned",
        notes="医药行业最核心的政策来源。",
    ),
    "nmpa": DataSource(
        id="nmpa", name="国家药监局", name_en="NMPA",
        url="https://www.nmpa.gov.cn", layer="industry", tier=TrustTier.OFFICIAL,
        access=AccessMethod.WEB_SCRAPE, category="policy",
        provides=["药品审批", "医疗器械注册", "监管政策"],
        update_frequency="adhoc", rate_limit="unlimited",
        is_free=True, base_trust=0.98,
        integration_status="planned",
    ),

    # ═══════════════════════════════════════════
    # LAYER 6: News (★★★★☆)
    # ═══════════════════════════════════════════
    "xinhua": DataSource(
        id="xinhua", name="新华社", name_en="Xinhua News Agency",
        url="https://www.news.cn", layer="news", tier=TrustTier.NEWS,
        access=AccessMethod.WEB_SCRAPE, category="news",
        provides=["政策新闻", "经济新闻", "国际新闻"],
        update_frequency="realtime", rate_limit="unlimited",
        is_free=True, base_trust=0.85,
        integration_status="planned",
        notes="国家级通讯社。AI可自动摘要+情绪分析。",
    ),
    "cs_com_cn": DataSource(
        id="cs_com_cn", name="中国证券报", name_en="China Securities Journal",
        url="https://www.cs.com.cn", layer="news", tier=TrustTier.NEWS,
        access=AccessMethod.WEB_SCRAPE, category="news",
        provides=["证券市场新闻", "公司报道", "政策解读"],
        update_frequency="daily", rate_limit="unlimited",
        is_free=True, base_trust=0.82,
        integration_status="planned",
    ),
    "cnstock": DataSource(
        id="cnstock", name="上海证券报", name_en="Shanghai Securities News",
        url="https://www.cnstock.com", layer="news", tier=TrustTier.NEWS,
        access=AccessMethod.WEB_SCRAPE, category="news",
        provides=["资本市场新闻", "上市公司报道"],
        update_frequency="daily", rate_limit="unlimited",
        is_free=True, base_trust=0.82,
        integration_status="planned",
    ),
    "stcn": DataSource(
        id="stcn", name="证券时报", name_en="Securities Times",
        url="https://www.stcn.com", layer="news", tier=TrustTier.NEWS,
        access=AccessMethod.WEB_SCRAPE, category="news",
        provides=["财经新闻", "市场分析"],
        update_frequency="daily", rate_limit="unlimited",
        is_free=True, base_trust=0.82,
        integration_status="planned",
    ),
    "yicai": DataSource(
        id="yicai", name="第一财经", name_en="Yicai",
        url="https://www.yicai.com", layer="news", tier=TrustTier.NEWS,
        access=AccessMethod.WEB_SCRAPE, category="news",
        provides=["财经新闻", "深度报道", "视频访谈"],
        update_frequency="realtime", rate_limit="unlimited",
        is_free=True, base_trust=0.80,
        integration_status="planned",
    ),
    "reuters": DataSource(
        id="reuters", name="Reuters", name_en="Reuters",
        url="https://www.reuters.com", layer="news", tier=TrustTier.NEWS,
        access=AccessMethod.API, category="news",
        provides=["国际财经新闻", "市场快讯"],
        update_frequency="realtime", rate_limit="商业API",
        is_free=True, base_trust=0.88, language="en",
        integration_status="planned",
    ),

    # ═══════════════════════════════════════════
    # LAYER 7: Company (★★★★★)
    # ═══════════════════════════════════════════
    "company_ir": DataSource(
        id="company_ir", name="上市公司投资者关系", name_en="Company IR",
        url="", layer="company", tier=TrustTier.COMPANY,
        access=AccessMethod.WEB_SCRAPE, category="announcement",
        provides=["投资者关系", "新闻中心", "产品发布", "ESG报告", "招聘信息"],
        update_frequency="adhoc", rate_limit="unlimited",
        is_free=True, base_trust=0.75,
        integration_status="planned",
        notes="需为每家公司配置官网IR页面URL。招聘扩产=利好信号。",
    ),
}


# ================================================================
# Query helpers
# ================================================================

def get_sources_by_layer(layer: str) -> list[DataSource]:
    """Get all sources for a given data layer."""
    return [s for s in DATA_SOURCE_REGISTRY.values() if s.layer == layer]

def get_sources_by_tier(tier: TrustTier) -> list[DataSource]:
    """Get all sources at a given trust tier."""
    return [s for s in DATA_SOURCE_REGISTRY.values() if s.tier == tier]

def get_active_sources() -> list[DataSource]:
    """Get all actively integrated sources."""
    return [s for s in DATA_SOURCE_REGISTRY.values() if s.integration_status == "active"]

def get_source_summary() -> dict:
    """Summary of the entire registry for display."""
    layers = {}
    for s in DATA_SOURCE_REGISTRY.values():
        if s.layer not in layers:
            layers[s.layer] = {"count": 0, "active_count": 0, "sources": []}
        layers[s.layer]["count"] += 1
        if s.integration_status == "active":
            layers[s.layer]["active_count"] += 1
        layers[s.layer]["sources"].append({
            "id": s.id, "name": s.name, "tier": s.tier.value,
            "status": s.integration_status, "base_trust": s.base_trust,
            "provides": s.provides[:5],
        })

    return {
        "total_sources": len(DATA_SOURCE_REGISTRY),
        "active_sources": len(get_active_sources()),
        "layers": layers,
    }
