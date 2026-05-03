import streamlit as st
import json
import os
import pandas as pd
import math  # ✨ 新增數學模組用來計算無條件進位
from pulp import *

# 🛠️ 防崩潰機制：確保有安裝 agraph
try:
    from streamlit_agraph import agraph, Node, Edge, Config
except ImportError:
    st.error("🚨 缺少核心繪圖套件！請先關閉程式，打開終端機 (cmd) 輸入：\n\n`pip install streamlit-agraph`\n\n安裝完成後再重新啟動！")
    st.stop()

# ==========================================
# 1. 資料存取與自動修復系統
# ==========================================
DB_FILE = "factory_v5_4.json"

def load_data():
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

            save_data(d)
            return d
    return {"materials": [], "machines": [], "recipes": [], "supply": {}, "infinite_mats": [], "prices": {}, "machine_limits": {}, "machine_slots": {}, "fuel_settings": {}}

def save_data(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# ==========================================
# 2. 介面與全域變數配置
# ==========================================
st.set_page_config(page_title="專業工廠規劃器 V8.2", layout="wide")

if "calc_done" not in st.session_state:
    st.session_state.calc_done = False

data = load_data()

used_mats = set(); used_machines = set()
for r in data["recipes"]:
    used_mats.update(r.get("inputs", {}).keys())
    used_mats.update(r.get("outputs", {}).keys())
    used_machines.add(r.get("machine", ""))

st.title("🏭 專業工廠規劃器 V8.2 (防卡死與管線版)")

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
                save_data(data); st.rerun()
        
        st.caption("💡 提示：若為『集成製造站』，請將插槽數設為 4。普通設備維持 1。")
        for mac in sorted(data["machines"]):
            cc1, cc2, cc3, cc4 = st.columns([2, 1, 1, 0.5])
            cc1.write(f"⚙️ **{mac}**")
            data["machine_limits"][mac] = cc2.number_input("上限(台)", min_value=0.0, value=float(data["machine_limits"].get(mac, 0)), step=1.0, format="%g", key=f"lim_{mac}")
            data["machine_slots"][mac] = cc3.number_input("插槽數", min_value=1.0, value=float(data.get("machine_slots", {}).get(mac, 1.0)), step=1.0, format="%g", key=f"s_{mac}")
            if mac not in used_machines:
                if cc4.button("🗑️", key=f"del_mac_{mac}"): data["machines"].remove(mac); save_data(data); st.rerun()
            else: cc4.markdown("⚠️", unsafe_allow_html=True)
            
        if st.button("💾 儲存設備設定", type="primary", use_container_width=True):
            save_data(data)
            st.success("✅ 設備上限與插槽設定已永久儲存！")
            
    with c2:
        st.header("材料管理")
        with st.container(border=True):
            new_mat = st.text_input("註冊新材料", key="new_mat")
            if st.button("確認註冊材料", use_container_width=True) and new_mat and new_mat not in data["materials"]:
                data["materials"].append(new_mat); save_data(data); st.rerun()
        for mat in sorted(data["materials"]):
            cc1, cc2 = st.columns([3, 1])
            cc1.write(f"📦 **{mat}**")
            if mat not in used_mats:
                if cc2.button("🗑️", key=f"del_mat_{mat}"): data["materials"].remove(mat); save_data(data); st.rerun()
            else: cc2.markdown("<span style='color:gray;'>⚠️ 使用中</span>", unsafe_allow_html=True)

# === TAB 2, 3 維持 ===
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
            save_data(data); st.rerun()
    st.header("現有配方清單")
    for i, r in enumerate(data["recipes"]):
        with st.expander(f"📜 {r['name']} ({r['time']}s)"):
            c1, c2 = st.columns(2)
            c1.write("**📥 消耗:**"); [c1.write(f"- {m}: {q}") for m, q in r.get("inputs", {}).items()]
            c2.write("**📤 產出:**"); [c2.write(f"- {m}: {q}") for m, q in r.get("outputs", {}).items()]
            if st.button("🗑️ 刪除", key=f"dr_{i}"): data["recipes"].pop(i); save_data(data); st.rerun()

with tab_price:
    for m in data["materials"]:
        data["prices"][m] = st.number_input(f"{m} 單價", min_value=0.0, value=float(data["prices"].get(m, 0)), step=1.0, format="%g", key=f"p_{m}")
    if st.button("💾 儲存價格設定", type="primary"): save_data(data); st.success("已儲存")

# === TAB 4: 核心運算區 ===
with tab_calc:
    col_s, col_r = st.columns([1, 2])
    
    with col_s:
        st.button("🔴 儲存所有設定", on_click=lambda: save_data(data), use_container_width=True, type="primary")
        st.write("---")
        st.subheader("設定參數")
        
        inf_mats = st.multiselect("🌊 無限資源", options=data["materials"], default=data["infinite_mats"])
        data["infinite_mats"] = inf_mats
        
        with st.expander("⛏️ 展開：有限資源上限設定", expanded=False):
            if st.button("🔄 全部歸零 (有限資源)", key="r_sup", use_container_width=True): 
                st.session_state.calc_done = False
                for k in data["supply"]: data["supply"][k] = 0.0
                save_data(data); st.rerun()
                
            input_only = set(k for r in data["recipes"] for k in r.get("inputs", {}))
            for m in sorted(list(input_only)):
                if m not in inf_mats:
                    data["supply"][m] = st.number_input(f"{m} 供應量", min_value=0.0, value=float(data["supply"].get(m, 0.0)), step=1.0, format="%g", key=f"sup_{m}")
        
        with st.expander("🎯 展開：強制產量目標設定", expanded=False):
            if st.button("🔄 全部歸零 (產量目標)", key="r_tar", use_container_width=True):
                st.session_state.calc_done = False
                for r in data["recipes"]: r["target"] = 0.0
                save_data(data); st.rerun()
                
            for i, r in enumerate(data["recipes"]):
                data["recipes"][i]["target"] = st.number_input(f"{r['name']} 需求", min_value=0.0, value=float(r.get("target", 0.0)), step=1.0, format="%g", key=f"t_{i}")

        with st.expander("⚡ 展開：直接扣除發電燃料", expanded=False):
            st.caption("💡 直接輸入你想從最終產物裡扣除多少個燃料。")
            if st.button("🔄 全部歸零 (燃料扣除)", key="r_fuel", use_container_width=True):
                data["fuel_settings"] = {}
                st.session_state.calc_done = False
                save_data(data); st.rerun()
            
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
                deadlocks = [] # ✨ 記錄死鎖風險物資
                final_profit = value(revenue)

                # 做帳扣除與死鎖偵測
                for m in data["materials"]:
                    val = value(sell_vars[m])
                    if m in fuel_dict:
                        fuel_req = fuel_dict[m]
                        val -= fuel_req
                        final_profit -= fuel_req * data["prices"].get(m, 0)
                        if val < -0.001:
                            shortages.append({"mat": m, "req": fuel_req, "short": abs(val)})
                    
                    if val > 0.001:
                        # ✨ 特色功能 2：計算末端需要的輸送帶數量
                        req_belts = math.ceil(val / 30.0)
                        sales.append({"材料": m, "最終淨產出/分": round(val, 2), "所需輸送帶(30/分)": f"{req_belts} 條"})
                        
                        # ✨ 特色功能 3：偵測是否無處安放且單價為 0
                        if data["prices"].get(m, 0) == 0:
                            deadlocks.append(m)
                    elif val < -0.001:
                        sales.append({"材料": m, "最終淨產出/分": round(val, 2), "所需輸送帶(30/分)": "-"})
                        
                c1.table(pd.DataFrame(sales))
                
                # ✨ 跳出死鎖警告
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

                # ==========================================
                # 🕸️ 產線邏輯拖曳圖 (加上輸送帶數量計算)
                # ==========================================
                st.write("---")
                st.subheader("🕸️ 產線邏輯圖 (可自由拖曳)")
                st.caption("💡 管線上的數字代表流量與所需的 **30速輸送帶數量**，幫助您規劃接口。")
                
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
                        
                        # ✨ 在圖表管線上標註「需幾條帶子」
                        for mat, qty in r.get("inputs", {}).items():
                            m_id = f"M_{mat}"
                            get_or_add_node(m_id, f"📦 {mat}", "#87CEEB", "ellipse")
                            flow_in = qty * vR * (60.0 / r["time"])
                            belts_in = math.ceil(flow_in / 30.0)
                            edges.append(Edge(source=m_id, target=r_id, label=f"{flow_in:g}/分 ({belts_in}條帶)"))
                            
                        for mat, qty in r.get("outputs", {}).items():
                            m_id = f"M_{mat}"
                            get_or_add_node(m_id, f"📦 {mat}", "#90EE90", "ellipse")
                            flow_out = qty * vR * (60.0 / r["time"])
                            belts_out = math.ceil(flow_out / 30.0)
                            edges.append(Edge(source=r_id, target=m_id, label=f"{flow_out:g}/分 ({belts_out}條帶)"))

                if has_flow:
                    config = Config(width="100%", height=750, directed=True, physics=False, hierarchical=True, zoom=True, pan=True, nodeHighlightBehavior=True)
                    agraph(nodes=nodes, edges=edges, config=config)
                else:
                    st.warning("目前沒有產生任何物流。")
            else:
                st.error("❌ 無法滿足目標，請檢查資源與設備上限。")