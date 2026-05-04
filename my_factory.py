import streamlit as st
import json
import os
import pandas as pd
import math  
from pulp import *
from streamlit_agraph import agraph, Node, Edge, Config

# ==========================================
# 1. 初始資料讀取 (唯讀藍圖，不寫入)
# ==========================================
DB_FILE = "factory_v5_4.json"

def load_base_data():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            try: d = json.load(f)
            except: d = {}
            
            defaults = {
                "materials": [], "machines": [], "recipes": [], 
                "supply": {}, "infinite_mats": [], "prices": {}, 
                "machine_limits": {}, 
                "machine_slots": {},
                "fuel_settings": {} 
            }
            for k, v in defaults.items():
                if k not in d: d[k] = v
                
            for r in d["recipes"]:
                if r.get("machine") is None or str(r.get("machine")).strip() in ["", "None"]: r["machine"] = "未指派設備"
            
            d["machines"] = [m for m in d["machines"] if m is not None and str(m).strip() not in ["", "None"]]
            d["materials"] = [m for m in d["materials"] if m is not None and str(m).strip() not in ["", "None"]]
            if any(r["machine"] == "未指派設備" for r in d["recipes"]) and "未指派設備" not in d["machines"]: d["machines"].append("未指派設備")
            
            d["machine_limits"] = {k: v for k, v in d.get("machine_limits", {}).items() if k in d["machines"]}
            for m in d["machines"]:
                if m not in d.get("machine_slots", {}): d.setdefault("machine_slots", {})[m] = 1.0
            
            d["prices"] = {k: v for k, v in d.get("prices", {}).items() if k in d["materials"]}

            return d
    return {"materials": [], "machines": [], "recipes": [], "supply": {}, "infinite_mats": [], "prices": {}, "machine_limits": {}, "machine_slots": {}, "fuel_settings": {}}

# ==========================================
# 2. 介面與全域變數配置
# ==========================================
st.set_page_config(page_title="蘋果派終末地計算機(更新至武陵1.2版本)", layout="wide")

# 初始化使用者的獨立暫存空間
if "app_data" not in st.session_state:
    st.session_state.app_data = load_base_data()
if "calc_done" not in st.session_state:
    st.session_state.calc_done = False
if "show_help" not in st.session_state:
    st.session_state.show_help = False

data = st.session_state.app_data

used_mats = set(); used_machines = set()
for r in data["recipes"]:
    used_mats.update(r.get("inputs", {}).keys())
    used_mats.update(r.get("outputs", {}).keys())
    used_machines.add(r.get("machine", ""))

# ==========================================
# ✨ 側邊欄：個人存檔與讀檔系統
# ==========================================
with st.sidebar:
    st.title("💾 存檔與讀檔")
    st.info("💡 為了互不干擾，本網頁採用獨立記憶體。如果你想保留心血，請務必在離開前下載存檔！")
    
    st.download_button(
        label="📥 下載個人存檔",
        data=json.dumps(data, indent=4, ensure_ascii=False),
        file_name="Endfield_Save_Data.json",
        mime="application/json",
        use_container_width=True,
        type="primary"
    )
    
    st.write("---")
    uploaded_file = st.file_uploader("📤 匯入個人存檔", type=["json"])
    if uploaded_file is not None:
        try:
            new_data = json.load(uploaded_file)
            st.session_state.app_data = new_data
            st.success("✅ 讀檔成功！設定已覆蓋。")
            if st.button("🔄 點擊刷新畫面", use_container_width=True):
                st.rerun()
        except:
            st.error("❌ 檔案格式錯誤")

# ==========================================
# 主畫面開始
# ==========================================
col_title, col_btn = st.columns([5, 1])
with col_title:
    st.title("🍏 蘋果派終末地計算機 (更新至武陵1.2版本)")
with col_btn:
    st.write("") 
    if st.button("📖 點我看教學", use_container_width=True):
        st.session_state.show_help = not st.session_state.show_help

if st.session_state.show_help:
    st.info("""
    ### 👷 新手管理員報到！5 分鐘學會如何使用：
    本系統會幫你精算出「最少機台、不卡線、最省電」的完美藍圖。
    
    1. **【🏗️ 設備與材料】**：先去這裡註冊你的機器和物資。還要記得設定 **上限(台)**，以及 **插槽數**（插槽數代表此設備可以同時跑幾個配方）。
    2. **【📜 配方管理】**：在這裡輸入你想做的物品配方和花費秒數。可以利用上方的 `🔍 依設備篩選` 快速尋找已有配方。
    3. **【💰 產物價值】**：(非必填) 給有價值的貨物定價，方便計算工廠每分鐘的預計總利潤。
    4. **【🚀 生產運算】**：
       - 在左側輸入你想達成的 **「產量目標」** (例如：息壤裝備原件 0.5/分)。
       - 勾選哪些資源是 **「無限資源」** (例如：清水、沉積酸)。
       - 在下方輸入你需要 **「直接扣除的發電燃料」** (系統會幫你在結算時自動扣掉)。
       - 按下 **【開始計算最佳方案】**！
    5. **看報告**：往下滑查看精確的「機台數量表」，並參考「🕸️ 產線邏輯圖」來接你的 30 速輸送帶。
    """)

tab_setup, tab_recipe, tab_price, tab_calc = st.tabs(["🏗️ 設備與材料", "📜 配方管理", "💰 產物價值設定", "🚀 生產運算"])

# === TAB 1: 設備與材料 ===
with tab_setup:
    c1, c2 = st.columns(2)
    with c1:
        st.header("設備與總量管理")
        with st.container(border=True):
            new_mac = st.text_input("註冊新設備", key="new_mac")
            if st.button("確認註冊", use_container_width=True) and new_mac and new_mac not in data["machines"]:
                data["machines"].append(new_mac)
                data["machine_limits"][new_mac] = 0.0
                data["machine_slots"][new_mac] = 1.0
                st.rerun()
        
        for mac in sorted(data["machines"]):
            cc1, cc2, cc3, cc4 = st.columns([2, 1, 1, 0.5])
            cc1.write(f"⚙️ **{mac}**")
            data["machine_limits"][mac] = cc2.number_input("上限(台)", min_value=0.0, value=float(data["machine_limits"].get(mac, 0)), step=1.0, format="%g", key=f"lim_{mac}")
            data["machine_slots"][mac] = cc3.number_input("插槽數", min_value=1.0, value=float(data.get("machine_slots", {}).get(mac, 1.0)), step=1.0, format="%g", key=f"s_{mac}")
            if mac not in used_machines:
                if cc4.button("🗑️", key=f"del_mac_{mac}"): data["machines"].remove(mac); st.rerun()
            else: cc4.markdown("⚠️", unsafe_allow_html=True)
            
        if st.button("💾 確認並套用設備設定", type="primary", use_container_width=True):
            st.success("✅ 設定已更新至暫存區！")
            
    with c2:
        st.header("材料管理")
        with st.container(border=True):
            new_mat = st.text_input("註冊新材料", key="new_mat")
            if st.button("確認註冊材料", use_container_width=True) and new_mat and new_mat not in data["materials"]:
                data["materials"].append(new_mat); st.rerun()
        for mat in sorted(data["materials"]):
            cc1, cc2 = st.columns([3, 1])
            cc1.write(f"📦 **{mat}**")
            if mat not in used_mats:
                if cc2.button("🗑️", key=f"del_mat_{mat}"): data["materials"].remove(mat); st.rerun()
            else: cc2.markdown("<span style='color:gray;'>⚠️ 使用中</span>", unsafe_allow_html=True)

# === TAB 2: 配方管理 ===
with tab_recipe:
    with st.container(border=True):
        sel_mac = st.selectbox("選擇設備", options=data["machines"])
        col_in, col_out = st.columns(2)
        with col_in:
            m_ins = st.multiselect("消耗原料", options=data["materials"])
            in_dict = {m: st.number_input(f"{m} 數量", min_value=0.0, step=1.0, format="%g", key=f"qi_{m}") for m in m_ins}
        with col_out:
            m_outs = st.multiselect("產出物", options=data["materials"])
            out_dict = {m: st.number_input(f"{m} 數量", min_value=0.0, step=1.0, format="%g", key=f"qo_{m}") for m in m_outs}
        duration = st.number_input("製作秒數", min_value=0.1, value=4.0, step=1.0, format="%g")
        if st.button("➕ 儲存配方", use_container_width=True, type="primary"):
            r_name = f"{sel_mac if sel_mac else '未指派設備'}: " + "+".join(out_dict.keys())
            data["recipes"].append({"name": r_name, "machine": sel_mac if sel_mac else "未指派設備", "inputs": in_dict, "outputs": out_dict, "time": duration, "target": 0.0})
            st.rerun()
            
    st.header("現有配方清單")
    filter_mac = st.selectbox("🔍 依設備篩選配方", options=["顯示全部"] + sorted(data["machines"]), key="filter_mac")
    
    for i, r in enumerate(data["recipes"]):
        if filter_mac != "顯示全部" and r.get("machine", "未指派設備") != filter_mac:
            continue 
                
        with st.expander(f"📜 {r['name']} ({r['time']}s)"):
            c1, c2 = st.columns(2)
            c1.write("**📥 消耗:**"); [c1.write(f"- {m}: {q}") for m, q in r.get("inputs", {}).items()]
            c2.write("**📤 產出:**"); [c2.write(f"- {m}: {q}") for m, q in r.get("outputs", {}).items()]
            if st.button("🗑️ 刪除", key=f"dr_{i}"): data["recipes"].pop(i); st.rerun()

# === TAB 3: 產物價值設定 ===
with tab_price:
    st.header("產物價值設定")
    
    c_search, c_reset = st.columns([4, 1])
    search_price = c_search.text_input("🔍 搜尋材料名稱...", key="s_price")
    
    c_reset.write("")
    c_reset.write("")
    if c_reset.button("🔄 全部歸零", use_container_width=True):
        for k in data["prices"]: 
            data["prices"][k] = 0.0
        st.rerun()
    
    for m in data["materials"]:
        if search_price and search_price.lower() not in m.lower():
            continue 
        data["prices"][m] = st.number_input(f"{m} 單價", min_value=0.0, value=float(data["prices"].get(m, 0)), step=1.0, format="%g", key=f"p_{m}")
        
    if st.button("💾 確認單價設定", type="primary"): 
        st.success("✅ 價格已更新至暫存區")

# === TAB 4: 核心運算區 ===
with tab_calc:
    col_s, col_r = st.columns([1, 2])
    
    with col_s:
        if st.button("🔄 還原至伺服器初始預設", use_container_width=True):
            st.session_state.app_data = load_base_data()
            st.rerun()
        st.write("---")
        st.subheader("設定參數")
        
        inf_mats = st.multiselect("🌊 無限資源", options=data["materials"], default=data["infinite_mats"])
        data["infinite_mats"] = inf_mats
        
        with st.expander("⛏️ 展開：有限資源上限設定", expanded=False):
            if st.button("🔄 全部歸零 (有限資源)", key="r_sup", use_container_width=True): 
                st.session_state.calc_done = False
                for k in data["supply"]: data["supply"][k] = 0.0
                st.rerun()
            
            search_sup = st.text_input("🔍 搜尋材料...", key="s_sup")
                
            input_only = set(k for r in data["recipes"] for k in r.get("inputs", {}))
            for m in sorted(list(input_only)):
                if m not in inf_mats:
                    if search_sup and search_sup.lower() not in m.lower():
                        continue
                    data["supply"][m] = st.number_input(f"{m} 供應量", min_value=0.0, value=float(data["supply"].get(m, 0.0)), step=1.0, format="%g", key=f"sup_{m}")
        
        with st.expander("🎯 展開：強制產量目標設定", expanded=False):
            if st.button("🔄 全部歸零 (產量目標)", key="r_tar", use_container_width=True):
                st.session_state.calc_done = False
                for r in data["recipes"]: r["target"] = 0.0
                st.rerun()
            
            search_tar = st.text_input("🔍 搜尋配方名稱...", key="s_tar")
                
            for i, r in enumerate(data["recipes"]):
                if search_tar and search_tar.lower() not in r['name'].lower():
                    continue
                data["recipes"][i]["target"] = st.number_input(f"{r['name']} 需求", min_value=0.0, value=float(r.get("target", 0.0)), step=1.0, format="%g", key=f"t_{i}")

        with st.expander("⚡ 展開：直接扣除發電燃料", expanded=False):
            st.caption("💡 直接輸入你想從最終產物裡扣除多少個燃料。")
            if st.button("🔄 全部歸零 (燃料扣除)", key="r_fuel", use_container_width=True):
                data["fuel_settings"] = {}
                st.session_state.calc_done = False
                st.rerun()
            
            existing_fuels = [f for f in data.get("fuel_settings", {}).keys() if f in data["materials"]]
            sel_fuels = st.multiselect("選擇要扣除的物資 (可多選)", options=data["materials"], default=existing_fuels)
            
            new_fuel_settings = {}
            if sel_fuels:
                for f in sel_fuels:
                    old_val = data.get("fuel_settings", {}).get(f, 0.0)
                    new_val = st.number_input(f"{f} 每分鐘扣除量", min_value=0.0, value=float(old_val), step=1.0, format="%g", key=f"fuel_{f}")
                    if new_val > 0:
                        new_fuel_settings[f] = new_val
            
            data["fuel_settings"] = new_fuel_settings

    with col_r:
        st.header("🚀 最佳化工廠方案")
        if st.button("開始計算最佳方案", type="primary", use_container_width=True):
            st.session_state.calc_done = True
            
        if st.session_state.calc_done:
            prob = LpProblem("FactoryOptim", LpMaximize)
            
            R_vars = [LpVariable(f"R{i}", lowBound=0) for i in range(len(data["recipes"]))]
            S_vars = [LpVariable(f"S{i}", lowBound=0, cat='Integer') for i in range(len(data["recipes"]))]
            M_vars = {mac: LpVariable(f"M_{mac}", lowBound=0, cat='Integer') for mac in data["machines"]}
            sell_vars = {m: LpVariable(f"Sell_{m}", lowBound=0) for m in data["materials"]}
            
            for i in range(len(data["recipes"])):
                prob += R_vars[i] <= S_vars[i]

            for mac in data["machines"]:
                mac_slots = int(max(1.0, float(data.get("machine_slots", {}).get(mac, 1.0))))
                recipes_for_mac = [S_vars[i] for i, r in enumerate(data["recipes"]) if r.get("machine") == mac]
                if recipes_for_mac:
                    prob += lpSum(recipes_for_mac) <= M_vars[mac] * mac_slots
                else:
                    prob += M_vars[mac] == 0
                    
                limit = data["machine_limits"].get(mac, 0)
                if limit > 0: prob += M_vars[mac] <= limit

            for m in data["materials"]:
                net = lpSum([R_vars[i] * (60/r["time"]) * r.get("outputs", {}).get(m, 0) for i, r in enumerate(data["recipes"])]) \
                    - lpSum([R_vars[i] * (60/r["time"]) * r.get("inputs", {}).get(m, 0) for i, r in enumerate(data["recipes"])])
                sup = 999999 if m in data["infinite_mats"] else data["supply"].get(m, 0)
                prob += net + sup - sell_vars[m] >= 0

            for i, r in enumerate(data["recipes"]):
                if r.get("target", 0) > 0 and r.get("outputs"):
                    main_qty = list(r["outputs"].values())[0]
                    prob += R_vars[i] * (60/r["time"]) * main_qty >= r["target"]
            
            revenue = lpSum([sell_vars[m] * data["prices"].get(m, 0) for m in data["materials"]])
            machine_penalty = lpSum([M_vars[mac] * 0.0001 for mac in data["machines"]])
            slot_penalty = lpSum([S_vars[i] * 0.00001 for i in range(len(data["recipes"]))])
            prob += revenue - machine_penalty - slot_penalty

            prob.solve(PULP_CBC_CMD(msg=0))
            if LpStatus[prob.status] == 'Optimal':
                st.success("✅ 計算成功！")
                
                st.subheader("📊 實體機台部署表")
                res = []
                for mac in data["machines"]:
                    m_count = int(value(M_vars[mac]))
                    if m_count > 0:
                        mac_slots = int(max(1.0, float(data.get("machine_slots", {}).get(mac, 1.0))))
                        r_list = []
                        for i, r in enumerate(data["recipes"]):
                            if r["machine"] == mac and value(S_vars[i]) > 0:
                                assigned_s = int(value(S_vars[i]))
                                load_pct = round((value(R_vars[i]) / assigned_s) * 100, 1)
                                r_list.append(f"{r['name']}(分 {assigned_s} 槽, 負載 {load_pct}%)")
                        
                        res.append({
                            "實體設備": mac, 
                            "總台數": f"{m_count}台 (共 {m_count * mac_slots} 槽)", 
                            "槽位設定與降頻指南": " / ".join(r_list)
                        })
                st.table(pd.DataFrame(res))
                
                c1, c2 = st.columns(2)
                c1.subheader("📦 最終淨產出")
                
                fuel_dict = data.get("fuel_settings", {})
                sales = []
                shortages = []
                deadlocks = [] 
                final_profit = value(revenue)

                for m in data["materials"]:
                    val = value(sell_vars[m])
                    if m in fuel_dict:
                        fuel_req = fuel_dict[m]
                        val -= fuel_req
                        final_profit -= fuel_req * data["prices"].get(m, 0)
                        if val < -0.001:
                            shortages.append({"mat": m, "req": fuel_req, "short": abs(val)})
                    
                    if val > 0.001:
                        sales.append({"材料": m, "最終淨產出/分": round(val, 2)})
                        if data["prices"].get(m, 0) == 0:
                            deadlocks.append(m)
                    elif val < -0.001:
                        sales.append({"材料": m, "最終淨產出/分": round(val, 2)})
                        
                c1.table(pd.DataFrame(sales))
                
                if deadlocks:
                    st.warning(f"💀 【產線卡死風險】副產物 **{', '.join(deadlocks)}** 大量溢出，且無經濟價值 (單價為0)！請記得在遊戲末端接上『碎石機』或大型儲存槽將其消耗，否則產線不久後將會卡死停擺。")
                
                c2.subheader("⚡ 燃料扣除報告")
                if fuel_dict:
                    fuel_table = [{"燃料": k, "扣除/分": v} for k, v in fuel_dict.items()]
                    c2.table(pd.DataFrame(fuel_table))
                    for s in shortages:
                        st.error(f"⚠️ 【缺料警告】發電需要扣除 {s['req']}/分的 {s['mat']}，尚缺 {round(s['short'], 2)} 個！")
                else:
                    c2.info("目前不需扣除任何燃料。")
                        
                st.metric("預計總利潤 (/分)", f"${final_profit:,.2f}")

                st.write("---")
                st.subheader("🕸️ 產線邏輯圖 (可自由拖曳)")
                st.caption("💡 管線上的數字代表流量與所需的 **30速輸送帶數量**，幫助您規劃接口。（⚠️ **您可以隨意拖曳節點來排版，不會回彈！**）")
                
                nodes = []; edges = []; created = set()
                def get_or_add_node(node_id, label, color, shape="dot"):
                    if node_id not in created:
                        nodes.append(Node(id=node_id, label=label, size=25, color=color, shape=shape))
                        created.add(node_id)
                    return node_id

                has_flow = False
                for i, r in enumerate(data["recipes"]):
                    vS = int(value(S_vars[i]))
                    vR = value(R_vars[i])
                    if vS > 0:
                        has_flow = True
                        
                        load_pct = round((vR / vS) * 100, 1)
                        r_id = f"R_{i}"
                        r_label = f"⚙️ {r['name']}\n(分 {vS} 槽, 負載 {load_pct}%)"
                        get_or_add_node(r_id, r_label, "#FFD700", "box")
                        
                        mac_slots = int(max(1.0, float(data.get("machine_slots", {}).get(r["machine"], 1.0))))
                        recipe_machines = math.ceil(vS / mac_slots)
                        
                        for mat, qty in r.get("inputs", {}).items():
                            m_id = f"M_{mat}"
                            
                            is_island = True
                            for recipe_check in data["recipes"]:
                                if mat in recipe_check.get("outputs", {}):
                                    is_island = False
                                    break
                            
                            m_label = f"📦 {mat}"
                            if is_island:
                                m_label += " (⚠️ 孤島材料)" 
                            
                            get_or_add_node(m_id, m_label, "#87CEEB", "ellipse")
                            flow_in = qty * vR * (60.0 / r["time"])
                            belts_in = max(math.ceil(flow_in / 30.0), recipe_machines)
                            edges.append(Edge(source=m_id, target=r_id, label=f"{flow_in:g}/分 ({belts_in}條帶)"))
                            
                        for mat, qty in r.get("outputs", {}).items():
                            m_id = f"M_{mat}"
                            
                            is_island = True
                            for recipe_check in data["recipes"]:
                                if mat in recipe_check.get("outputs", {}):
                                    is_island = False
                                    break
                                    
                            m_label = f"📦 {mat}"
                            if is_island:
                                m_label += " (⚠️ 孤島材料)" 
                                
                            get_or_add_node(m_id, m_label, "#90EE90", "ellipse")
                            flow_out = qty * vR * (60.0 / r["time"])
                            belts_out = max(math.ceil(flow_out / 30.0), recipe_machines)
                            edges.append(Edge(source=r_id, target=m_id, label=f"{flow_out:g}/分 ({belts_out}條帶)"))

                if has_flow:
                    config = Config(
                        width="100%", 
                        height=750, 
                        directed=True, 
                        physics=False,  
                        zoom=True, 
                        pan=True, 
                        nodeHighlightBehavior=True
                    )
                    agraph(nodes=nodes, edges=edges, config=config)
                else:
                    st.warning("目前沒有產生任何物流。")
            else:
                st.error("❌ 無法滿足目標，請檢查資源與設備上限。")