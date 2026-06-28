import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import os

st.set_page_config(page_title="Survivor LigaMX Premium", layout="wide")
st.title("📊 Survivor LigaMX - Dashboard Premium")

API_URL = "https://survivor-ligamx-bot.onrender.com"
API_KEY = os.getenv("API_KEY", "survivor-ligamx-premium-2026")
headers = {"X-API-Key": API_KEY}

# Métricas principales
st.subheader("📈 Métricas de Rendimiento")
try:
    stats = requests.get(f"{API_URL}/stats", headers=headers, timeout=10).json()
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Picks", stats["total_picks"])
    col2.metric("Wins", stats["wins"])
    col3.metric("Win Rate", f"{stats['win_rate']:.1f}%")
    col4.metric("Total Profit", f"{stats['total_profit']:.2f}")
    
    st.success(f"✅ ROI Promedio: {stats['avg_profit']:.4f} por pick")
except Exception as e:
    st.error(f"Error cargando métricas: {e}")

# Pick de Survivor (modelo real)
st.subheader("🎯 Pick de Survivor (mayor prob. de NO perder)")
try:
    surv = requests.get(f"{API_URL}/survivor", timeout=60).json()
    pick = surv.get("pick_survivor")
    if pick:
        st.success(
            f"**{pick['equipo']}** ({pick['condicion']} vs {pick['rival']}) — "
            f"no perder **{pick['no_perder_pct']}%**"
        )
        st.caption(f"Fuente: {surv.get('fuente_datos')} · {surv.get('decision')}")
    else:
        st.info("No hay pick de Survivor disponible (faltan fixtures o datos).")
except Exception as e:
    st.error(f"Error cargando pick de Survivor: {e}")

# Predicciones del modelo (ESPN + Poisson)
st.subheader("🔮 Predicciones del modelo (ESPN + Poisson)")
try:
    pred = requests.get(f"{API_URL}/predicciones", timeout=60).json()
    pronos = pred.get("pronosticos", [])

    if pronos:
        df = pd.DataFrame(pronos)
        cols = [c for c in [
            "local", "visitante", "pick_1x2",
            "prob_local_pct", "prob_empate_pct", "prob_visitante_pct",
            "pick_ou", "pick_btts", "marcador_mas_probable",
        ] if c in df.columns]
        st.dataframe(df[cols] if cols else df, use_container_width=True)

        # Gráfico: probabilidad del pick por partido
        if {"prob_local_pct", "prob_visitante_pct"}.issubset(df.columns):
            df["partido"] = df["local"] + " vs " + df["visitante"]
            fig = px.bar(
                df, x="partido", y="prob_local_pct",
                title="Probabilidad de Local por partido (%)",
                labels={"prob_local_pct": "P(Local) %", "partido": "Partido"},
            )
            st.plotly_chart(fig, use_container_width=True)
        st.caption(f"Fuente: {pred.get('fuente_datos')} · {pred.get('decision')}")
    else:
        st.info("No hay predicciones disponibles actualmente")
except Exception as e:
    st.error(f"Error cargando predicciones: {e}")

# Historial
st.subheader("📜 Historial de Picks")
try:
    history = requests.get(f"{API_URL}/history?limit=20", headers=headers, timeout=10).json()
    
    if history["records"]:
        df_hist = pd.DataFrame(history["records"])
        st.dataframe(df_hist, use_container_width=True)
        
        # Gráfico de profit/loss
        if "profit_loss" in df_hist.columns:
            fig2 = px.line(df_hist, y="profit_loss", 
                          title="Evolución de Profit/Loss",
                          labels={"profit_loss": "P/L"})
            st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("No hay historial disponible")
except Exception as e:
    st.error(f"Error cargando historial: {e}")

st.caption(f"Última actualización: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}")
