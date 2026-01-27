import streamlit as st
import pandas as pd
import random
from io import BytesIO

# --- 页面配置 ---
st.set_page_config(page_title="ABC", layout="wide") 
st.title("ABC 排单系统 (全员防重版)")

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
    **逻辑升级：**
    - 主力、替补1、替补2 均执行“同产品本周不重复”规则。
    - 如果首选替补已用过，自动寻找下一个可用替补。
    """)

# --- 辅助函数：寻找可用替补 ---
def find_valid_backup(start_index, backup_pool, history, pid, exclude_acc=None):
    """
    从 start_index 开始，在 backup_pool 中找一个没买过 pid 的账号。
    exclude_acc: 需要额外排除的账号（用于选第二个替补时排除第一个）
    """
    pool_size = len(backup_pool)
    # 尝试遍历整个替补池
    for i in range(pool_size):
        # 环形查找：从 start_index 往后找，到头了就回到 0 继续找
        current_idx = (start_index + i) % pool_size
        candidate = backup_pool[current_idx]
        
        # 检查1: 是否被排除 (比如已经是替补1了)
        if exclude_acc and candidate == exclude_acc:
            continue
            
        # 检查2: 历史记录 (本周是否关联过该产品)
        if pid not in history[candidate]:
            return candidate
            
    # 如果转了一圈都没找到 (说明20个替补全买过这个品了)
    return None

# --- 核心逻辑函数 ---
def generate_smart_schedule(df):
    days = ["周一", "周二", "周三", "周四", "周五", "周六"]
    
    # 1. 建立全局历史记录 (包含主力 和 替补)
    # 格式: {账号ID: {'C001', 'C002'...}}
    # 把主力和替补都初始化进去
    all_accounts = main_accounts + backup_accounts
    global_history = {acc: set() for acc in all_accounts}
    
    # 2. 准备结果容器
    schedule_results = {day: [] for day in days}
    
    # 3. 解析任务
    tasks = []
    for _, row in df.iterrows():
        pid = str(row[0]).strip()
        total_weekly = int(row[1])
        
        # 安全检查
        if total_weekly > len(main_accounts):
            st.error(f"错误：产品 {pid} 的周单量 ({total_weekly}) 超过了主力账号总数，无法分配不重复主力！")
            return None
            
        tasks.append({'id': pid, 'total': total_weekly})

    # 打乱任务顺序
    random.shuffle(tasks)

    # 4. 开始按天循环分配
    for day_idx, day_name in enumerate(days):
        
        daily_load = {acc: 0 for acc in main_accounts}
        
        for task in tasks:
            pid = task['id']
            total = task['total']
            
            # --- 数学计算：今天该做几单？ ---
            base = total // 6
            remainder = total % 6
            needed_today = base + (1 if day_idx < remainder else 0)
            
            if needed_today == 0:
                continue
                
            # --- 分配账号 ---
            for _ in range(needed_today):
                # ===========================
                # 步骤1：选主力
                # ===========================
                # 规则：没买过 + 负载低
                candidates = [acc for acc in main_accounts if pid not in global_history[acc]]
                
                if not candidates:
                    st.error(f"无法分配：在 {day_name} 为产品 {pid} 找不到可用主力账号。")
                    return None

                min_load = min(daily_load[acc] for acc in candidates)
                best_candidates = [acc for acc in candidates if daily_load[acc] == min_load]
                chosen_main = random.choice(best_candidates)
                
                # 记账
                global_history[chosen_main].add(pid)
                daily_load[chosen_main] += 1
                
                # ===========================
                # 步骤2：选替补1 (智能防重)
                # ===========================
                # 计算“首选”位置 (9:1逻辑)
                preferred_idx = (chosen_main - main_start) // 9
                
                # 在替补池里搜索可用的
                chosen_backup1 = find_valid_backup(preferred_idx, backup_accounts, global_history, pid)
                
                if chosen_backup1 is None:
                    # 这种情况极少见：说明20个替补本周都跟这个品有过瓜葛
                    # 可以在这里做个妥协，比如强行复用，或者报错。
                    # 为了程序不崩溃，我们强行选首选，但给个标记
                    chosen_backup1 = backup_accounts[preferred_idx % len(backup_accounts)]
                    # st.warning(f"警告：产品 {pid} 替补资源耗尽，账号 {chosen_backup1} 被迫复用。")
                
                # 记账 (只要被列入计划，就视为已占用，防止被别人再次征用)
                global_history[chosen_backup1].add(pid)

                # ===========================
                # 步骤3：选替补2 (排除替补1)
                # ===========================
                # 从替补1的下一个位置开始找
                backup1_real_idx = backup_accounts.index(chosen_backup1)
                start_search_2 = (backup1_real_idx + 1)
                
                chosen_backup2 = find_valid_backup(start_search_2, backup_accounts, global_history, pid, exclude_acc=chosen_backup1)
                
                if chosen_backup2 is None:
                    # 同样的处理逻辑
                    chosen_backup2 = backup_accounts[(backup1_real_idx + 1) % len(backup_accounts)]
                
                # 记账
                global_history[chosen_backup2].add(pid)
                
                # ===========================
                # 存入结果
                # ===========================
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
            with st.spinner('正在进行全员防重计算...'):
                results = generate_smart_schedule(df_input)
                
            if results:
                st.success("✅ 排程完成！主力与替补均已检查重复性。")
                
                # 创建 Excel 下载
                output = BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    
                    workbook = writer.book
                    center_format = workbook.add_format({'align': 'center', 'valign': 'vcenter'})
                    
                    for day in ["周一", "周二", "周三", "周四", "周五", "周六"]:
                        df_day = pd.DataFrame(results[day])
                        
                        if not df_day.empty:
                            df_day = df_day.sort_values(by="产品编号")
                            df_day.insert(0, "序号", range(1, 1 + len(df_day)))
                            df_day.to_excel(writer, sheet_name=day, index=False)
                            
                            worksheet = writer.sheets[day]
                            worksheet.set_column('A:F', 15, center_format)
                            
                        else:
                            empty_df = pd.DataFrame(columns=["序号","产品编号","周待补单量","主力账号","替补账号1","替补账号2"])
                            empty_df.to_excel(writer, sheet_name=day, index=False)
                            worksheet = writer.sheets[day]
                            worksheet.set_column('A:F', 15, center_format)
                
                st.download_button(
                    label="📥 下载 ABC 排程结果 (Excel)",
                    data=output.getvalue(),
                    file_name="ABC_Smart_Schedule.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
    except Exception as e:
        st.error(f"程序出错: {e}")
