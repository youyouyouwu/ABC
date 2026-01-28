import streamlit as st
import pandas as pd
import random
from io import BytesIO
from datetime import datetime, timedelta

# --- 页面配置 ---
st.set_page_config(page_title="ABC", layout="wide") 
st.title("ABC 排单系统 (自定义日期版)")

# --- 侧边栏：设置 ---
with st.sidebar:
    st.header("1. 日期范围设置")
    # 默认今天开始，往后排7天
    today = datetime.today()
    start_date = st.date_input("开始日期", today)
    end_date = st.date_input("结束日期", today + timedelta(days=6))
    
    if start_date > end_date:
        st.error("结束日期必须晚于开始日期！")
        
    # 计算所有日期列表
    delta = (end_date - start_date).days + 1
    date_list = [start_date + timedelta(days=i) for i in range(delta)]
    
    st.success(f"已选择排单天数：{len(date_list)} 天")

    st.header("2. 账号范围设置")
    main_start = st.number_input("主力账号起始", value=1)
    main_end = st.number_input("主力账号结束", value=180)
    backup_start = st.number_input("替补账号起始", value=181)
    backup_count = st.number_input("替补账号数量", value=20)
    
    # 生成账号池
    main_accounts = list(range(main_start, main_end + 1))
    backup_accounts = list(range(backup_start, backup_start + backup_count))
    
    st.info(f"主力号：{len(main_accounts)} 个 | 替补号：{len(backup_accounts)} 个")

# --- 辅助函数：寻找可用替补 ---
def find_valid_backup(start_index, backup_pool, history, pid, exclude_acc=None):
    pool_size = len(backup_pool)
    for i in range(pool_size):
        current_idx = (start_index + i) % pool_size
        candidate = backup_pool[current_idx]
        if exclude_acc and candidate == exclude_acc:
            continue
        if pid not in history[candidate]:
            return candidate
    return None

# --- 辅助函数：格式化日期显示 ---
def format_date_sheet_name(d):
    # 返回格式：10-24 (周四)
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    return f"{d.strftime('%m-%d')} ({weekdays[d.weekday()]})"

# --- 核心逻辑函数 ---
def generate_smart_schedule(df, target_dates):
    # 1. 建立全局历史记录
    all_accounts = main_accounts + backup_accounts
    global_history = {acc: set() for acc in all_accounts}
    
    # 2. 准备结果容器 (使用格式化后的日期作为Key)
    schedule_results = {}
    for d in target_dates:
        schedule_results[format_date_sheet_name(d)] = []
    
    # 3. 解析任务
    tasks = []
    for _, row in df.iterrows():
        pid = str(row[0]).strip()
        total_qty = int(row[1])
        
        if total_qty > len(main_accounts):
            st.error(f"错误：产品 {pid} 的总单量 ({total_qty}) 超过了主力账号总数，无法分配不重复主力！")
            return None
            
        tasks.append({'id': pid, 'total': total_qty})

    random.shuffle(tasks)

    # 4. 按天分配
    num_days = len(target_dates)
    
    for day_idx, date_obj in enumerate(target_dates):
        day_key = format_date_sheet_name(date_obj)
        daily_load = {acc: 0 for acc in main_accounts}
        
        for task in tasks:
            pid = task['id']
            total = task['total']
            
            # --- 动态计算每一天的单量 ---
            # 总量 除以 天数
            base = total // num_days
            remainder = total % num_days
            needed_today = base + (1 if day_idx < remainder else 0)
            
            if needed_today == 0:
                continue
                
            for _ in range(needed_today):
                # 选主力
                candidates = [acc for acc in main_accounts if pid not in global_history[acc]]
                if not candidates:
                    st.error(f"无法分配：在 {day_key} 为产品 {pid} 找不到可用主力账号。")
                    return None

                min_load = min(daily_load[acc] for acc in candidates)
                best_candidates = [acc for acc in candidates if daily_load[acc] == min_load]
                chosen_main = random.choice(best_candidates)
                
                global_history[chosen_main].add(pid)
                daily_load[chosen_main] += 1
                
                # 选替补1
                preferred_idx = (chosen_main - main_start) // 9
                chosen_backup1 = find_valid_backup(preferred_idx, backup_accounts, global_history, pid)
                if chosen_backup1 is None:
                    chosen_backup1 = backup_accounts[preferred_idx % len(backup_accounts)]
                global_history[chosen_backup1].add(pid)

                # 选替补2
                backup1_real_idx = backup_accounts.index(chosen_backup1)
                start_search_2 = (backup1_real_idx + 1)
                chosen_backup2 = find_valid_backup(start_search_2, backup_accounts, global_history, pid, exclude_acc=chosen_backup1)
                if chosen_backup2 is None:
                    chosen_backup2 = backup_accounts[(backup1_real_idx + 1) % len(backup_accounts)]
                global_history[chosen_backup2].add(pid)
                
                schedule_results[day_key].append({
                    "产品编号": pid,
                    "期间总单量": total,
                    "主力账号": chosen_main,
                    "替补账号1": chosen_backup1,
                    "替补账号2": chosen_backup2
                })

    return schedule_results, [format_date_sheet_name(d) for d in target_dates]

# --- 界面交互 ---
uploaded_file = st.file_uploader("📂 上传 Excel 表格 (第一列：产品编号，第二列：期间总单量)", type=["xlsx"])

if uploaded_file and start_date <= end_date:
    try:
        df_input = pd.read_excel(uploaded_file, engine='openpyxl')
        st.write("数据预览：", df_input.head())
        
        if st.button("🚀 开始计算并生成排期"):
            with st.spinner('正在计算...'):
                # 传入日期列表
                results, day_keys = generate_smart_schedule(df_input, date_list)
                
            if results:
                st.success(f"✅ 排程完成！日期范围：{start_date} 至 {end_date}")
                
                output = BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    workbook = writer.book
                    center_fmt = workbook.add_format({'align': 'center', 'valign': 'vcenter'})
                    
                    # 颜色定义
                    colors = ['#E6F3FF', '#E6FFFA', '#F0FFF0', '#FFFFE0', '#FFF0F5', '#F5F5F5']
                    
                    # 1. 生成每日明细 Sheet
                    for d_key in day_keys:
                        df_day = pd.DataFrame(results[d_key])
                        if not df_day.empty:
                            df_day = df_day.sort_values(by="产品编号")
                            df_day.insert(0, "序号", range(1, 1 + len(df_day)))
                            df_day.to_excel(writer, sheet_name=d_key, index=False)
                            writer.sheets[d_key].set_column('A:F', 15, center_fmt)
                        else:
                            # 即使某天没单子，也生成空表
                            pd.DataFrame(columns=["序号","产品编号","期间总单量","主力账号","替补账号1","替补账号2"]).to_excel(writer, sheet_name=d_key, index=False)

                    # 2. 生成【汇总复核】Sheet
                    summary_sheet = workbook.add_worksheet("汇总复核")
                    
                    current_col = 0
                    for i, d_key in enumerate(day_keys):
                        # 循环使用颜色
                        color_idx = i % len(colors)
                        bg_color = colors[color_idx]
                        
                        header_fmt = workbook.add_format({'align': 'center', 'valign': 'vcenter', 'bold': True, 'bg_color': bg_color, 'border': 1})
                        cell_fmt = workbook.add_format({'align': 'center', 'valign': 'vcenter', 'bg_color': bg_color, 'border': 1})
                        total_fmt = workbook.add_format({'align': 'center', 'valign': 'vcenter', 'bold': True, 'bg_color': bg_color, 'border': 1, 'font_color': '#FF0000'})

                        raw_data = results[d_key]
                        
                        if raw_data:
                            df_temp = pd.DataFrame(raw_data)
                            summary_df = df_temp['产品编号'].value_counts().reset_index()
                            summary_df.columns = ['产品编号', '当日总单量']
                            summary_df = summary_df.sort_values(by='产品编号')
                            
                            # 表头
                            summary_sheet.write(0, current_col, "日期", header_fmt)
                            summary_sheet.write(0, current_col+1, "产品编号", header_fmt)
                            summary_sheet.write(0, current_col+2, "当日总单量", header_fmt)
                            
                            # 数据
                            for row_idx, row_data in summary_df.iterrows():
                                summary_sheet.write(row_idx+1, current_col, d_key, cell_fmt)
                                summary_sheet.write(row_idx+1, current_col+1, row_data['产品编号'], cell_fmt)
                                summary_sheet.write(row_idx+1, current_col+2, row_data['当日总单量'], cell_fmt)
                            
                            # 底部总计
                            total_row_idx = len(summary_df) + 1
                            day_total_sum = summary_df['当日总单量'].sum()
                            summary_sheet.write(total_row_idx, current_col + 1, "当日合计", header_fmt)
                            summary_sheet.write(total_row_idx, current_col + 2, day_total_sum, total_fmt)

                            summary_sheet.set_column(current_col, current_col+2, 18) # 稍微宽一点适应日期显示
                            
                        else:
                            summary_sheet.write(0, current_col, d_key + " (无数据)", header_fmt)
                        
                        current_col += 3

                st.download_button(
                    label="📥 下载 ABC 自定义日期排程表",
                    data=output.getvalue(),
                    file_name="ABC_Custom_Schedule.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
    except Exception as e:
        st.error(f"程序出错: {e}")
