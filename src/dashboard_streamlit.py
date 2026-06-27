import streamlit as st
import pandas as pd
import requests
import plotly.express as px
import json
import time

API_URL = "https://survivor-ligamx-bot.onrender.com"
st.set_page_config(page_title="LigaMX Premium Dashboard", layout="wide", page_icon="📊")

@st.cache_data(ttl=60)
def fetch_stats():
    try: return requests.get(f"{API_URL}/stats", timeout=15).json()
    except: return {"total_picks":0,"roi":"0.00%","win_rate":"0.00%","avg_ev":"0.00","sharpe":"0.00"}

@st.cache_data(ttl=60)
def fetch_picks():
    try:
        res = requests.get(f"{API_URL}/picks/latest", timeout=60)
        res.raise_for_status()
        data = res.json()
        df = pd.DataFrame(data.get("picks", []))
        if not df.empty:
            for col in ["expected_value","kelly_stake","true_prob"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
        return df
    except: return pd.DataFrame()

@st.cache_data(ttl=60)
def fetch_history():
    try: return requests.get(f"{API_URL}/history?limit=50", timeout=15).json().get("records", [])
    except: return []

st.title("🏆 Survivor LigaMX | Dashboard Premium")
st.caption("Modelo Poisson + Kelly | API Cloud v2.1.0")

if st.button("🔄 Actualizar Datos"): 
    st.cache_data.clear()
    st.rerun()

stats = fetch_stats()
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("📊 Picks Totales", stats.get("total_picks", 0))
c2.metric("💰 ROI", stats.get("roi", "0.00%"))
c3.metric("🎯 Win Rate", stats.get("win_rate", "0.00%"))
c4.metric("📈 Avg EV", stats.get("avg_ev", "0.00%"))
c5.metric("⚖️ Sharpe", stats.get("sharpe", "0.00"))

st.divider()

tab1, tab2, tab3 = st.tabs(["🎯 Picks Actuales", "📜 Historial", "📤 Exportar"])

with tab1:
    df_picks = fetch_picks()
    if df_picks.empty:
        st.info("⏳ Sin picks activos ahora. El bot verificará en el próximo ciclo.")
    else:
        min_ev = st.slider("Filtrar EV Mínimo (%)", 0.0, 15.0, 4.0, 0.5)
        df_filt = df_picks[df_picks["expected_value"]*100 >= min_ev]
        if df_filt.empty:
            st.warning("⚠️ Ningún pick supera el filtro de EV seleccionado.")
        else:
            st.dataframe(df_filt, use_container_width=True, height=250)
            try:
                fig = px.bar(df_filt, x="match", y="expected_value", color="kelly_stake",
                             title="Distribución de Expected Value por Pick",
                             labels={"expected_value":"EV (%)","match":"Partido"},
                             color_continuous_scale="Viridis")
                fig.update_layout(yaxis_title="EV (%)", xaxis_tickangle=-45)
                st.plotly_chart(fig, use_container_width=True)
            except Exception as e:
                st.error(f"📊 Error en gráfico: {e}")

with tab2:
    hist = fetch_history()
    if not hist:
        st.warning("📭 Historial vacío. Los picks se registrarán tras el primer ciclo.")
    else:
        st.dataframe(pd.DataFrame(hist), use_container_width=True, height=400)

with tab3:
    st.subheader("💾 Descargar Datos")
    if not df_picks.empty:
        csv = df_picks.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Picks (CSV)", csv, "ligamx_picks.csv", "text/csv")
        json_data = json.dumps(df_picks.to_dict(orient="records"), indent=2)
        st.download_button("📥 Picks (JSON)", json_data, "ligamx_picks.json", "application/json")
    st.caption(f"🕒 Última consulta: {time.strftime('%H:%M:%S')}")
