import streamlit as st
import pandas as pd
import random
from io import BytesIO
from datetime import datetime, timedelta
import zipfile

# --- 页面配置 ---
st.set_page_config(page_title="ABC", layout="wide") 
st.title("ABC 排单系统 (链接导入Sheet2修正版)")

# --- 侧边栏：设置 ---
with st.sidebar:
    st.header("1. 日期范围设置")
    today = datetime.today()
    
    # 默认跨度为 5天 (即当天+5天=总共6天)
    default_end = today + timedelta(days=5)
    
    start_date = st.date_input("开始日期", today)
    end_date = st.date_input("结束日期", default_end)
    
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
        if len(row) < 2 or pd.isna(row.iloc[0]) or str(row.iloc[0]).strip() == "":
            continue
            
        pid = str(row.iloc[0]).strip()
        try:
            total_qty = int(row.iloc[1])
        except (ValueError, TypeError):
            continue 
            
        if total_qty > len(main_accounts):
            st.error(f"错误：产品 {pid} 的总单量 ({total_qty}) 超过了主力账号总数！")
            return None
        tasks.append({'id': pid, 'total': total_qty})

    if not tasks:
        st.error("没有找到有效的排单任务，请检查表格内容。")
        return None

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
        
        info_data = product_info_map.get(pid, {})
        infos = info_data.get('details', [""] * 7)
        if len(infos) < 7: infos += [""] * (7 - len(infos))
        
        # 【完全复原 Sheet1】保持原来的 14 列，不在这里加链接
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
            
            st.subheader("1. 任务表预览 (Sheet1)")
            st.dataframe(df_tasks, use_container_width=True, height=200)
            
            st.subheader("2. 信息表预览 (Sheet2)")
            st.dataframe(df_details, use_container_width=True, height=200)
            
            product_info_map = {}
            for _, row in df_details.iterrows():
                if len(row) == 0 or pd.isna(row.iloc[0]) or str(row.iloc[0]).strip() == "":
                    continue
                p_code = str(row.iloc[0]).strip()
                
                details = []
                for i in range(1, 8):
                    val = row.iloc[i] if i < len(row) else ""
                    details.append(val)
                
                price_val = 0.0
                if len(row) > 8 and pd.notna(row.iloc[8]):
                    try:
                        price_val = float(row.iloc[8])
                    except (ValueError, TypeError):
                        price_val = 0.0
                
                # 读取 J 列 和 K 列链接
                link_j = str(row.iloc[9]).strip() if len(row) > 9 and pd.notna(row.iloc[9]) else ""
                link_k = str(row.iloc[10]).strip() if len(row) > 10 and pd.notna(row.iloc[10]) else ""
                
                product_info_map[p_code] = {
                    'details': details,
                    'price': price_val,
                    'link_j': link_j,
                    'link_k': link_k
                }

            if st.button("🚀 生成排程结果"):
                with st.spinner('计算中...'):
                    results = generate_smart_schedule(df_tasks, date_list)
                
                if results:
                    st.success("✅ 计算完成！所有数据处理成功。")
                    
                    # ---------------------------------------------------------
                    # 1. 纯排单汇总表 (管理用)
                    # ---------------------------------------------------------
                    buffer_sched = BytesIO()
                    with pd.ExcelWriter(buffer_sched, engine='xlsxwriter') as writer:
                        wb = writer.book
                        
                        header_fmt = wb.add_format({'align': 'center', 'valign': 'vcenter', 'bold': True, 'bg_color': '#D3D3D3', 'border': 1})
                        white_fmt = wb.add_format({'align': 'center', 'valign': 'vcenter', 'border': 1, 'bg_color': '#FFFFFF'})
                        gray_fmt = wb.add_format({'align': 'center', 'valign': 'vcenter', 'border': 1, 'bg_color': '#F2F2F2'})
                        
                        for date_obj in date_list:
                            raw_data = results[date_obj]
                            day_str = format_date_str(date_obj)
                            
                            if raw_data:
                                df_schedule = pd.DataFrame(raw_data).sort_values(by="产品编号")
                                df_schedule.insert(0, "序号", range(1, 1 + len(df_schedule)))
                                df_schedule["金额"] = df_schedule["产品编号"].apply(lambda x: product_info_map.get(x, {}).get('price', 0))

                                df_schedule.to_excel(writer, sheet_name=day_str, index=False)
                                ws = writer.sheets[day_str]
                                ws.set_column('A:F', 15, white_fmt) 
                                ws.set_column('G:G', 15, white_fmt) 
                                
                                for c, val in enumerate(df_schedule.columns):
                                    ws.write(0, c, val, header_fmt)
                                
                                current_product = None
                                color_toggle = False
                                
                                for r_idx, row in enumerate(df_schedule.itertuples(), 1):
                                    product_code = row.产品编号
                                    if product_code != current_product:
                                        current_product = product_code
                                        color_toggle = not color_toggle
                                    
                                    row_fmt = gray_fmt if color_toggle else white_fmt
                                    
                                    ws.write(r_idx, 0, row.序号, row_fmt)
                                    ws.write(r_idx, 1, row.产品编号, row_fmt)
                                    ws.write(r_idx, 2, row.期间总单量, row_fmt)
                                    ws.write(r_idx, 3, row.主力账号, row_fmt)
                                    ws.write(r_idx, 4, row.替补账号1, row_fmt)
                                    ws.write(r_idx, 5, row.替补账号2, row_fmt)
                                    ws.write(r_idx, 6, row.金额, row_fmt) 
                                    
                            else:
                                pd.DataFrame().to_excel(writer, sheet_name=day_str)

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
                                
                                daily_total_money = 0
                                
                                for r_idx, r_dat in sum_df.iterrows():
                                    pid = r_dat['产品编号']
                                    qty = r_dat['当日总单量']
                                    price = product_info_map.get(pid, {}).get('price', 0)
                                    daily_total_money += (qty * price)
                                    
                                    ws_summary.write(r_idx+1, curr_col, day_str, c_fmt)
                                    ws_summary.write(r_idx+1, curr_col+1, pid, c_fmt)
                                    ws_summary.write(r_idx+1, curr_col+2, qty, c_fmt)
                                
                                total_row = len(sum_df) + 1
                                ws_summary.write(total_row, curr_col+1, "当日合计", h_fmt)
                                ws_summary.write(total_row, curr_col+2, sum_df['当日总单量'].sum(), tot_fmt)
                                
                                money_row = total_row + 1
                                ws_summary.write(money_row, curr_col+1, "总金额", h_fmt)
                                ws_summary.write(money_row, curr_col+2, daily_total_money, tot_fmt)
                                
                                ws_summary.set_column(curr_col, curr_col+2, 16)
                            curr_col += 3

                    # ---------------------------------------------------------
                    # 2. 独立工单 Zip (将链接放到 Sheet2)
                    # ---------------------------------------------------------
                    buffer_zip = BytesIO()
                    with zipfile.ZipFile(buffer_zip, "w") as zf:
                        for date_obj in date_list:
                            raw_data = results[date_obj]
                            if not raw_data: continue
                            
                            # 生成原汁原味的 Sheet1
                            df_sheet1 = convert_to_work_order_df(raw_data, product_info_map)
                            
                            # 聚合生成 Sheet2
                            df_sheet2 = df_sheet1.groupby('产品代码', as_index=False).agg({
                                '工单号': 'count',
                                '环境序号': lambda x: "",
                                '橙火ID': 'first',
                                'PRODUCT ID': 'first',
                                'VENDOR ITEM ID': 'first',
                                '关键词': 'first',
                                '品牌名称': 'first',
                                '最低价': 'first',
                                '最高价': 'first'
                            })
                            df_sheet2.rename(columns={'工单号': '产品数量', 'VENDOR ITEM ID': '自发货ID'}, inplace=True)
                            
                            # 【核心修正】在 Sheet2 提取链接信息并加在最后
                            df_sheet2['自发货外部推广链接'] = df_sheet2['产品代码'].apply(lambda x: product_info_map.get(x, {}).get('link_j', ''))
                            df_sheet2['火箭仓外部推广链接'] = df_sheet2['产品代码'].apply(lambda x: product_info_map.get(x, {}).get('link_k', ''))
                            
                            # Sheet2 包含A-L共12列
                            target_cols = ['产品数量', '产品代码', '环境序号', '橙火ID', 'PRODUCT ID', '自发货ID', '关键词', '品牌名称', '最低价', '最高价', '自发货外部推广链接', '火箭仓外部推广链接']
                            df_sheet2 = df_sheet2[target_cols]
                            
                            buf_single = BytesIO()
                            with pd.ExcelWriter(buf_single, engine='xlsxwriter') as writer:
                                wb = writer.book
                                
                                header_fmt = wb.add_format({'align': 'center', 'valign': 'vcenter', 'bold': True, 'bg_color': '#D3D3D3', 'border': 1})
                                white_fmt = wb.add_format({'align': 'center', 'valign': 'vcenter', 'border': 1, 'bg_color': '#FFFFFF'})
                                gray_fmt = wb.add_format({'align': 'center', 'valign': 'vcenter', 'border': 1, 'bg_color': '#F2F2F2'})
                                
                                # --- 写入 Sheet1 (完全原样，不包含链接) ---
                                df_sheet1.to_excel(writer, sheet_name='Sheet1', index=False)
                                ws1 = writer.sheets['Sheet1']
                                ws1.set_column('A:N', 12, white_fmt)
                                ws1.set_column('D:H', 18, white_fmt)
                                
                                for c, val in enumerate(df_sheet1.columns):
                                    ws1.write(0, c, val, header_fmt)

                                current_product = None
                                color_toggle = False
                                
                                for r_idx, row in enumerate(df_sheet1.itertuples(), 1):
                                    product_code = row.产品代码
                                    if product_code != current_product:
                                        current_product = product_code
                                        color_toggle = not color_toggle
                                    
                                    row_fmt = gray_fmt if color_toggle else white_fmt
                                    for c_idx, val in enumerate(row[1:]): 
                                        if pd.isna(val): val = ""
                                        ws1.write(r_idx, c_idx, val, row_fmt)

                                # --- 写入 Sheet2 (包含 K/L 链接) ---
                                df_sheet2.to_excel(writer, sheet_name='Sheet2', index=False)
                                ws2 = writer.sheets['Sheet2']
                                center_fmt = wb.add_format({'align': 'center', 'valign': 'vcenter', 'border': 1})
                                
                                ws2.set_column('A:J', 15, center_fmt)
                                ws2.set_column('K:L', 30, center_fmt) # 把链接列 K 和 L 拉宽
                                
                                orange_fmt = wb.add_format({'align': 'center', 'valign': 'vcenter', 'border': 1, 'bg_color': '#FFC000'}) 
                                blue_fmt = wb.add_format({'align': 'center', 'valign': 'vcenter', 'border': 1, 'bg_color': '#CCECFF'})
                                
                                for c, val in enumerate(df_sheet2.columns):
                                    ws2.write(0, c, val, header_fmt)
                                    
                                for r_idx, row in enumerate(df_sheet2.itertuples(), 1):
                                    ws2.write(r_idx, 0, row.产品数量, center_fmt)
                                    ws2.write(r_idx, 1, row.产品代码, center_fmt)
                                    ws2.write(r_idx, 2, "", center_fmt)
                                    
                                    val_d = row.橙火ID
                                    fmt_d = orange_fmt if pd.notna(val_d) and str(val_d).strip() != "" else center_fmt
                                    ws2.write(r_idx, 3, val_d, fmt_d)
                                    
                                    ws2.write(r_idx, 4, df_sheet2.iloc[r_idx-1, 4], center_fmt)
                                    
                                    val_f = df_sheet2.iloc[r_idx-1, 5] 
                                    fmt_f = blue_fmt if pd.notna(val_f) and str(val_f).strip() != "" else center_fmt
                                    ws2.write(r_idx, 5, val_f, fmt_f)
                                    
                                    ws2.write(r_idx, 6, df_sheet2.iloc[r_idx-1, 6], center_fmt)
                                    ws2.write(r_idx, 7, df_sheet2.iloc[r_idx-1, 7], center_fmt)
                                    ws2.write(r_idx, 8, df_sheet2.iloc[r_idx-1, 8], center_fmt)
                                    ws2.write(r_idx, 9, df_sheet2.iloc[r_idx-1, 9], center_fmt)
                                    # 写入 K, L 链接列
                                    ws2.write(r_idx, 10, df_sheet2.iloc[r_idx-1, 10], center_fmt)
                                    ws2.write(r_idx, 11, df_sheet2.iloc[r_idx-1, 11], center_fmt)
                            
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
                            help="Sheet1完全复原，Sheet2包含K/L推广链接"
                        )

    except Exception as e:
        st.error("程序遇到了一点小麻烦，请检查上传的表格格式是否正确。")
        st.warning(f"报错详情供参考: {e}")
