import sys
import os

# Asegurar que Python pueda encontrar los módulos dentro de la carpeta 'src'
sys.path.append(os.path.abspath('src'))

from scraper import obtener_datos_casino
from contexto import obtener_clima_estadios
from predictor import calcular_pronosticos_avanzados
from optimizer import seleccionar_pick_survivor

def ejecutar_sistema_completo():
    print("🚀 ======================================================= 🚀")
    print("🤖   INICIANDO BOT INTELIGENTE: SURVIVOR Y PRONÓSTICOS LIGA MX   🤖")
    print("🚀 ======================================================= 🚀\n")
    
    # Paso 1: Obtener estado de mercado / momios
    obtener_datos_casino()
    print("\n------------------------------------------------------------")
    
    # Paso 2: Inyectar Clima de los Estadios
    obtener_clima_estadios()
    print("\n------------------------------------------------------------")
    
    # Paso 3: Correr el Modelo de Pronósticos de Partidos
    calcular_pronosticos_avanzados()
    print("\n------------------------------------------------------------")
    
    # Paso 4: Resolver el Pick Óptimo para el Survivor de Playdoit
    seleccionar_pick_survivor()
    
    print("\n🏁 ======================================================= 🏁")
    print("✅   PROCESO COMPLETADO SATCHEL. EL BOT ESTÁ ACTUALIZADO.   ")
    print("🏁 ======================================================= 🏁")

if __name__ == "__main__":
    ejecutar_sistema_completo()
