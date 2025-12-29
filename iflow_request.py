import json
import requests
import schedule
import time
from datetime import datetime, timedelta
from plyer import notification
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.patches as mpatches

# ==================== 核心配置区 ====================
TARGET_URL = "https://api.iflow.work/steam/analysisData"

BUY_CONDITIONS = {
    'week_rank_target': 1, 
    'month_quantile_target': 0.10, 
    'quarter_quantile_target': 0.15, 
    'year_quantile_target': 0.20 
}

SEASONAL_DROP_THRESHOLD = 0.02

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ...",
    "Referer": "https://www.iflow.work/"
}

# --- 新增：Steam 历年大促时间表 (需手动维护，但这比爬虫稳定得多) ---
# 格式：(开始日期, 结束日期, 标签, 颜色)
SALE_CALENDAR = [
    # --- 2023年 (历史实录) ---
    ("2023-03-16", "2023-03-23", "23春促", "#98FB98"), 
    ("2023-06-29", "2023-07-13", "23夏促", "#FF6347"), 
    ("2023-11-21", "2023-11-28", "23秋促", "#FFA500"), 
    ("2023-12-21", "2024-01-04", "23冬促", "#87CEFA"), 

    # --- 2024年 (历史实录) ---
    ("2024-03-14", "2024-03-21", "24春促", "#98FB98"),
    ("2024-06-27", "2024-07-11", "24夏促", "#FF6347"),
    ("2024-11-27", "2024-12-04", "24秋促", "#FFA500"),
    ("2024-12-19", "2025-01-02", "24冬促", "#87CEFA"),

    # --- 2025年 (根据官方公告与日历推算补全) ---
    ("2025-03-13", "2025-03-20", "25春促", "#98FB98"), # 官方已公布
    ("2025-06-26", "2025-07-10", "25夏促", "#FF6347"), # 基于6月最后一个周四推算
    ("2025-09-28", "2025-10-05", "25秋促", "#FFA500"), # 基于黑色星期五推算
    ("2025-12-18", "2026-01-05", "25冬促", "#87CEFA"), # 基于圣诞节推算 (当前正在进行)
]

# ==================== 可视化逻辑优化 ====================

def plot_sale_zones(ax, start_date_obj, end_date_obj):
    """
    在给定的坐标轴 ax 上，绘制处于 start_date 和 end_date 之间的促销背景带
    """
    # 获取当前X轴的范围，避免绘制超出图表范围的促销
    xlim = ax.get_xlim()
    # 将matplotlib的float型日期转回datetime以便比较（如果需要更严谨的判断）
    
    added_labels = set() # 防止重复添加图例

    for s_str, e_str, label, color in SALE_CALENDAR:
        s_date = datetime.strptime(s_str, "%Y-%m-%d")
        e_date = datetime.strptime(e_str, "%Y-%m-%d")

        # 简单的重叠检测：如果 (促销结束 > 视图开始) 且 (促销开始 < 视图结束)
        if e_date >= start_date_obj and s_date <= end_date_obj:
            # 绘制半透明矩形区域
            ax.axvspan(s_date, e_date, color=color, alpha=0.2, zorder=0)
            
            # 在区域上方标注文字 (可选)
            # 计算区域中间位置
            mid_point = s_date + (e_date - s_date) / 2
            # 仅当中间点在视图范围内才标注，避免文字乱飞
            if start_date_obj <= mid_point <= end_date_obj:
                ylim = ax.get_ylim()
                ax.text(mid_point, ylim[1], label, ha='center', va='bottom', fontsize=8, color=color, rotation=0)

def visualize_market(n10_data):
    """
    生成市场趋势可视化图表 (含大促标注版)
    """
    if not n10_data:
        print("无数据可供绘图")
        return

    # 准备绘图数据
    dates = [datetime.strptime(x['date'], "%Y-%m-%d") for x in n10_data]
    values = [x['value'] for x in n10_data]
    latest_date = dates[-1]

    plt.style.use('seaborn-v0_8-whitegrid') # 使用更现代的网格风格

    # 设置中文及样式
    plt.rcParams['font.sans-serif'] = ['SimHei'] 
    plt.rcParams['axes.unicode_minus'] = False
    
    fig, axes = plt.subplots(2, 2, figsize=(16, 10))
    plt.subplots_adjust(hspace=0.35, wspace=0.2, top=0.92)
    fig.suptitle(f"Steam 挂刀指数分析 - 数据截至 {latest_date.strftime('%Y-%m-%d')}", fontsize=18, fontweight='bold')

    # 定义子图逻辑
    def plot_trend(ax, x_data, y_data, title, date_fmt):
        ax.plot(x_data, y_data, marker='o' if len(x_data)<15 else None, color='#1f77b4', linewidth=2, label='挂刀比例')
        ax.set_title(title, fontsize=12, fontweight='bold')
        ax.xaxis.set_major_formatter(mdates.DateFormatter(date_fmt))
        
        # === 核心修改：调用促销绘制函数 ===
        if len(x_data) > 0:
            plot_sale_zones(ax, x_data[0], x_data[-1])
        # ===============================

    # 1. 周线
    plot_trend(axes[0, 0], dates[-7:], values[-7:], "周趋势 (7 Days)", '%m-%d')

    # 2. 月线
    plot_trend(axes[0, 1], dates[-30:], values[-30:], "月趋势 (30 Days)", '%m-%d')

    # 3. 季度线
    plot_trend(axes[1, 0], dates[-90:], values[-90:], "季度趋势 (90 Days)", '%Y-%m')

    # 4. 历史同期月线 (逻辑稍微复杂，暂不加背景带，因为是多不同年份叠加)
    curr_month = latest_date.month
    colors = ['#d62728', '#9467bd', '#8c564b']
    found_any = False
    
    for i, year_offset in enumerate([0, 1, 2]):
        target_year = latest_date.year - year_offset
        month_points = [
            (d, v) for d, v in zip(dates, values) 
            if d.year == target_year and d.month == curr_month
        ]
        if month_points:
            found_any = True
            # 这里为了对齐X轴，把日期统一替换成 "2000年" (闰年兼容性好) 来绘图，只显示日
            plot_dates = [p[0].replace(year=2000) for p in month_points]
            vals = [p[1] for p in month_points]
            axes[1, 1].plot(plot_dates, vals, label=f"{target_year}年", color=colors[i], linewidth=2)

    if found_any:
        axes[1, 1].set_title(f"历史同期对比 ({curr_month}月)")
        axes[1, 1].xaxis.set_major_formatter(mdates.DateFormatter('%d'))
        axes[1, 1].set_xlabel("日期 (Day)")
        axes[1, 1].legend()
    else:
        axes[1, 1].set_title("历史同期对比 (暂无数据)")

    # 增加一个图例说明颜色含义
    patches = [
        mpatches.Patch(color='#FF6347', alpha=0.3, label='夏促'),
        mpatches.Patch(color='#87CEFA', alpha=0.3, label='冬促'),
        mpatches.Patch(color='#FFA500', alpha=0.3, label='秋促'),
        mpatches.Patch(color='#98FB98', alpha=0.3, label='春促'),
    ]
    fig.legend(handles=patches, loc='upper right', bbox_to_anchor=(0.95, 0.97), ncol=4, fontsize=9)

    # 保存
    file_name = f"D:/code/iflow_request/analysis_pic/market_analysis_{latest_date.strftime('%Y%m%d')}.png"
    plt.savefig(file_name, dpi=120) # 稍微提高dpi
    print(f"√ 趋势分析图已生成 (含大促标记): {file_name}")


# ==================== 逻辑实现 ====================

def get_market_position(current_val, history_values):
    if not history_values:
        return 1, 0.0
    all_values = history_values + [current_val]
    all_values.sort()
    rank_index = all_values.index(current_val)
    rank = rank_index + 1
    cheaper_count = sum(1 for v in history_values if v < current_val)
    quantile = cheaper_count / len(history_values)
    return rank, quantile

def check_market(is_manual=False):
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 正在扫描市场...")
    
    try:
        resp = requests.get(TARGET_URL, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            print(f"接口报错: {resp.status_code}")
            return

        raw_data = resp.json()
        
        # 备份数据
        with open("steam_market_history.json", 'w', encoding='utf-8') as f:
            json.dump(raw_data, f, ensure_ascii=False, indent=4)
        
        # 数据清洗
        n10_data = sorted(
            [item for item in raw_data if item.get('type') == '10%'], 
            key=lambda x: x['date']
        )
        
        if not n10_data:
            print("数据源为空")
            return

        latest = n10_data[-1]
        curr_val = latest['value']
        curr_date = datetime.strptime(latest['date'], "%Y-%m-%d")
        
        print(f"数据日期: {latest['date']} | 当前指数: {curr_val:.4f}")

        # 1. 可视化分析 (单次手动执行或特定时间点触发)
        if is_manual:
            visualize_market(n10_data)

        # 2. 周期回溯分析
        periods = {
            '周': {'days': 7, 'key': 'week_rank_target', 'mode': 'rank'},
            '月': {'days': 30, 'key': 'month_quantile_target', 'mode': 'quantile'},
            '季': {'days': 90, 'key': 'quarter_quantile_target', 'mode': 'quantile'},
            '年': {'days': 365, 'key': 'year_quantile_target', 'mode': 'quantile'}
        }
        
        report_msgs = []
        for name, conf in periods.items():
            start_dt = curr_date - timedelta(days=conf['days'])
            hist_vals = [
                x['value'] for x in n10_data 
                if start_dt <= datetime.strptime(x['date'], "%Y-%m-%d") < curr_date
            ]
            
            if not hist_vals: continue
            
            real_rank, real_quantile = get_market_position(curr_val, hist_vals)
            target = BUY_CONDITIONS.get(conf['key'])

            is_hit = False
            status_text = ""
            if conf['mode'] == 'rank':
                if real_rank <= target: is_hit = True
                status_text = f"近{name}排名: 第{real_rank}低"
            else:
                if real_quantile <= target: is_hit = True
                status_text = f"近{name}位置: 底部 {real_quantile*100:.1f}%"
            
            print(f"  - {status_text}")
            if is_hit:
                report_msgs.append(f"★ 触发{name}度好价 ({status_text})")

        # 3. 季节性检测
        seasonal_msg = check_seasonal(n10_data, curr_date)
        
        # 4. 汇总发送
        if report_msgs:
            final_msg = f"💰 发现好价！指数 {curr_val:.4f}\n" + "\n".join(report_msgs)
            if seasonal_msg: final_msg += f"\n\n{seasonal_msg}"
            notification.notify(title='Steam 挂刀行情提醒', message=final_msg, timeout=20)
            print(">>> 已发送提醒弹窗")
        elif seasonal_msg:
            print(">>> 虽无好价，但有历史预警")
            notification.notify(title='Steam 历史预警', message=seasonal_msg, timeout=15)

    except Exception as e:
        print(f"出错: {e}")

def check_seasonal(all_data, curr_date):
    drops = []
    date_val_map = {x['date']: x['value'] for x in all_data}
    for year_back in [1, 2, 3]:
        try:
            past_start = curr_date.replace(year=curr_date.year - year_back)
            past_end = past_start + timedelta(days=7)
            s_str = past_start.strftime("%Y-%m-%d")
            e_str = past_end.strftime("%Y-%m-%d")
            if s_str in date_val_map and e_str in date_val_map:
                change = (date_val_map[s_str] - date_val_map[e_str]) / date_val_map[s_str]
                drops.append(change)
        except: pass
    if drops:
        avg_drop = sum(drops) / len(drops)
        if avg_drop > SEASONAL_DROP_THRESHOLD:
            return f"⚠️ 历史预警: 过去{len(drops)}年同期，未来一周平均下跌 {avg_drop*100:.1f}%"
    return None

if __name__ == "__main__":
    print("--- Steam 挂刀监控 V3.1 (图表版) ---")
    
    # 立即执行一次并进行可视化
    check_market(is_manual=True)
    print("--- 任务完成，脚本自动退出 ---")
    
    # # 设定计划任务
    # schedule.every().day.at("10:15").do(check_market)
    # schedule.every().day.at("22:15").do(check_market)
    
    # while True:
    #     schedule.run_pending()
    #     time.sleep(60)