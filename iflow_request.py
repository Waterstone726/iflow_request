import json
import requests
import schedule
import time
from datetime import datetime, timedelta
from plyer import notification

# ==================== 核心配置区 (已修正) ====================
TARGET_URL = "https://api.iflow.work/steam/analysisData"

# --- 触发提醒的条件 ---
# 逻辑：只要满足以下【任意】一条，就报警
BUY_CONDITIONS = {
    # 周策略：必须是过去7天里的【第1低】才提醒 (严苛)
    'week_rank_target': 1,   
    
    # 月策略：价格处于过去30天的【底部 10%】区间 (0.1)
    'month_quantile_target': 0.10, 
    
    # 季策略：价格处于过去90天的【底部 15%】区间
    'quarter_quantile_target': 0.15, 
    
    # 年策略：价格处于过去365天的【底部 20%】区间 (放宽，防止长期通胀不触发)
    'year_quantile_target': 0.20   
}

# 历史同期预警阈值 (例如：历史上未来7天平均跌幅 > 2% 则预警)
SEASONAL_DROP_THRESHOLD = 0.02

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.iflow.work/"
}

# ==================== 逻辑实现 ====================

def get_market_position(current_val, history_values):
    """
    计算当前价格在历史数据中的位置
    返回: (排名int, 分位数float)
    注：排名 1 代表最低价；分位数 0.0 代表最低，1.0 代表最高
    """
    if not history_values:
        return 1, 0.0
    
    # 加上当前值一起排序，看看排老几
    all_values = history_values + [current_val]
    all_values.sort()
    
    # 找到当前值在排序后列表中的索引 (如果有重复值，取第一个，即更优的排名)
    rank_index = all_values.index(current_val)
    
    # 排名 (从1开始)
    rank = rank_index + 1
    
    # 分位数 (0.0 ~ 1.0, 越小越便宜)
    # 公式：比我便宜的数量 / 总数量
    cheaper_count = sum(1 for v in history_values if v < current_val)
    quantile = cheaper_count / len(history_values)
    
    return rank, quantile

def check_market():
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 正在扫描市场...")
    
    try:
        resp = requests.get(TARGET_URL, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            print(f"接口报错: {resp.status_code}")
            return

        raw_data = resp.json()
        
        # ======= 新增：保存数据到本地 =======
        file_path = "steam_market_history.json"
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(raw_data, f, ensure_ascii=False, indent=4)
        print(f"√ 数据已备份至 {file_path}")
        # ===================================
        
        # 1. 数据清洗：只取 10% 类型，按日期排序
        # 【关键点】这里不能写成 sorted(...)，必须是下面这行完整的列表推导式！
        n10_data = sorted(
            [item for item in raw_data if item.get('type') == '10%'], 
            key=lambda x: x['date']
        )
        
        if not n10_data:
            print("数据源为空")
            return

        # 提取最新数据
        latest = n10_data[-1]
        curr_val = latest['value']
        curr_date = datetime.strptime(latest['date'], "%Y-%m-%d")
        
        print(f"数据日期: {latest['date']} | 当前指数: {curr_val:.4f}")

        # 2. 周期回溯分析
        periods = {
            '周': {'days': 7, 'key': 'week_rank_target', 'mode': 'rank'},
            '月': {'days': 30, 'key': 'month_quantile_target', 'mode': 'quantile'},
            '季': {'days': 90, 'key': 'quarter_quantile_target', 'mode': 'quantile'},
            '年': {'days': 365, 'key': 'year_quantile_target', 'mode': 'quantile'}
        }
        
        report_msgs = []
        
        for name, conf in periods.items():
            # 切片获取历史数据（不含今天）
            start_dt = curr_date - timedelta(days=conf['days'])
            hist_vals = [
                x['value'] for x in n10_data 
                if start_dt <= datetime.strptime(x['date'], "%Y-%m-%d") < curr_date
            ]
            
            if not hist_vals: continue
            
            real_rank, real_quantile = get_market_position(curr_val, hist_vals)
            target = BUY_CONDITIONS.get(conf['key'])

            # 逻辑判断
            is_hit = False
            status_text = ""
            
            if conf['mode'] == 'rank':
                # 排名模式：比如要求第1名
                if real_rank <= target:
                    is_hit = True
                status_text = f"近{name}排名: 第{real_rank}低"
            else:
                # 分位数模式：比如要求在底部 10% (<=0.1)
                if real_quantile <= target:
                    is_hit = True
                status_text = f"近{name}位置: 底部 {real_quantile*100:.1f}%"
            
            print(f"  - {status_text}")
            
            if is_hit:
                report_msgs.append(f"★ 触发{name}度好价 ({status_text})")

        # 3. 季节性检测 (简单版)
        seasonal_msg = check_seasonal(n10_data, curr_date)
        
        # 4. 汇总发送
        if report_msgs:
            final_msg = f"💰 发现好价！指数 {curr_val:.4f}\n" + "\n".join(report_msgs)
            if seasonal_msg:
                final_msg += f"\n\n{seasonal_msg}"
                
            notification.notify(
                title='Steam 挂刀行情提醒',
                message=final_msg,
                app_name='Market Bot',
                timeout=20
            )
            print(">>> 已发送提醒弹窗")
        elif seasonal_msg:
            # 如果没有好价，但有剧烈跌幅预警，也弹一下
            print(">>> 虽无好价，但有历史预警")
            notification.notify(title='Steam 历史预警', message=seasonal_msg, timeout=15)

    except Exception as e:
        print(f"出错: {e}")

def check_seasonal(all_data, curr_date):
    # 检查过去3年同期的未来7天平均跌幅
    drops = []
    date_val_map = {x['date']: x['value'] for x in all_data}
    
    for year_back in [1, 2, 3]:
        try:
            past_start = curr_date.replace(year=curr_date.year - year_back)
            past_end = past_start + timedelta(days=7)
            
            s_str = past_start.strftime("%Y-%m-%d")
            e_str = past_end.strftime("%Y-%m-%d")
            
            if s_str in date_val_map and e_str in date_val_map:
                # 跌幅 = (开始 - 结束) / 开始
                change = (date_val_map[s_str] - date_val_map[e_str]) / date_val_map[s_str]
                drops.append(change)
        except: pass
        
    if drops:
        avg_drop = sum(drops) / len(drops)
        if avg_drop > SEASONAL_DROP_THRESHOLD:
            return f"⚠️ 历史预警: 过去{len(drops)}年同期，未来一周平均下跌 {avg_drop*100:.1f}%"
    return None

if __name__ == "__main__":
    print("--- Steam 挂刀监控 V3 (Rank修正版) ---")
    check_market()
    schedule.every().day.at("10:15").do(check_market)
    schedule.every().day.at("22:15").do(check_market)
    while True:
        schedule.run_pending()
        time.sleep(60)