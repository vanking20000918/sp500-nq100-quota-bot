# -*- coding: utf-8 -*-
"""
A股交易日判断：周一到周五且非法定节假日（含调休补班日也不交易，
因为交易所只在"非节假日的工作日"开市，周末补班日不开市）。

用法：
  python trading_day.py            # 输出 1(交易日) / 0(非交易日)
  代码中: from trading_day import is_trading_day
"""

import datetime


def is_trading_day(date: datetime.date | None = None) -> bool:
    date = date or datetime.date.today()
    if date.weekday() >= 5:          # 周末从不开市（即使是调休补班日）
        return False
    try:
        import chinese_calendar
        return not chinese_calendar.is_holiday(date)
    except Exception:
        # 包缺失或年份数据未更新时退化为"工作日即交易日"
        return True


if __name__ == "__main__":
    print(1 if is_trading_day() else 0)
