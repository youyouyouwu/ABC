import streamlit as st
import pandas as pd
import random
from io import BytesIO
from datetime import datetime, timedelta
import zipfile  # 新增：用于打包多个Excel

# --- 页面配置 ---
st.set_page_config(page_title="ABC", layout="wide") 
st.title("ABC 排单系统 (独立工单 Zip 版)")

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

def format_file_name(d):
    # 文件名格式：10-24(周四).xlsx
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    return f"{d.strftime('%m-%d')}({weekdays[d.weekday()]})"

# --- 核心逻辑函数 ---
def generate_smart_schedule(df_tasks, date_list):
    # 1. 基础排单逻辑 (与之前相同)
    all_accounts = main_accounts + backup_accounts
    global_history = {acc: set() for acc in all_accounts}
    
    schedule_results = {}
    # 使用日期对象作为Key，方便后续处理
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
                
                # 替补逻辑保持，虽然本次输出没要求显示替补，但逻辑需保留以防冲突
                preferred_idx = (chosen_main - main_start) // 9
                chosen_backup1 = find_valid_backup(preferred_idx, backup_accounts, global_history, pid)
                if not chosen_backup1: chosen_backup1 = backup_accounts[preferred_idx % len(backup_accounts)]
                global_history[chosen_backup1].add(pid)
                
                # 记录结果 (只记录需要的信息)
                schedule_results[date_obj].append({
                    "产品编号": pid,
                    "主力账号": chosen_main
                })
                
    return schedule_results

# --- 界面交互 ---
uploaded_file = st.file_uploader("📂 上传 Excel 表格 (需包含 Sheet1:任务, Sheet2:详细信息)", type=["xlsx"])

if uploaded_file and start_date <= end_date:
    try:
        # 读取所有 Sheets
        xls_dict = pd.read_excel(uploaded_file, sheet_name=None, engine='openpyxl')
        sheet_names = list(xls_dict.keys())
        
        if len(sheet_names) < 2:
            st.error("❌ 错误：Excel 文件必须至少包含 2 个 Sheet！(Sheet1为排单，Sheet2为产品信息)")
        else:
            # 获取 Sheet1 (任务) 和 Sheet2 (信息)
            df_tasks = xls_dict[sheet_names[0]]
            df_details = xls_dict[sheet_names[1]]
            
            st.write("数据预览 (Sheet1 - 任务):", df_tasks.head(2))
            st.write("数据预览 (Sheet2 - 信息):", df_details.head(2))
            
            # --- 预处理 Sheet2 信息映射 ---
            # 建立字典: {产品编号: [ColB, ColC, ... ColH]}
            product_info_map = {}
            for _, row in df_details.iterrows():
                # 假设 Sheet2 第一列是产品编号
                p_code = str(row[0]).strip()
                # 取第2列到第8列 (B,C,D,E,F,G,H) 共7个值
                # row.iloc[1:8] 对应 B 到 H
                infos = row.iloc[1:8].tolist()
                product_info_map[p_code] = infos

            if st.button("🚀 生成独立工单文件 (ZIP)"):
                with st.spinner('正在计算排期并生成独立文件...'):
                    results = generate_smart_schedule(df_tasks, date_list)
                    
                    if results:
                        # 创建 ZIP 内存缓冲
                        zip_buffer = BytesIO()
                        
                        with zipfile.ZipFile(zip_buffer, "w") as zf:
                            # 遍历每一天，生成独立的 Excel 并写入 Zip
                            for date_obj, daily_data in results.items():
                                if not daily_data:
                                    continue
                                    
                                # 1. 构建基础数据 DataFrame
                                df_res = pd.DataFrame(daily_data)
                                # 按产品编号排序
                                df_res = df_res.sort_values(by="产品编号")
                                
                                # 2. 构建最终输出表格结构
                                final_rows = []
                                for idx, row in enumerate(df_res.itertuples(), 1):
                                    pid = row.产品编号
                                    main_acc = row.主力账号
                                    
                                    # 从 Sheet2 映射信息 (B-H) -> (D-J)
                                    # 如果找不到产品，填充空值
                                    infos = product_info_map.get(pid, [""] * 7)
                                    # 确保 infos 长度为 7 (防止 Sheet2 列不够)
                                    if len(infos) < 7:
                                        infos += [""] * (7 - len(infos))
                                    
                                    # 构建一行数据 (A 到 N)
                                    # A:工单号, B:产品代码, C:环境序号
                                    # D-J: 映射信息
                                    # K-N: 空白
                                    new_row = [
                                        idx,            # A: 工单号
                                        pid,            # B: 产品代码
                                        main_acc,       # C: 环境序号
                                        infos[0],       # D: 橙火ID
                                        infos[1],       # E: 橙火ID
                                        infos[2],       # F: 橙火ID
                                        infos[3],       # G: 橙火ID
                                        infos[4],       # H: 橙火ID
                                        infos[5],       # I: ZUIDIJIA 
                                        infos[6],       # J: 最高价
                                        "",             # K: 付款账号
                                        "",             # L: 金额
                                        "",             # M: 结果
                                        ""              # N: 下单时间
                                    ]
                                    final_rows.append(new_row)
                                
                                # 定义表头
                                headers = [
                                    "工单号", "产品代码", "环境序号", 
                                    "橙火ID", "橙火ID", "橙火ID", "橙火ID", "橙火ID", 
                                    "ZUIDIJIA ", "最高价", 
                                    "付款账号", "金额", "结果", "下单时间"
                                ]
                                
                                df_final = pd.DataFrame(final_rows, columns=headers)
                                
                                # 3. 写入单个 Excel 文件的 BytesIO
                                excel_buffer = BytesIO()
                                with pd.ExcelWriter(excel_buffer, engine='xlsxwriter') as writer:
                                    # Sheet1 名称固定为 "Sheet1" 或日期名，这里用日期名更直观，或者按要求用 Sheet1
                                    df_final.to_excel(writer, sheet_name='Sheet1', index=False)
                                    
                                    # 设置格式
                                    workbook = writer.book
                                    worksheet = writer.sheets['Sheet1']
                                    center_fmt = workbook.add_format({'align': 'center', 'valign': 'vcenter', 'border': 1})
                                    header_fmt = workbook.add_format({'align': 'center', 'valign': 'vcenter', 'bold': True, 'bg_color': '#D3D3D3', 'border': 1})
                                    
                                    # 设置列宽
                                    worksheet.set_column('A:N', 12, center_fmt) # 默认宽度
                                    worksheet.set_column('B:B', 15, center_fmt) # 产品代码宽一点
                                    worksheet.set_column('D:H', 18, center_fmt) # 橙火ID宽一点
                                    
                                    # 应用表头格式
                                    for col_num, value in enumerate(df_final.columns.values):
                                        worksheet.write(0, col_num, value, header_fmt)
                                
                                # 4. 将 Excel 文件存入 ZIP
                                file_name = format_file_name(date_obj) + ".xlsx"
                                zf.writestr(file_name, excel_buffer.getvalue())

                        st.success("✅ 生成成功！请下载 ZIP 包，解压后即可获得每一天的独立表格。")
                        
                        st.download_button(
                            label="📥 下载工单压缩包 (Zip)",
                            data=zip_buffer.getvalue(),
                            file_name="Brushing_Work_Orders.zip",
                            mime="application/zip"
                        )

    except Exception as e:
        st.error(f"程序出错: {e}")
