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

# Picks activos
st.subheader("🎯 Picks Activos (EV > 4%)")
try:
    picks = requests.get(f"{API_URL}/picks/latest", headers=headers, timeout=10).json()
    
    if picks["status"] == "active" and picks["picks"]:
        df = pd.DataFrame(picks["picks"])
        st.dataframe(df, use_container_width=True)
        
        # Gráfico de EV
        fig = px.bar(df, x="match", y="expected_value", 
                     title="Expected Value por Pick",
                     labels={"expected_value": "EV", "match": "Partido"})
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No hay picks activos actualmente")
except Exception as e:
    st.error(f"Error cargando picks: {e}")

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
