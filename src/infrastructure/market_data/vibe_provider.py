"""Vibe Research 数据提供者 - 提供短线情绪和市场榜单数据。

集成策略：
- 作为补充数据源，提供连板股、成交额榜单等短线数据
- 不替换AIIP的决策治理体系，只作为市场温度计
- 数据来源：东财公开榜单（客观数据，非推荐）
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Final
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_WORKSPACE_ROOT = Path(__file__).resolve().parents[4]
_SHARED_PYTHON = _WORKSPACE_ROOT / "shared" / "python"
if str(_SHARED_PYTHON) not in sys.path:
    sys.path.insert(0, str(_SHARED_PYTHON))
from investment_common import load_runtime_env, plain_code, runtime_value  # noqa: E402
from src.infrastructure.market_data.vibe_embedded import (  # noqa: E402
    get_embedded_vibe_service,
)

load_runtime_env(_WORKSPACE_ROOT / "adaptive-investment-intelligence")

# Vibe Research 后端地址由根目录共享配置提供，可用环境变量覆盖。
VIBE_BASE_URL = runtime_value("VIBE_BASE_URL", "http://127.0.0.1:8900")
VIBE_PROVIDER_MODE = runtime_value("VIBE_PROVIDER_MODE", "http").strip().lower()
_EMBEDDED_UNAVAILABLE: Final = object()
_A_SHARE_NEWS_TERMS = (
    "A股", "沪深", "上证", "深证", "证监会", "交易所", "央行", "人民币",
    "半导体", "芯片", "机器人", "新能源", "光伏", "储能", "医药", "消费",
    "汽车", "能源", "银行", "券商", "房地产", "工业", "制造",
)
_A_SHARE_NEWS_INDUSTRIES = {
    "semi", "robot", "auto", "energy", "bio", "consumer", "macro", "tech"
}


class VibeResearchProvider:
    """Vibe Research 数据提供者。"""

    def __init__(self, base_url: str = VIBE_BASE_URL, mode: str = VIBE_PROVIDER_MODE):
        self.base_url = base_url
        self.mode = (mode or "http").strip().lower()
        self._client = httpx.AsyncClient(timeout=10.0)

    def _metadata(self, *, available: bool, error: str = "") -> dict[str, Any]:
        return {
            "provider": "vibe_research",
            "source_url": self.base_url,
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "available": available,
            "error": error,
        }

    @staticmethod
    def _normalize_a_share_code(stock_code: str) -> str:
        """Convert 600000.SH / SZ000001 style symbols to Vibe's six digits."""
        return plain_code(stock_code)

    async def _try_embedded(self, module_name: str, function_name: str, *args, **kwargs):
        """Try the in-process Vibe module; auto mode may fall back to HTTP."""
        if self.mode not in {"embedded", "auto"}:
            return _EMBEDDED_UNAVAILABLE
        try:
            return await get_embedded_vibe_service().call(
                module_name, function_name, *args, **kwargs
            )
        except Exception as exc:  # noqa: BLE001
            if self.mode == "embedded":
                raise
            logger.warning("Embedded Vibe call %s.%s failed; using HTTP: %s", module_name, function_name, exc)
            return _EMBEDDED_UNAVAILABLE

    def _error_result(self, error: Exception, **payload: Any) -> dict[str, Any]:
        return {
            **payload,
            "_meta": self._metadata(available=False, error=str(error)[:200]),
        }

    async def _quote_snapshot(self, normalized_code: str) -> tuple[dict[str, Any], str, str]:
        """Return a real quote for degraded pages without inventing fundamentals."""
        errors: list[str] = []
        try:
            from src.infrastructure.market_data.stock_skill_bridge import (
                fetch_tencent_quotes,
                normalize_stock_code,
            )

            dashboard_code = normalize_stock_code(normalized_code)
            quotes = await fetch_tencent_quotes([dashboard_code], timeout_seconds=3.0)
            quote = quotes.get(dashboard_code) or {}
            if quote:
                return quote, "stock_skill_tencent_live_quote", ""
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Tencent: {str(exc)[:100]}")

        # The local database contains previously synchronized real bars. It is
        # a cache fallback only; callers must label it as non-live.
        try:
            from src.infrastructure.market_data.stock_skill_bridge import normalize_stock_code
            from src.infrastructure.storage.market_database import market_db

            dashboard_code = normalize_stock_code(normalized_code)
            quote = await asyncio.to_thread(market_db.get_latest_quote, dashboard_code) or {}
            if quote:
                return quote, "local_market_database", ""
        except Exception as exc:  # noqa: BLE001
            errors.append(f"local cache: {str(exc)[:100]}")
        return {}, "", "; ".join(errors)

    @staticmethod
    def _proxy_metadata(source: str, warning: str) -> dict[str, Any]:
        return {
            "provider": source,
            "available": True,
            "is_proxy": True,
            "warning": warning,
        }

    async def _fundflow_quote_proxy(self, normalized_code: str) -> dict[str, Any] | None:
        quote, source, _ = await self._quote_snapshot(normalized_code)
        active_ratio = quote.get("active_volume_ratio")
        if active_ratio is None:
            return None
        return {
            "data": {
                "name": quote.get("name") or normalized_code,
                "price": quote.get("price"),
                "change_pct": quote.get("change_pct"),
                "main_net_pct": round(float(active_ratio) * 100, 2),
                "outer_volume_lots": quote.get("outer_volume_lots"),
                "inner_volume_lots": quote.get("inner_volume_lots"),
                "amount_wan": quote.get("amount_wan"),
                "data_date": quote.get("data_date"),
                "proxy_type": "active_trade_ratio",
            },
            "_meta": {
                **self._proxy_metadata(
                    source,
                    "主力资金源不可用；当前展示主动买卖盘差额占比代理指标",
                ),
                "fetched_at": quote.get("fetched_at", ""),
                "source_url": "",
                "error": "",
            },
        }

    @staticmethod
    def _radar_result(radar_data: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
        news_list = []
        for industry in radar_data.get("industries", []):
            for item in industry.get("items", []):
                blob = f"{item.get('title', '')} {item.get('summary', '')}"
                relevance = sum(term.lower() in blob.lower() for term in _A_SHARE_NEWS_TERMS)
                if industry.get("key") in _A_SHARE_NEWS_INDUSTRIES:
                    relevance += 1
                news_list.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "time": item.get("time", ""),
                    "source": item.get("source", ""),
                    "summary": item.get("summary", ""),
                    "industry": industry.get("name", ""),
                    "industry_key": industry.get("key", ""),
                    "published_ts": int(item.get("ts") or 0),
                    "a_share_relevance_score": relevance,
                })
        news_list.sort(
            key=lambda item: (
                int(item.get("a_share_relevance_score") or 0),
                int(item.get("published_ts") or 0),
            ),
            reverse=True,
        )
        result_metadata = {
            **metadata,
            "scope": "industry_macro_radar",
            "ranking": "a_share_relevance_then_recency",
        }
        return {
            "news": news_list[:200],
            "total_count": len(news_list),
            "updated_at": radar_data.get("generated_at", ""),
            "_meta": result_metadata,
        }

    @staticmethod
    def _report_result(raw_reports: list[dict[str, Any]]) -> dict[str, Any]:
        reports = [
            {
                **item,
                "id": item.get("id") or item.get("infoCode", ""),
                "publish_date": item.get("publish_date") or item.get("publishDate", ""),
                "author": item.get("researcher") or item.get("author", ""),
                "institution": item.get("institution") or item.get("orgSName")
                or item.get("orgName", ""),
            }
            for item in raw_reports
        ]
        return {"reports": reports, "count": len(reports)}

    async def close(self):
        """关闭HTTP客户端。"""
        await self._client.aclose()

    async def get_sentiment_lite(self) -> dict[str, Any]:
        """获取短线情绪数据。

        包含：
        - 连板梯队（2板/3板/4板/5+板各多少家）
        - 连板股清单（股票代码/名称/连板数/成交额等）
        - 最高连板数、炸板率、封板率、晋级率
        - 涨跌停家数统计

        Returns:
            dict: 短线情绪数据，失败时返回空字典
        """
        try:
            embedded = await self._try_embedded("market", "get_short_term_emotion")
            if embedded is not _EMBEDDED_UNAVAILABLE:
                return embedded or {}
            resp = await self._client.get(f"{self.base_url}/api/market/emotion")
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", data)
        except Exception as e:
            logger.warning(f"获取短线情绪数据失败: {e}")
            return {}

    async def get_top_volume_stocks(self, limit: int = 20) -> list[dict[str, Any]]:
        """获取成交额TOP榜单。

        Args:
            limit: 返回股票数量，默认20

        Returns:
            list: 成交额TOP股票列表，每项包含：
                - code: 股票代码
                - name: 股票名称
                - price: 现价
                - pct: 涨跌幅
                - amount: 成交额（元）
                - mcap: 总市值（元）
                - float_mcap: 流通市值（元）
                - turnover: 换手率
        """
        try:
            embedded = await self._try_embedded("market", "get_turnover_top")
            if embedded is not _EMBEDDED_UNAVAILABLE:
                return (embedded or {}).get("stocks", [])[:limit]
            resp = await self._client.get(
                f"{self.base_url}/api/market/turnover-top",
                params={"limit": limit}
            )
            resp.raise_for_status()
            data = resp.json()
            return (data.get("data", data) or {}).get("stocks", [])
        except Exception as e:
            logger.warning(f"获取成交额TOP榜单失败: {e}")
            return []

    async def get_news_radar(self) -> dict[str, Any]:
        """获取新闻雷达数据。

        Returns:
            dict: 新闻雷达数据，包含：
                - news: 新闻列表，每项包含标题、时间、来源、URL等
                - updated_at: 更新时间
        """
        try:
            embedded = await self._try_embedded("newsradar", "get_radar", False)
            if embedded is not _EMBEDDED_UNAVAILABLE:
                radar = embedded or {}
                has_items = any(
                    industry.get("items") for industry in radar.get("industries", [])
                )
                return self._radar_result(
                    radar,
                    self._metadata(
                        available=bool(has_items),
                        error="资讯源返回空结果" if not has_items else "",
                    ),
                )
            resp = await self._client.get(f"{self.base_url}/api/radar")
            resp.raise_for_status()
            data = resp.json()
            # Vibe Research返回 {"data": {...}}，需要提取data字段
            radar_data = data.get("data", {})
            return self._radar_result(
                radar_data,
                self._metadata(
                    available=any(
                        industry.get("items") for industry in radar_data.get("industries", [])
                    ),
                    error="资讯源返回空结果" if not any(
                        industry.get("items") for industry in radar_data.get("industries", [])
                    ) else "",
                ),
            )
        except Exception as e:
            logger.warning(f"获取新闻雷达数据失败: {e}")
            return {
                "news": [], "updated_at": "",
                "_meta": self._metadata(available=False, error=str(e)[:200]),
            }

    async def refresh_news_radar(self) -> dict[str, Any]:
        """刷新新闻雷达数据（强制重新抓取）。

        Returns:
            dict: 刷新后的新闻雷达数据
        """
        try:
            embedded = await self._try_embedded("newsradar", "fetch_radar")
            if embedded is not _EMBEDDED_UNAVAILABLE:
                radar = embedded or {}
                has_items = any(
                    industry.get("items") for industry in radar.get("industries", [])
                )
                return self._radar_result(
                    radar,
                    self._metadata(
                        available=bool(has_items),
                        error="资讯源返回空结果" if not has_items else "",
                    ),
                )
            resp = await self._client.post(f"{self.base_url}/api/radar/refresh")
            resp.raise_for_status()
            data = resp.json()
            # Vibe Research返回 {"data": {...}}，需要提取data字段
            radar_data = data.get("data", {})
            return self._radar_result(
                radar_data,
                self._metadata(
                    available=any(
                        industry.get("items") for industry in radar_data.get("industries", [])
                    ),
                    error="资讯源返回空结果" if not any(
                        industry.get("items") for industry in radar_data.get("industries", [])
                    ) else "",
                ),
            )
        except Exception as e:
            logger.warning(f"刷新新闻雷达数据失败: {e}")
            return {
                "news": [], "updated_at": "",
                "_meta": self._metadata(available=False, error=str(e)[:200]),
            }

    async def get_reports(self, stock_code: str) -> dict[str, Any]:
        """获取指定股票的研报列表。

        Args:
            stock_code: 股票代码（如 "000001"）

        Returns:
            dict: 研报数据，包含：
                - reports: 研报列表，每项包含标题、作者、发布时间、研报ID等
                - count: 研报总数
        """
        try:
            normalized_code = self._normalize_a_share_code(stock_code)
            embedded = await self._try_embedded("astock", "eastmoney_reports", normalized_code, max_pages=2)
            if embedded is not _EMBEDDED_UNAVAILABLE:
                rows = embedded or []
                for row in rows:
                    if row.get("infoCode"):
                        row["pdfUrl"] = await get_embedded_vibe_service().call(
                            "astock", "pdf_url", row["infoCode"]
                        )
                return {
                    **self._report_result(rows),
                    "_meta": self._metadata(available=True),
                }
            resp = await self._client.get(
                f"{self.base_url}/api/reports",
                params={"code": normalized_code}
            )
            resp.raise_for_status()
            data = resp.json()
            raw_reports = data.get("reports", data.get("data", []))
            reports = [
                {
                    **item,
                    "id": item.get("id") or item.get("infoCode", ""),
                    "publish_date": item.get("publish_date") or item.get("publishDate", ""),
                    "author": item.get("researcher") or item.get("author", ""),
                    "institution": item.get("institution") or item.get("orgSName")
                    or item.get("orgName", ""),
                }
                for item in raw_reports
            ]
            return {
                "reports": reports,
                "count": len(reports),
                "_meta": self._metadata(available=True),
            }
        except Exception as e:
            logger.warning(f"获取股票 {stock_code} 研报列表失败: {e}")
            return {
                "reports": [], "count": 0,
                "_meta": self._metadata(available=False, error=str(e)[:200]),
            }

    async def get_my_reports(self) -> dict[str, Any]:
        """获取本地收藏的研报列表。

        Returns:
            dict: 收藏的研报数据，包含：
                - reports: 研报列表
                - count: 研报总数
        """
        try:
            embedded = await self._try_embedded("myreports", "list_reports")
            if embedded is not _EMBEDDED_UNAVAILABLE:
                reports = embedded or []
                return {
                    "reports": reports,
                    "count": len(reports),
                    "_meta": self._metadata(available=True),
                }
            resp = await self._client.get(f"{self.base_url}/api/myreports")
            resp.raise_for_status()
            data = resp.json()
            data["_meta"] = self._metadata(available=True)
            return data
        except Exception as e:
            logger.warning(f"获取收藏研报列表失败: {e}")
            return {
                "reports": [], "count": 0,
                "_meta": self._metadata(available=False, error=str(e)[:200]),
            }

    async def save_report(self, report_id: str, stock_code: str, title: str) -> dict[str, Any]:
        """收藏一份研报到本地。

        Args:
            report_id: 研报ID
            stock_code: 股票代码
            title: 研报标题

        Returns:
            dict: 操作结果，包含 success 字段
        """
        try:
            if self.mode == "embedded":
                return {
                    "success": False,
                    "error": "嵌入模式只支持上传本地报告；远程研报收藏请保留 Vibe HTTP 服务。",
                    "_meta": self._metadata(available=False),
                }
            resp = await self._client.post(
                f"{self.base_url}/api/myreports",
                json={"rid": report_id, "code": stock_code, "title": title}
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning(f"收藏研报 {report_id} 失败: {e}")
            return {"success": False, "error": str(e)}

    def get_report_file_url(self, report_id: str) -> str:
        """获取研报PDF文件的下载URL。

        Args:
            report_id: 研报ID

        Returns:
            str: PDF文件的完整URL
        """
        return f"{self.base_url}/api/myreports/file/{report_id}"

    async def get_announcements(self, stock_code: str) -> dict[str, Any]:
        """获取指定股票的公告列表。

        Args:
            stock_code: 股票代码（如 "000001"）

        Returns:
            dict: 公告数据，包含：
                - announcements: 公告列表，每项包含标题、时间、类型等
                - count: 公告总数
        """
        try:
            normalized_code = self._normalize_a_share_code(stock_code)
            embedded = await self._try_embedded("astock", "announcements", normalized_code)
            if embedded is not _EMBEDDED_UNAVAILABLE:
                announcements = [
                    {
                        **item,
                        "publish_date": item.get("publish_date") or item.get("date", ""),
                        "stock_code": item.get("stock_code") or normalized_code,
                    }
                    for item in (embedded or [])
                ]
                return {
                    "announcements": announcements,
                    "count": len(announcements),
                    "_meta": self._metadata(available=True),
                }
            resp = await self._client.get(
                f"{self.base_url}/api/announcements",
                params={"code": normalized_code}
            )
            resp.raise_for_status()
            data = resp.json()
            # Vibe Research返回 {"data": [...]}，需要提取data字段
            announcements = [
                {
                    **item,
                    "publish_date": item.get("publish_date") or item.get("date", ""),
                    "stock_code": item.get("stock_code") or normalized_code,
                }
                for item in data.get("data", [])
            ]
            return {
                "announcements": announcements,
                "count": len(announcements),
                "_meta": self._metadata(available=True),
            }
        except Exception as e:
            logger.warning(f"获取股票 {stock_code} 公告列表失败: {e}")
            return {
                "announcements": [], "count": 0,
                "_meta": self._metadata(available=False, error=str(e)[:200]),
            }

    async def get_latest_announcements(self, limit: int = 50) -> dict[str, Any]:
        """获取最新公告列表（全市场）。

        注意：Vibe Research后端没有"最新公告"接口，此方法返回空数据。
        建议使用 get_announcements(stock_code) 查询特定股票的公告。

        Args:
            limit: 返回公告数量，默认50（未使用）

        Returns:
            dict: 空的公告数据
        """
        # Vibe Research没有全市场最新公告接口，返回空数据
        logger.warning("Vibe Research不支持全市场最新公告查询，请使用股票代码查询")
        return {
            "announcements": [], "updated_at": "",
            "_meta": {
                **self._metadata(available=False),
                "unsupported": True,
                "error": "当前数据源不支持全市场最新公告，请输入股票代码查询",
            },
        }

    async def get_financials(self, stock_code: str) -> dict[str, Any]:
        """获取指定股票的财务数据。

        Args:
            stock_code: 股票代码（如 "000001"）

        Returns:
            dict: 财务数据，包含营收、净利润、EPS、ROE等关键指标
        """
        try:
            normalized_code = self._normalize_a_share_code(stock_code)
            embedded = await self._try_embedded("astock", "financials", normalized_code)
            if embedded is not _EMBEDDED_UNAVAILABLE and embedded:
                return {
                    "data": embedded or {},
                    "_meta": self._metadata(
                        available=bool(embedded),
                        error="财务数据源返回空结果" if not embedded else "",
                    ),
                }
            resp = await self._client.get(
                f"{self.base_url}/api/financials",
                params={"code": normalized_code}
            )
            resp.raise_for_status()
            data = resp.json()
            # Vibe Research返回 {"data": {...}}
            financials = data.get("data", {})
            return {
                "data": financials,
                "_meta": self._metadata(
                    available=bool(financials),
                    error="财务数据源返回空结果" if not financials else "",
                ),
            }
        except Exception as e:
            logger.warning(f"获取股票 {stock_code} 财务数据失败: {e}")
            return {
                "data": {},
                "_meta": self._metadata(available=False, error=str(e)[:200]),
            }

    async def get_valuation(self, stock_code: str) -> dict[str, Any]:
        """获取指定股票的估值数据。

        Args:
            stock_code: 股票代码（如 "000001"）

        Returns:
            dict: 估值数据，包含PE、PB、PS、市值等指标
        """
        try:
            normalized_code = self._normalize_a_share_code(stock_code)
            embedded = await self._try_embedded("astock", "full_valuation", normalized_code)
            if embedded is not _EMBEDDED_UNAVAILABLE and embedded:
                valuation = embedded or {}
                if "pe" not in valuation and "pe_ttm" in valuation:
                    valuation["pe"] = valuation["pe_ttm"]
                if "market_cap" not in valuation and "mcap_yi" in valuation:
                    valuation["market_cap"] = valuation["mcap_yi"] * 100_000_000
                return {
                    "data": valuation,
                    "_meta": self._metadata(
                        available=bool(valuation),
                        error="估值数据源返回空结果" if not valuation else "",
                    ),
                }
            resp = await self._client.get(
                f"{self.base_url}/api/valuation",
                params={"code": normalized_code}
            )
            resp.raise_for_status()
            data = resp.json()
            valuation = data.get("data", {})
            if "pe" not in valuation and "pe_ttm" in valuation:
                valuation["pe"] = valuation["pe_ttm"]
            if "market_cap" not in valuation and "mcap_yi" in valuation:
                valuation["market_cap"] = valuation["mcap_yi"] * 100_000_000
            # Vibe Research返回 {"data": {...}}
            if valuation:
                return {
                    "data": valuation,
                    "_meta": self._metadata(available=True),
                }
            raise RuntimeError("估值数据源返回空结果")
        except Exception as e:
            logger.warning(f"获取股票 {stock_code} 估值数据失败: {e}")
            normalized_code = self._normalize_a_share_code(stock_code)
            quote, source, quote_error = await self._quote_snapshot(normalized_code)
            if quote:
                valuation = {
                    "name": quote.get("name") or normalized_code,
                    "code": normalized_code,
                    "price": quote.get("price"),
                    "change_pct": quote.get("change_pct"),
                    "pe_ttm": quote.get("pe_ttm") or None,
                    "pb": quote.get("pb") or None,
                    "market_cap": (
                        float(quote.get("market_cap_yi") or quote.get("mcap_yi"))
                        * 100_000_000
                        if quote.get("market_cap_yi") or quote.get("mcap_yi")
                        else None
                    ),
                }
                valuation = {key: value for key, value in valuation.items() if value is not None}
                return {
                    "data": valuation,
                    "_meta": {
                        **self._proxy_metadata(
                            source,
                            "完整估值源不可用；当前仅展示行情源提供的估值字段",
                        ),
                        "fetched_at": quote.get("fetched_at", ""),
                        "source_url": "",
                        "error": "",
                    },
                }
            return {
                "data": {},
                "_meta": self._metadata(
                    available=False,
                    error=f"{str(e)[:140]}{'; ' + quote_error if quote_error else ''}",
                ),
            }

    async def get_fundflow(self, stock_code: str) -> dict[str, Any]:
        """获取指定股票的资金流向数据。

        Args:
            stock_code: 股票代码（如 "000001"）

        Returns:
            dict: 资金流向数据，包含主力资金、散户资金等流入流出情况
        """
        try:
            normalized_code = self._normalize_a_share_code(stock_code)
            embedded = await self._try_embedded("astock", "stock_fund_flow_120d", normalized_code)
            if embedded is not _EMBEDDED_UNAVAILABLE:
                history = embedded or []
                latest = history[-1] if history else {}
                fundflow = {
                    **latest,
                    "medium_net": latest.get("medium_net", latest.get("mid_net")),
                    "super_large_net": latest.get("super_large_net", latest.get("super_net")),
                    "history": history,
                } if latest else {}
                if not fundflow:
                    proxy = await self._fundflow_quote_proxy(normalized_code)
                    if proxy:
                        return proxy
                return {
                    "data": fundflow,
                    "_meta": self._metadata(
                        available=bool(fundflow),
                        error="" if fundflow else "资金流数据源返回空结果",
                    ),
                }
            resp = await self._client.get(
                f"{self.base_url}/api/fund-flow",
                params={"code": normalized_code}
            )
            resp.raise_for_status()
            data = resp.json()
            history = data.get("data", [])
            latest = history[-1] if history else {}
            fundflow = {
                **latest,
                "medium_net": latest.get("medium_net", latest.get("mid_net")),
                "super_large_net": latest.get("super_large_net", latest.get("super_net")),
                "history": history,
            } if latest else {}
            # Vibe Research返回 {"data": {...}}
            if fundflow:
                return {
                    "data": fundflow,
                    "_meta": self._metadata(available=True),
                }
            proxy = await self._fundflow_quote_proxy(normalized_code)
            if proxy:
                return proxy
            return {
                "data": {},
                "_meta": self._metadata(available=False, error="资金流数据源返回空结果"),
            }
        except Exception as e:
            logger.warning(f"获取股票 {stock_code} 资金流向数据失败: {e}")
            proxy = await self._fundflow_quote_proxy(self._normalize_a_share_code(stock_code))
            if proxy:
                return proxy
            return {
                "data": {},
                "_meta": self._metadata(available=False, error=str(e)[:200]),
            }

    async def get_dragon_tiger(self, stock_code: str) -> dict[str, Any]:
        """获取指定股票的龙虎榜数据。

        Args:
            stock_code: 股票代码（如 "000001"）

        Returns:
            dict: 龙虎榜数据，包含买入/卖出营业部、上榜原因等
        """
        try:
            normalized_code = self._normalize_a_share_code(stock_code)
            embedded = await self._try_embedded("astock", "dragon_tiger_board", normalized_code)
            if embedded is not _EMBEDDED_UNAVAILABLE:
                result = embedded or {}
                has_records = bool(
                    result.get("records") or
                    (result.get("seats") or {}).get("buy") or
                    (result.get("seats") or {}).get("sell")
                ) if isinstance(result, dict) else bool(result)
                return {
                    "data": result,
                    "_meta": self._metadata(
                        available=has_records,
                        error="最近30日没有龙虎榜记录或数据源返回空结果" if not has_records else "",
                    ),
                }
            resp = await self._client.get(
                f"{self.base_url}/api/dragon-tiger",
                params={"code": normalized_code}
            )
            resp.raise_for_status()
            data = resp.json()
            # Vibe Research返回 {"data": {...}}
            result = data.get("data", {})
            has_records = bool(
                result.get("records") or
                (result.get("seats") or {}).get("buy") or
                (result.get("seats") or {}).get("sell")
            ) if isinstance(result, dict) else bool(result)
            return {
                "data": result,
                "_meta": self._metadata(
                    available=has_records,
                    error="最近30日没有龙虎榜记录或数据源返回空结果" if not has_records else "",
                ),
            }
        except Exception as e:
            logger.warning(f"获取股票 {stock_code} 龙虎榜数据失败: {e}")
            return {
                "data": {},
                "_meta": self._metadata(available=False, error=str(e)[:200]),
            }


# 全局单例
_provider: VibeResearchProvider | None = None


def get_vibe_provider() -> VibeResearchProvider:
    """获取全局Vibe Research提供者实例。"""
    global _provider
    if _provider is None:
        _provider = VibeResearchProvider()
    return _provider
