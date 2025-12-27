import json
import requests
import schedule
import time
from datetime import datetime, timedelta
from plyer import notification
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.iflow.work/"
}

# ==================== 新增：可视化逻辑 ====================

def visualize_market(n10_data):
    """
    生成市场趋势可视化图表
    """
    if not n10_data:
        print("无数据可供绘图")
        return

    # 准备绘图数据
    dates = [datetime.strptime(x['date'], "%Y-%m-%d") for x in n10_data]
    values = [x['value'] for x in n10_data]
    latest_date = dates[-1]

    # 设置中文显示（如果环境支持，否则使用默认）
    plt.rcParams['font.sans-serif'] = ['SimHei'] # Windows常用
    plt.rcParams['axes.unicode_minus'] = False

    fig, axes = plt.subplots(2, 2, figsize=(15, 10))
    plt.subplots_adjust(hspace=0.3, wspace=0.2)
    fig.suptitle(f"Steam 挂刀指数分析 - 数据截至 {latest_date.strftime('%Y-%m-%d')}", fontsize=16)

    # 1. 周线 (最近7个数据点)
    axes[0, 0].plot(dates[-7:], values[-7:], marker='o', color='#1f77b4', linewidth=2)
    axes[0, 0].set_title("周趋势 (7 Days)")
    axes[0, 0].xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
    axes[0, 0].grid(True, linestyle='--', alpha=0.6)

    # 2. 月线 (最近30个数据点)
    axes[0, 1].plot(dates[-30:], values[-30:], color='#2ca02c', linewidth=2)
    axes[0, 1].set_title("月趋势 (30 Days)")
    axes[0, 1].xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
    axes[0, 1].grid(True, linestyle='--', alpha=0.6)

    # 3. 季度线 (最近90个数据点)
    axes[1, 0].plot(dates[-90:], values[-90:], color='#ff7f0e', linewidth=1.5)
    axes[1, 0].set_title("季度趋势 (90 Days)")
    axes[1, 0].xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    axes[1, 0].grid(True, linestyle='--', alpha=0.6)

    # 4. 历史同期月线 (最近3年的当前月份对比)
    curr_month = latest_date.month
    colors = ['#d62728', '#9467bd', '#8c564b']
    found_any = False
    
    # 获取最近3年内该月份的数据
    for i, year_offset in enumerate([0, 1, 2]):
        target_year = latest_date.year - year_offset
        # 筛选该年该月的数据
        month_points = [
            (d.day, v) for d, v in zip(dates, values) 
            if d.year == target_year and d.month == curr_month
        ]
        if month_points:
            found_any = True
            days, vals = zip(*month_points)
            axes[1, 1].plot(days, vals, label=f"{target_year}年{curr_month}月", color=colors[i], marker='.' if year_offset==0 else None)
    
    if found_any:
        axes[1, 1].set_title(f"历史同期对比 ({curr_month}月)")
        axes[1, 1].set_xlabel("日期 (Day of Month)")
        axes[1, 1].legend()
        axes[1, 1].grid(True, linestyle='--', alpha=0.6)
    else:
        axes[1, 1].set_title("历史同期对比 (暂无数据)")

    # 保存图片
    file_name = f"D:/code/iflow_request/analysis_pic/market_analysis_{latest_date.strftime('%Y%m%d')}.png"
    plt.savefig(file_name)
    print(f"√ 趋势分析图已生成: {file_name}")
    # 如果在有GUI的环境下可以使用 plt.show()
    # plt.show()

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