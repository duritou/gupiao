"""交易日验证脚本 —— 验证 iFind 实时接入是否真正打通。

用法(项目根目录):
    poetry run python verify_trading_day.py

何时跑:A 股交易日开盘后(9:30-15:00)。
非交易日(周末/假日 / 收盘后)① 实时 quote 会返回 None(无盘中数据),属正常;
交易日开盘后 ①② 应出真实数据。
"""

import asyncio

from src.infrastructure.market_data.ifind_provider import IFindProvider
from src.infrastructure.market_data.source_manager import source_manager


def main():
    print("=== iFind 实时接入验证 ===\n")

    # ① iFind 实时 quote
    q = IFindProvider().get_quote("600000.SH")
    print("[1] ifind get_quote('600000.SH'):")
    if q and q.price:
        print(f"    [OK] price={q.price} open={q.open} high={q.high} "
              f"low={q.low} chg%={q.change_pct} amount={q.amount}")
    else:
        print(f"    [NONE] 无盘中数据(q={q})")
        print("    -> 非交易日/收盘后正常;交易日 9:30 后此处应有值")

    # ② source_manager 实时链路是否命中 ifind
    q2, prov = asyncio.run(source_manager.get_realtime_quote("600000.SH"))
    provider = prov.provider
    price = (q2 or {}).get("price") if q2 else None
    print("\n[2] source_manager.get_realtime_quote('600000.SH'):")
    if provider == "ifind":
        print(f"    [OK] 命中 ifind (provider=ifind, is_live={prov.is_live}, price={price})")
    else:
        print(f"    [FALLBACK] provider={provider} (未命中 ifind, is_live={prov.is_live}, price={price})")
        if prov.error_message:
            print(f"      err: {prov.error_message}")

    # ③ kline 确认(交易日/非交易日都应有历史)
    k = IFindProvider().get_kline("600000.SH", count=3)
    print("\n[3] ifind get_kline('600000.SH', count=3):")
    if k:
        last = k[-1]
        print(f"    [OK] {len(k)} 根,最新 {last['date']} close={last['close']}")
    else:
        print("    [NONE] 无数据")

    print("\n=== 判读 ===")
    if provider == "ifind" and q and q.price:
        print("iFind 实时接入完全打通:可提交 git。")
    elif (q and q.price) or provider == "ifind":
        print("部分通:贴输出给我排查。")
    else:
        print("实时未命中 ifind(非交易日属正常)。交易日开盘后再跑一次。")


if __name__ == "__main__":
    main()
