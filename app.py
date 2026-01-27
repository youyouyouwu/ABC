import streamlit as st
import pandas as pd
import random
from io import BytesIO

# --- 页面配置 ---
st.set_page_config(page_title="ABC", layout="wide") 
st.title("ABC 排单系统 (带汇总复核 + 可视化)")

# --- 侧边栏：账号设置 ---
with st.sidebar:
    st.header("1. 账号范围设置")
    main_start = st.number_input("主力账号起始", value=1)
    main_end = st.number_input("主力账号结束", value=180)
    backup_start = st.number_input("替补账号起始", value=181)
    backup_count = st.number_input("替补账号数量", value=20)
    
    # 生成账号池
    main_accounts = list(range(main_start, main_end + 1))
    backup_accounts = list(range(backup_start, backup_start + backup_count))
    
    st.info(f"当前主力号：{len(main_accounts)} 个\n当前替补号：{len(backup_accounts)} 个")

    st.header("2. 说明")
    st.markdown("""
    **功能更新：**
    - 最后增加【汇总复核】Sheet。
    - 按天分栏显示，不同颜色区分。
    - 自动统计每日各产品下单总数。
    """)

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

# --- 核心逻辑函数 ---
def generate_smart_schedule(df):
    days = ["周一", "周二", "周三", "周四", "周五", "周六"]
    
    # 1. 建立全局历史记录
    all_accounts = main_accounts + backup_accounts
    global_history = {acc: set() for acc in all_accounts}
    
    # 2. 准备结果容器
    schedule_results = {day: [] for day in days}
    
    # 3. 解析任务
    tasks = []
    for _, row in df.iterrows():
        pid = str(row[0]).strip()
        total_weekly = int(row[1])
        
        if total_weekly > len(main_accounts):
            st.error(f"错误：产品 {pid} 的周单量 ({total_weekly}) 超过了主力账号总数，无法分配不重复主力！")
            return None
            
        tasks.append({'id': pid, 'total': total_weekly})

    random.shuffle(tasks)

    # 4. 按天分配
    for day_idx, day_name in enumerate(days):
        daily_load = {acc: 0 for acc in main_accounts}
        
        for task in tasks:
            pid = task['id']
            total = task['total']
            
            base = total // 6
            remainder = total % 6
            needed_today = base + (1 if day_idx < remainder else 0)
            
            if needed_today == 0:
                continue
                
            for _ in range(needed_today):
                # 选主力
                candidates = [acc for acc in main_accounts if pid not in global_history[acc]]
                if not candidates:
                    st.error(f"无法分配：在 {day_name} 为产品 {pid} 找不到可用主力账号。")
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
                
                schedule_results[day_name].append({
                    "产品编号": pid,
                    "周待补单量": total,
                    "主力账号": chosen_main,
                    "替补账号1": chosen_backup1,
                    "替补账号2": chosen_backup2
                })

    return schedule_results

# --- 界面交互 ---
uploaded_file = st.file_uploader("📂 上传 Excel 表格 (第一列：产品编号，第二列：周总单量)", type=["xlsx"])

if uploaded_file:
    try:
        df_input = pd.read_excel(uploaded_file, engine='openpyxl')
        st.write("数据预览：", df_input.head())
        
        if st.button("🚀 开始计算并生成排期"):
            with st.spinner('正在计算...'):
                results = generate_smart_schedule(df_input)
                
            if results:
                st.success("✅ 排程完成！正在生成带汇总表的文件...")
                
                output = BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    workbook = writer.book
                    
                    # --- 样式定义 ---
                    center_fmt = workbook.add_format({'align': 'center', 'valign': 'vcenter'})
                    
                    # 定义6种淡色背景，用于区分周一到周六
                    colors = ['#E6F3FF', '#E6FFFA', '#F0FFF0', '#FFFFE0', '#FFF0F5', '#F5F5F5']
                    color_formats = [workbook.add_format({'align': 'center', 'valign': 'vcenter', 'bg_color': c, 'border': 1}) for c in colors]
                    header_formats = [workbook.add_format({'align': 'center', 'valign': 'vcenter', 'bold': True, 'bg_color': c, 'border': 1}) for c in colors]

                    # 1. 生成每日明细 Sheet
                    days_list = ["周一", "周二", "周三", "周四", "周五", "周六"]
                    for day in days_list:
                        df_day = pd.DataFrame(results[day])
                        if not df_day.empty:
                            df_day = df_day.sort_values(by="产品编号")
                            df_day.insert(0, "序号", range(1, 1 + len(df_day)))
                            df_day.to_excel(writer, sheet_name=day, index=False)
                            writer.sheets[day].set_column('A:F', 15, center_fmt)
                        else:
                            pd.DataFrame(columns=["序号","产品编号","周待补单量","主力账号","替补账号1","替补账号2"]).to_excel(writer, sheet_name=day, index=False)

                    # 2. 生成【汇总复核】Sheet
                    summary_sheet = workbook.add_worksheet("汇总复核")
                    
                    current_col = 0
                    for i, day in enumerate(days_list):
                        # 获取当天数据
                        raw_data = results[day]
                        
                        if raw_data:
                            # 统计当天每个产品的单量
                            df_temp = pd.DataFrame(raw_data)
                            # 聚合统计：按产品编号计数
                            summary_df = df_temp['产品编号'].value_counts().reset_index()
                            summary_df.columns = ['产品编号', '当日总单量']
                            summary_df = summary_df.sort_values(by='产品编号')
                            
                            # 写入表头 (3列: 日期, 产品, 单量)
                            summary_sheet.write(0, current_col, "日期", header_formats[i])
                            summary_sheet.write(0, current_col+1, "产品编号", header_formats[i])
                            summary_sheet.write(0, current_col+2, "当日总单量", header_formats[i])
                            
                            # 写入数据
                            for row_idx, row_data in summary_df.iterrows():
                                # A列：写入日期文本
                                summary_sheet.write(row_idx+1, current_col, day, color_formats[i])
                                # B列：产品编号
                                summary_sheet.write(row_idx+1, current_col+1, row_data['产品编号'], color_formats[i])
                                # C列：单量
                                summary_sheet.write(row_idx+1, current_col+2, row_data['当日总单量'], color_formats[i])
                                
                            # 设置列宽
                            summary_sheet.set_column(current_col, current_col+2, 15)
                            
                        else:
                            # 如果某天没数据，也占个位
                            summary_sheet.write(0, current_col, day + " (无数据)", header_formats[i])
                        
                        # 向右移动4列（留1列空白间隔，或者紧挨着? 你要求D/E/F，所以是紧挨着）
                        # A,B,C -> 0,1,2. 下一次从 3 (D) 开始
                        current_col += 3

                st.download_button(
                    label="📥 下载 ABC 最终排程表 (含汇总)",
                    data=output.getvalue(),
                    file_name="ABC_Final_Schedule.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
    except Exception as e:
        st.error(f"程序出错: {e}")
