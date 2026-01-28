import streamlit as st
import pandas as pd
import random
from io import BytesIO
from datetime import datetime, timedelta
import zipfile

# --- 页面配置 ---
st.set_page_config(page_title="ABC", layout="wide") 
st.title("ABC 排单系统 (工单汇总颜色版)")

# --- 侧边栏：设置 ---
with st.sidebar:
    st.header("1. 日期范围设置")
    today = datetime.today()
    start_date = st.date_input("开始日期", today)
    end_date = st.date_input("结束日期", today + timedelta(days=6))
    
    if start_date > end_date:
        st.error("结束日期必须晚于开始日期！")
        
    delta = (end_date - start_date).days + 1
    date_list = [start_date + timedelta(days=i) for i in range(delta)]
    
    st.success(f"已选择排单天数：{len(date_list)} 天")

    st.header("2. 账号范围设置")
    main_start = st.number_input("主力账号起始", value=1)
    main_end = st.number_input("主力账号结束", value=180)
    backup_start = st.number_input("替补账号起始", value=181)
    backup_count = st.number_input("替补账号数量", value=20)
    
    main_accounts = list(range(main_start, main_end + 1))
    backup_accounts = list(range(backup_start, backup_start + backup_count))
    
    st.info(f"主力号：{len(main_accounts)} 个 | 替补号：{len(backup_accounts)} 个")

# --- 辅助函数 ---
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

def format_date_str(d):
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    return f"{d.strftime('%m-%d')}({weekdays[d.weekday()]})"

# --- 核心排程逻辑 ---
def generate_smart_schedule(df_tasks, date_list):
    all_accounts = main_accounts + backup_accounts
    global_history = {acc: set() for acc in all_accounts}
    
    schedule_results = {}
    for d in date_list:
        schedule_results[d] = []
    
    tasks = []
    for _, row in df_tasks.iterrows():
        pid = str(row[0]).strip()
        total_qty = int(row[1])
        if total_qty > len(main_accounts):
            st.error(f"错误：产品 {pid} 的总单量 ({total_qty}) 超过了主力账号总数！")
            return None
        tasks.append({'id': pid, 'total': total_qty})

    random.shuffle(tasks)
    num_days = len(date_list)
    
    for day_idx, date_obj in enumerate(date_list):
        daily_load = {acc: 0 for acc in main_accounts}
        for task in tasks:
            pid = task['id']
            total = task['total']
            
            base = total // num_days
            remainder = total % num_days
            needed_today = base + (1 if day_idx < remainder else 0)
            
            if needed_today == 0: continue
                
            for _ in range(needed_today):
                candidates = [acc for acc in main_accounts if pid not in global_history[acc]]
                if not candidates:
                    st.error(f"无法分配：日期 {date_obj} 产品 {pid} 无可用主力。")
                    return None

                min_load = min(daily_load[acc] for acc in candidates)
                best_candidates = [acc for acc in candidates if daily_load[acc] == min_load]
                chosen_main = random.choice(best_candidates)
                
                global_history[chosen_main].add(pid)
                daily_load[chosen_main] += 1
                
                # 替补逻辑
                preferred_idx = (chosen_main - main_start) // 9
                chosen_backup1 = find_valid_backup(preferred_idx, backup_accounts, global_history, pid)
                if not chosen_backup1: chosen_backup1 = backup_accounts[preferred_idx % len(backup_accounts)]
                global_history[chosen_backup1].add(pid)
                
                backup1_real_idx = backup_accounts.index(chosen_backup1)
                start_search_2 = (backup1_real_idx + 1)
                chosen_backup2 = find_valid_backup(start_search_2, backup_accounts, global_history, pid, exclude_acc=chosen_backup1)
                if not chosen_backup2: chosen_backup2 = backup_accounts[(backup1_real_idx + 1) % len(backup_accounts)]
                global_history[chosen_backup2].add(pid)
                
                schedule_results[date_obj].append({
                    "产品编号": pid,
                    "期间总单量": total,
                    "主力账号": chosen_main,
                    "替补账号1": chosen_backup1,
                    "替补账号2": chosen_backup2
                })
                
    return schedule_results

# --- 辅助：转换工单格式 ---
def convert_to_work_order_df(daily_data, product_info_map):
    df_base = pd.DataFrame(daily_data)
    if df_base.empty: return pd.DataFrame()
    
    df_base = df_base.sort_values(by="产品编号")
    final_rows = []
    
    for idx, row in enumerate(df_base.itertuples(), 1):
        pid = row.产品编号
        main_acc = row.主力账号
        infos = product_info_map.get(pid, [""] * 7)
        if len(infos) < 7: infos += [""] * (7 - len(infos))
        
        new_row = [
            idx, pid, main_acc,
            infos[0], infos[1], infos[2], infos[3], infos[4], infos[5], infos[6],
            "", "", "", ""
        ]
        final_rows.append(new_row)
        
    headers = [
        "工单号", "产品代码", "环境序号", 
        "橙火ID", "PRODUCT ID", "VENDOR ITEM ID", "关键词", "品牌名称", 
        "最低价", "最高价", 
        "付款账号", "金额", "结果", "下单时间"
    ]
    return pd.DataFrame(final_rows, columns=headers)

# --- 界面交互 ---
uploaded_file = st.file_uploader("📂 上传 Excel (Sheet1:任务, Sheet2:信息)", type=["xlsx"])

if uploaded_file and start_date <= end_date:
    try:
        xls_dict = pd.read_excel(uploaded_file, sheet_name=None, engine='openpyxl')
        if len(xls_dict) < 2:
            st.error("Excel 必须包含至少两个 Sheet！")
        else:
            sheet_names = list(xls_dict.keys())
            df_tasks = xls_dict[sheet_names[0]]
            df_details = xls_dict[sheet_names[1]]
            
            st.write("任务表预览:", df_tasks.head(1))
            st.write("信息表预览:", df_details.head(1))
            
            product_info_map = {}
            for _, row in df_details.iterrows():
                p_code = str(row[0]).strip()
                product_info_map[p_code] = row.iloc[1:8].tolist()

            if st.button("🚀 生成排程结果"):
                with st.spinner('计算中...'):
                    results = generate_smart_schedule(df_tasks, date_list)
                
                if results:
                    st.success("计算完成！")
                    
                    # ---------------------------------------------------------
                    # 1. 纯排单汇总表 (管理用)
                    # ---------------------------------------------------------
                    buffer_sched = BytesIO()
                    with pd.ExcelWriter(buffer_sched, engine='xlsxwriter') as writer:
                        wb = writer.book
                        center_fmt = wb.add_format({'align': 'center', 'valign': 'vcenter', 'border': 1})
                        
                        for date_obj in date_list:
                            raw_data = results[date_obj]
                            day_str = format_date_str(date_obj)
                            if raw_data:
                                df_schedule = pd.DataFrame(raw_data).sort_values(by="产品编号")
                                df_schedule.insert(0, "序号", range(1, 1 + len(df_schedule)))
                                df_schedule.to_excel(writer, sheet_name=day_str, index=False)
                                writer.sheets[day_str].set_column('A:F', 15, center_fmt)
                            else:
                                pd.DataFrame().to_excel(writer, sheet_name=day_str)

                        # 汇总复核 Sheet
                        ws_summary = wb.add_worksheet("汇总复核")
                        curr_col = 0
                        colors = ['#E6F3FF', '#E6FFFA', '#F0FFF0', '#FFFFE0', '#FFF0F5', '#F5F5F5']
                        
                        for i, date_obj in enumerate(date_list):
                            day_str = format_date_str(date_obj)
                            raw_data = results[date_obj]
                            bg_col = colors[i % len(colors)]
                            
                            h_fmt = wb.add_format({'align': 'center', 'valign': 'vcenter', 'bold': True, 'bg_color': bg_col, 'border': 1})
                            c_fmt = wb.add_format({'align': 'center', 'valign': 'vcenter', 'bg_color': bg_col, 'border': 1})
                            tot_fmt = wb.add_format({'align': 'center', 'valign': 'vcenter', 'bold': True, 'bg_color': bg_col, 'border': 1, 'font_color': 'red'})

                            if raw_data:
                                df_tmp = pd.DataFrame(raw_data)
                                sum_df = df_tmp['产品编号'].value_counts().reset_index()
                                sum_df.columns = ['产品编号', '当日总单量']
                                sum_df = sum_df.sort_values(by='产品编号')
                                
                                ws_summary.write(0, curr_col, "日期", h_fmt)
                                ws_summary.write(0, curr_col+1, "产品编号", h_fmt)
                                ws_summary.write(0, curr_col+2, "当日总单量", h_fmt)
                                
                                for r_idx, r_dat in sum_df.iterrows():
                                    ws_summary.write(r_idx+1, curr_col, day_str, c_fmt)
                                    ws_summary.write(r_idx+1, curr_col+1, r_dat['产品编号'], c_fmt)
                                    ws_summary.write(r_idx+1, curr_col+2, r_dat['当日总单量'], c_fmt)
                                
                                total_row = len(sum_df) + 1
                                ws_summary.write(total_row, curr_col+1, "当日合计", h_fmt)
                                ws_summary.write(total_row, curr_col+2, sum_df['当日总单量'].sum(), tot_fmt)
                                ws_summary.set_column(curr_col, curr_col+2, 16)
                            curr_col += 3

                    # ---------------------------------------------------------
                    # 2. 独立工单 Zip (含 Sheet2 汇总颜色版)
                    # ---------------------------------------------------------
                    buffer_zip = BytesIO()
                    with zipfile.ZipFile(buffer_zip, "w") as zf:
                        for date_obj in date_list:
                            raw_data = results[date_obj]
                            if not raw_data: continue
                            
                            # 1. 生成 Sheet1 数据
                            df_sheet1 = convert_to_work_order_df(raw_data, product_info_map)
                            
                            # 2. 生成 Sheet2 数据 (聚合)
                            # 按 '产品代码' 分组
                            # 逻辑: count '工单号' 作为数量, 其他信息取 first (因为同一产品信息相同)
                            df_sheet2 = df_sheet1.groupby('产品代码', as_index=False).agg({
                                '工单号': 'count',
                                '环境序号': lambda x: "", # 强制置空
                                '橙火ID': 'first',
                                'PRODUCT ID': 'first',
                                'VENDOR ITEM ID': 'first',
                                '关键词': 'first',
                                '品牌名称': 'first',
                                '最低价': 'first',
                                '最高价': 'first'
                            })
                            # 重命名 A 列
                            df_sheet2.rename(columns={'工单号': '产品数量'}, inplace=True)
                            
                            # 调整列顺序 (A-J)
                            target_cols = ['产品数量', '产品代码', '环境序号', '橙火ID', 'PRODUCT ID', 'VENDOR ITEM ID', '关键词', '品牌名称', '最低价', '最高价']
                            df_sheet2 = df_sheet2[target_cols]
                            
                            # 3. 写入 Excel (多 Sheet)
                            buf_single = BytesIO()
                            with pd.ExcelWriter(buf_single, engine='xlsxwriter') as writer:
                                wb = writer.book
                                center_fmt = wb.add_format({'align': 'center', 'valign': 'vcenter', 'border': 1})
                                header_fmt = wb.add_format({'align': 'center', 'valign': 'vcenter', 'bold': True, 'bg_color': '#D3D3D3', 'border': 1})
                                
                                # --- 写入 Sheet1 ---
                                df_sheet1.to_excel(writer, sheet_name='Sheet1', index=False)
                                ws1 = writer.sheets['Sheet1']
                                ws1.set_column('A:N', 12, center_fmt)
                                ws1.set_column('D:H', 18, center_fmt)
                                for c, val in enumerate(df_sheet1.columns):
                                    ws1.write(0, c, val, header_fmt)
                                    
                                # --- 写入 Sheet2 (汇总 + 颜色) ---
                                df_sheet2.to_excel(writer, sheet_name='Sheet2', index=False)
                                ws2 = writer.sheets['Sheet2']
                                ws2.set_column('A:J', 15, center_fmt)
                                
                                # 定义颜色格式
                                orange_fmt = wb.add_format({'align': 'center', 'valign': 'vcenter', 'border': 1, 'bg_color': '#FFC000'}) # 橙色
                                blue_fmt = wb.add_format({'align': 'center', 'valign': 'vcenter', 'border': 1, 'bg_color': '#CCECFF'})   # 浅蓝
                                
                                # 写表头
                                for c, val in enumerate(df_sheet2.columns):
                                    ws2.write(0, c, val, header_fmt)
                                    
                                # 写数据 (应用条件格式)
                                # D列是索引 3 (橙火ID), F列是索引 5 (VENDOR ITEM ID)
                                for r_idx, row in enumerate(df_sheet2.itertuples(), 1):
                                    # 遍历每一列写入
                                    # row[0]是index, row[1]是A列... row[4]是D列(橙火ID)
                                    # itertuples 默认 index=True，所以 row[0] 是 pandas index
                                    # A列: row.产品数量 -> col 0
                                    ws2.write(r_idx, 0, row.产品数量, center_fmt)
                                    ws2.write(r_idx, 1, row.产品代码, center_fmt)
                                    ws2.write(r_idx, 2, "", center_fmt) # 环境序号为空
                                    
                                    # D列: 橙火ID (橙色)
                                    val_d = row.橙火ID
                                    fmt_d = orange_fmt if pd.notna(val_d) and str(val_d).strip() != "" else center_fmt
                                    ws2.write(r_idx, 3, val_d, fmt_d)
                                    
                                    ws2.write(r_idx, 4, getattr(row, "_5"), center_fmt) # PRODUCT ID (因为中间有空格pandas可能会重命名属性，用位置更稳妥) -> 其实itertuples属性名会自动处理空格，这里 PRODUCT ID 会变成 _4 或类似
                                    
                                    # 为保险起见，不通过属性名，通过 iloc 对应的值写入
                                    # df_sheet2.iloc[r_idx-1, 4] 是 PRODUCT ID
                                    ws2.write(r_idx, 4, df_sheet2.iloc[r_idx-1, 4], center_fmt)
                                    
                                    # F列: VENDOR ITEM ID (浅蓝)
                                    val_f = df_sheet2.iloc[r_idx-1, 5]
                                    fmt_f = blue_fmt if pd.notna(val_f) and str(val_f).strip() != "" else center_fmt
                                    ws2.write(r_idx, 5, val_f, fmt_f)
                                    
                                    # G-J列
                                    ws2.write(r_idx, 6, df_sheet2.iloc[r_idx-1, 6], center_fmt)
                                    ws2.write(r_idx, 7, df_sheet2.iloc[r_idx-1, 7], center_fmt)
                                    ws2.write(r_idx, 8, df_sheet2.iloc[r_idx-1, 8], center_fmt)
                                    ws2.write(r_idx, 9, df_sheet2.iloc[r_idx-1, 9], center_fmt)

                            
                            file_name = format_date_str(date_obj) + ".xlsx"
                            zf.writestr(file_name, buf_single.getvalue())

                    st.markdown("---")
                    col1, col2 = st.columns(2)
                    with col1:
                        st.download_button(
                            label="📄 方式1: 下载排单汇总表 (管理用)",
                            data=buffer_sched.getvalue(),
                            file_name="ABC_Schedule_Only.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            help="排单明细 + 汇总复核"
                        )
                    with col2:
                        st.download_button(
                            label="📦 方式2: 下载每日工单包 (员工用)",
                            data=buffer_zip.getvalue(),
                            file_name="ABC_Daily_Work_Orders.zip",
                            mime="application/zip",
                            help="每天独立文件，含Sheet1工单和Sheet2汇总"
                        )

    except Exception as e:
        st.error(f"程序出错: {e}")
