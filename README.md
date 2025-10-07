# Holter ECG con Reducción de Artefactos por Movimiento

## 📋 Contexto del Proyecto

Sistema de monitoreo ECG portátil (Holter) que captura señales cardíacas de 3 derivaciones junto con datos de un acelerómetro para detectar y minimizar artefactos causados por movimiento corporal del paciente.

## 🎯 Problema

En dispositivos Holter ambulatorios, el movimiento del paciente introduce ruido en la señal ECG que dificulta el diagnóstico médico. Los artefactos de movimiento pueden enmascarar eventos cardíacos importantes o generar falsos positivos.

## 💡 Solución

Implementación de un sistema híbrido que:

1. **Captura simultánea**: Registra ECG (3 derivaciones) + datos de acelerómetro (ADXL345)
2. **Detección de movimiento**: Utiliza la magnitud de aceleración para identificar segmentos con movimiento significativo
3. **Filtrado adaptativo**: Aplica transformada Wavelet (Daubechies db4) con umbrales variables según la intensidad del movimiento detectado
4. **Procesamiento en tiempo real**: Sistema híbrido que guarda datos crudos como backup y genera señal filtrada simultáneamente

## 🔬 Tecnologías

- **Hardware**: XSpaceBio V10 (AD8232 ECG), ADXL345 (acelerómetro I2C)
- **Algoritmo**: Transformada Wavelet Discreta con umbralización adaptativa (MAD)
- **Comunicación**: UDP sobre WiFi (100 Hz)
- **Procesamiento**: Python con PyWavelets, ventanas deslizantes con overlap

---

## 🏗️ Arquitectura del Código

### **Arduino (main.cpp)**
[Setup]
├── Inicializa XSpaceBio
├── Conecta WiFi y UDP
├── Activa sensores AD8232 (ECG)
└── Configura ADXL345 (I2C, ±4g, 100Hz)
[Loop - 100Hz]
├── Lee 2 derivaciones ECG (AD8232)
├── Calcula 3ra derivación (Einthoven)
├── Lee acelerómetro (X, Y, Z)
├── Calcula magnitud vectorial
└── Envía paquete UDP: "timestamp,ECG_I,ECG_II,ECG_III,AccX,AccY,AccZ,AccMag"

### **Python (holter_hybrid_system.py)**

#### **Arquitectura de 3 hilos:**
[Hilo 1: UDPReceiver]
└── Escucha puerto UDP → Parsea datos → Queue
[Hilo 2: Main Processing Loop]
├── Obtiene datos de Queue
├── Guarda dato crudo INMEDIATAMENTE en CSV
├── Agrega dato a buffer circular
└── Si buffer completo (500 muestras):
└── Llama a procesamiento Wavelet
[Hilo 3: WaveletProcessor]
├── Calcula umbral de movimiento (percentil 75)
├── Detecta segmentos con movimiento
├── Para cada derivación ECG:
│   ├── Descomposición Wavelet (5 niveles)
│   ├── Calcula umbral MAD
│   ├── Aplica thresholding adaptativo:
│   │   ├── Movimiento alto → umbral x2.5
│   │   └── Movimiento bajo → umbral x1.0
│   └── Reconstruye señal filtrada
├── Guarda ventana filtrada en CSV
└── Desliza buffer (overlap 50%)

#### **Clases principales:**

- **`HolterConfig`**: Parámetros centralizados (frecuencia, wavelet, umbrales)
- **`UDPReceiver`**: Recepción asíncrona de datos vía UDP
- **`WaveletProcessor`**: Filtrado adaptativo con ventanas deslizantes
- **`HolterSystem`**: Orquestador principal del sistema

#### **Algoritmo Wavelet:**

1. **Descomposición**: Señal ECG → Aproximación + 5 niveles de detalles
2. **Umbralización**: 
   - MAD (Median Absolute Deviation) para estimar ruido
   - Umbral base: `σ * sqrt(2 * ln(N))`
   - Factor adaptativo según movimiento detectado
3. **Reconstrucción**: Coeficientes filtrados → Señal limpia

#### **Ventanas deslizantes:**
Ventana 1: [0-500]      → Procesa y guarda [0-250]
Ventana 2: [250-750]    → Procesa y guarda [250-500]
Ventana 3: [500-1000]   → Procesa y guarda [500-750]
...
*Overlap de 50% para evitar efectos de borde*

---

## 📦 Hardware Requerido

- XSpaceBio V10 Board
- Sensor ADXL345 (acelerómetro I2C)
- PC en red WiFi

## 🔌 Conexiones ADXL345
ADXL345  →  XSpaceBio
VCC      →  3.3V
GND      →  GND
SDA      →  SDA (GPIO21)
SCL      →  SCL (GPIO22)
CS       →  3.3V
SDO      →  GND

## ⚙️ Instalación

### Arduino:
1. Instalar librerías: `Adafruit ADXL345`, `Adafruit Unified Sensor`
2. Modificar WiFi en `main.cpp`:
```cpp
   XSerial.Wifi_init("TuWiFi", "password");

Modificar IP en main.cpp:

cpp   XSerial.UDP_Connect("TU_IP_PC", 55000);

Flashear a XSpaceBio

Python:
bashpip install numpy pandas PyWavelets
🚀 Uso

Encender XSpaceBio (se conecta automáticamente)
Ejecutar en PC:

bash   python holter_hybrid_system.py

Detener: Ctrl+C

📂 Salida
El sistema genera dos archivos CSV por sesión:
Holter_Data/Session_YYYYMMDD_HHMMSS/
├── raw_data.csv       # Señales crudas sin procesar (backup completo)
└── filtered_data.csv  # Señales ECG con artefactos de movimiento reducidos
Formato raw_data.csv:
timestamp,ECG_I,ECG_II,ECG_III,AccX,AccY,AccZ,AccMag
1000,0.523,0.612,0.089,0.12,0.05,9.81,9.82
1010,0.531,0.619,0.088,0.11,0.06,9.80,9.81
Formato filtered_data.csv:
timestamp,ECG_I_filt,ECG_II_filt,ECG_III_filt
5000,0.520,0.610,0.090
5010,0.528,0.617,0.089
🎛️ Configuración
Parámetros principales en holter_hybrid_system.py:
pythonclass HolterConfig:
    UDP_IP = "192.168.4.101"              # IP de tu PC
    UDP_PORT = 55000                      # Puerto UDP
    SAMPLE_RATE = 100                     # Hz
    WAVELET_TYPE = 'db4'                  # Daubechies 4
    DECOMPOSITION_LEVEL = 5               # Niveles wavelet
    WINDOW_SIZE = 500                     # Ventana procesamiento (muestras)
    OVERLAP = 250                         # Overlap 50%
    ACC_THRESHOLD_PERCENTILE = 75         # Umbral movimiento
    THRESHOLD_MULTIPLIER_HIGH_MOTION = 2.5
    THRESHOLD_MULTIPLIER_LOW_MOTION = 1.0
✅ Verificación

Consola Arduino debe mostrar: SYSTEM_READY
Consola Python debe mostrar: [UDP] Escuchando en...
Progreso cada 5 segundos con número de muestras

⚠️ Troubleshooting
No recibe datos:

Verificar que PC e IP coincidan en ambos códigos
Confirmar que están en la misma red WiFi
Revisar firewall de Windows (permitir puerto 55000 UDP)

ADXL345 no detectado:

Verificar conexiones I2C (SDA/SCL)
Confirmar voltaje 3.3V (NO 5V)
Probar scanner I2C en Arduino


Aplicación: Monitoreo cardíaco ambulatorio de larga duración con calidad diagnóstica mejorada.
Desarrollado para: Proyecto de Instrumentación Biomédica - PUCP