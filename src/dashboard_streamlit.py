import streamlit as st
import pandas as pd
import requests
import time

st.set_page_config(page_title="Survivor LigaMX Dashboard", layout="wide")
API_URL = "https://survivor-ligamx-bot.onrender.com"

def fetch_picks():
    try:
        res = requests.get(f"{API_URL}/picks/latest", timeout=60)
        res.raise_for_status()
        data = res.json()
        if data.get("status") != "active" or not data.get("picks"):
            return pd.DataFrame()
        return pd.DataFrame(data["picks"])
    except Exception as e:
        st.error(f"❌ Error conectando a API: {e}")
        return pd.DataFrame()

st.title("📊 Survivor LigaMX - Panel Interactivo")
st.caption("Datos en tiempo real desde Render Cloud | Modelo Poisson + Kelly Fraccionario")

if st.button("🔄 Actualizar Datos"):
    st.rerun()

with st.spinner("⏳ Despertando API y consultando datos... (puede tardar ~40s)"):
    df = fetch_picks()

if df.empty:
    st.warning("⏳ No hay picks válidos en este momento (EV > 4% y Kelly > 0%).")
    st.info("💡 La API está activa. Los picks aparecerán cuando el mercado los genere.")
else:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("🎯 Picks Totales", len(df))
    col2.metric("📈 EV Promedio", f"{df['expected_value'].mean()*100:.2f}%")
    col3.metric("🧠 Prob Real Prom", f"{df['true_prob'].mean()*100:.1f}%")
    col4.metric("💰 Kelly Prom", f"{df['kelly_stake'].mean():.2f}%")

    st.sidebar.header("🔍 Filtros")
    min_ev = st.sidebar.slider("EV Mínimo (%)", 0.0, 10.0, 4.0, 0.5)
    min_kelly = st.sidebar.slider("Stake Kelly Mínimo (%)", 0.0, 5.0, 0.0, 0.1)

    df_filtered = df[(df['expected_value']*100 >= min_ev) & (df['kelly_stake'] >= min_kelly)]

    if not df_filtered.empty:
        st.dataframe(df_filtered, use_container_width=True, height=400)
        st.bar_chart(df_filtered.set_index("match")["expected_value"] * 100)
    else:
        st.info("Ningún pick cumple los filtros seleccionados.")

st.caption(f"🔄 Última consulta: {time.strftime('%H:%M:%S')}")
