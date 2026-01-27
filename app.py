import streamlit as st
import pandas as pd
import random
from io import BytesIO

# --- 页面配置 ---
st.set_page_config(page_title="ABC", layout="wide") 
st.title("ABC 排单系统")

# --- 侧边栏：账号设置 ---
with st.sidebar:
    st.header("1. 账号范围设置")
    main_start = st.number_input("主力账号起始", value=1)
    main_end = st.number_input("主力账号结束", value=180)
    backup_start = st.number_input("替补账号起始", value=181)
    
    # 生成账号池
    main_accounts = list(range(main_start, main_end + 1))
    backup_accounts = list(range(backup_start, backup_start + 20)) 
    
    st.info(f"当前主力号：{len(main_accounts)} 个\n当前替补号：{len(backup_accounts)} 个")

    st.header("2. 说明")
    st.markdown("""
    **替补规则 (9:1)：**
    - 1-9号主力 -> 181号替补
    - 10-18号主力 -> 182号替补
    - 以此类推...
    """)

# --- 核心逻辑函数 ---
def generate_smart_schedule(df):
    days = ["周一", "周二", "周三", "周四", "周五", "周六"]
    
    # 1. 建立全局历史记录
    global_history = {acc: set() for acc in main_accounts}
    
    # 2. 准备结果容器
    schedule_results = {day: [] for day in days}
    
    # 3. 解析任务
    tasks = []
    for _, row in df.iterrows():
        pid = str(row[0]).strip()
        total_weekly = int(row[1])
        
        # 安全检查
        if total_weekly > len(main_accounts):
            st.error(f"错误：产品 {pid} 的周单量 ({total_weekly}) 超过了主力账号总数 ({len(main_accounts)})，无法分配不重复账号！")
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
                # 规则1：本周没买过
                candidates = [acc for acc in main_accounts if pid not in global_history[acc]]
                
                if not candidates:
                    st.error(f"无法分配：在 {day_name} 为产品 {pid} 找不到可用账号。")
                    return None

                # 规则2：负载均衡
                min_load = min(daily_load[acc] for acc in candidates)
                best_candidates = [acc for acc in candidates if daily_load[acc] == min_load]
                
                chosen_main = random.choice(best_candidates)
                
                # --- 记录状态 ---
                global_history[chosen_main].add(pid)
                daily_load[chosen_main] += 1
                
                # --- 匹配替补 ---
                idx = (chosen_main - main_start) // 9
                backup_idx = min(idx, len(backup_accounts) - 1)
                chosen_backup = backup_accounts[backup_idx]
                
                # --- 添加到结果 ---
                schedule_results[day_name].append({
                    "产品编号": pid,
                    "周待补单量": total,
                    "主力账号": chosen_main,
                    "替补账号": chosen_backup
                })

    return schedule_results

# --- 界面交互 ---
uploaded_file = st.file_uploader("📂 上传 Excel 表格 (第一列：产品编号，第二列：周总单量)", type=["xlsx"])

if uploaded_file:
    try:
        # engine='openpyxl' 确保兼容性
        df_input = pd.read_excel(uploaded_file, engine='openpyxl')
        st.write("数据预览：", df_input.head())
        
        if st.button("🚀 开始计算并生成排期"):
            with st.spinner('正在计算最优排程...'):
                results = generate_smart_schedule(df_input)
                
            if results:
                st.success("✅ 排程完成！请下载结果：")
                
                # 创建 Excel 下载
                output = BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    for day in ["周一", "周二", "周三", "周四", "周五", "周六"]:
                        df_day = pd.DataFrame(results[day])
                        
                        if not df_day.empty:
                            # 1. 排序
                            df_day = df_day.sort_values(by="产品编号")
                            
                            # 2. 【核心修改】插入纯数字序号 (1, 2, 3...)
                            # range(1, N) 生成的就是纯阿拉伯数字
                            df_day.insert(0, "序号", range(1, 1 + len(df_day)))
                            
                            # 3. 写入 Excel
                            df_day.to_excel(writer, sheet_name=day, index=False)
                        else:
                            # 空表头
                            pd.DataFrame(columns=["序号","产品编号","周待补单量","主力账号","替补账号"]).to_excel(writer, sheet_name=day, index=False)
                
                st.download_button(
                    label="📥 下载 ABC 排程结果 (Excel)",
                    data=output.getvalue(),
                    file_name="ABC_Schedule.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
    except Exception as e:
        st.error(f"读取 Excel 失败，请检查文件格式。错误信息: {e}")
