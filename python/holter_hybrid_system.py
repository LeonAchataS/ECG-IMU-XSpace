import socket
import numpy as np
import pandas as pd
import pywt
from datetime import datetime
import threading
import queue
import os
import time

# =============================================================================
# CONFIGURACIÓN GLOBAL
# =============================================================================

class HolterConfig:
    """Configuración centralizada del sistema Holter"""
    
    # Red UDP
    UDP_IP = "192.168.4.101"  # IP de tu PC
    UDP_PORT = 55000
    
    # Frecuencia de muestreo
    SAMPLE_RATE = 100  # Hz
    
    # Procesamiento Wavelet
    WAVELET_TYPE = 'db4'
    DECOMPOSITION_LEVEL = 5
    WINDOW_SIZE = 500  # muestras (5 segundos a 100Hz)
    OVERLAP = 250      # 50% overlap
    
    # Detección de movimiento
    ACC_THRESHOLD_PERCENTILE = 75
    THRESHOLD_MULTIPLIER_HIGH_MOTION = 2.5
    THRESHOLD_MULTIPLIER_LOW_MOTION = 1.0
    
    # Archivos de salida
    OUTPUT_FOLDER = r'C:\Users\Lenovo\OneDrive\Desktop\PUCP\Instru\Holter_Data'
    
    @staticmethod
    def create_session_folder():
        """Crea carpeta para la sesión actual"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        session_folder = os.path.join(HolterConfig.OUTPUT_FOLDER, f"Session_{timestamp}")
        os.makedirs(session_folder, exist_ok=True)
        return session_folder


# =============================================================================
# FUNCIONES DE PROCESAMIENTO WAVELET
# =============================================================================

def calculate_acceleration_magnitude(acc_x, acc_y, acc_z):
    """Calcula magnitud vectorial de aceleración"""
    return np.sqrt(acc_x**2 + acc_y**2 + acc_z**2)


def detect_motion_segments(acc_magnitude, threshold):
    """Detecta segmentos con movimiento significativo"""
    return acc_magnitude > threshold


def apply_wavelet_thresholding(coeffs, threshold_value, mode='soft'):
    """Aplica umbral a coeficientes wavelet"""
    return pywt.threshold(coeffs, threshold_value, mode=mode)


def adaptive_wavelet_filter(ecg_signal, motion_mask, wavelet='db4', level=5):
    """
    Aplica filtrado wavelet adaptativo basado en detección de movimiento.
    Versión optimizada para procesamiento en tiempo real.
    """
    
    # Descomposición wavelet
    coeffs = pywt.wavedec(ecg_signal, wavelet, level=level)
    
    # Calcular umbral base usando MAD
    sigma = np.median(np.abs(coeffs[-1])) / 0.6745
    threshold_base = sigma * np.sqrt(2 * np.log(len(ecg_signal)))
    
    # Procesar coeficientes
    coeffs_filtered = [coeffs[0]]  # Mantener aproximación
    
    for i in range(1, len(coeffs)):
        detail_coeffs = coeffs[i]
        level_factor = 1.5 ** (len(coeffs) - i)
        
        # Umbral adaptativo según movimiento
        if np.mean(motion_mask) > 0.3:
            threshold = threshold_base * HolterConfig.THRESHOLD_MULTIPLIER_HIGH_MOTION * level_factor
        else:
            threshold = threshold_base * HolterConfig.THRESHOLD_MULTIPLIER_LOW_MOTION * level_factor
        
        detail_filtered = apply_wavelet_thresholding(detail_coeffs, threshold, mode='soft')
        coeffs_filtered.append(detail_filtered)
    
    # Reconstrucción
    ecg_filtered = pywt.waverec(coeffs_filtered, wavelet)
    
    # Ajustar longitud
    if len(ecg_filtered) > len(ecg_signal):
        ecg_filtered = ecg_filtered[:len(ecg_signal)]
    elif len(ecg_filtered) < len(ecg_signal):
        ecg_filtered = np.pad(ecg_filtered, (0, len(ecg_signal) - len(ecg_filtered)), 'edge')
    
    return ecg_filtered


# =============================================================================
# CLASE: RECEPTOR UDP
# =============================================================================

class UDPReceiver:
    """Receptor UDP que captura datos en tiempo real"""
    
    def __init__(self, data_queue):
        self.data_queue = data_queue
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((HolterConfig.UDP_IP, HolterConfig.UDP_PORT))
        self.sock.settimeout(1.0)
        self.running = False
        
    def start(self):
        """Inicia la recepción de datos"""
        self.running = True
        self.thread = threading.Thread(target=self._receive_loop, daemon=True)
        self.thread.start()
        print(f"[UDP] Escuchando en {HolterConfig.UDP_IP}:{HolterConfig.UDP_PORT}")
    
    def _receive_loop(self):
        """Loop principal de recepción"""
        while self.running:
            try:
                data, addr = self.sock.recvfrom(1024)
                message = data.decode('utf-8').strip()
                
                # Ignorar mensajes de sistema
                if message.startswith("ERROR") or message.startswith("SYSTEM"):
                    print(f"[SYSTEM] {message}")
                    continue
                
                # Parsear datos: timestamp,ECG_I,ECG_II,ECG_III,AccX,AccY,AccZ,AccMag
                try:
                    values = [float(x) for x in message.split(',')]
                    if len(values) == 8:
                        self.data_queue.put(values)
                except ValueError:
                    print(f"[WARNING] Datos inválidos recibidos: {message}")
                    
            except socket.timeout:
                continue
            except Exception as e:
                print(f"[ERROR] Error en recepción: {e}")
    
    def stop(self):
        """Detiene la recepción"""
        self.running = False
        self.sock.close()


# =============================================================================
# CLASE: PROCESADOR WAVELET EN TIEMPO REAL
# =============================================================================

class WaveletProcessor:
    """Procesador de señales ECG con wavelets en tiempo real"""
    
    def __init__(self, session_folder):
        self.session_folder = session_folder
        
        # Buffers circulares
        self.buffer_size = HolterConfig.WINDOW_SIZE + HolterConfig.OVERLAP
        self.ecg_I_buffer = []
        self.ecg_II_buffer = []
        self.ecg_III_buffer = []
        self.acc_mag_buffer = []
        self.timestamp_buffer = []
        
        # Variables para guardar
        self.raw_data_list = []
        self.filtered_data_list = []
        
        # Umbral de movimiento (se calcula adaptativamente)
        self.acc_threshold = None
        
        # Archivos CSV
        self.raw_csv_path = os.path.join(session_folder, "raw_data.csv")
        self.filtered_csv_path = os.path.join(session_folder, "filtered_data.csv")
        
        # Crear headers
        self._initialize_csv_files()
        
    def _initialize_csv_files(self):
        """Inicializa archivos CSV con headers"""
        raw_header = "timestamp,ECG_I,ECG_II,ECG_III,AccX,AccY,AccZ,AccMag\n"
        filtered_header = "timestamp,ECG_I_filt,ECG_II_filt,ECG_III_filt\n"
        
        with open(self.raw_csv_path, 'w') as f:
            f.write(raw_header)
        
        with open(self.filtered_csv_path, 'w') as f:
            f.write(filtered_header)
        
        print(f"[SAVE] Archivos inicializados:")
        print(f"  - {self.raw_csv_path}")
        print(f"  - {self.filtered_csv_path}")
    
    def process_sample(self, data):
        """
        Procesa una muestra individual.
        data = [timestamp, ECG_I, ECG_II, ECG_III, AccX, AccY, AccZ, AccMag]
        """
        
        # Guardar datos crudos INMEDIATAMENTE
        self._save_raw_sample(data)
        
        # Agregar a buffers
        timestamp, ecg_I, ecg_II, ecg_III, acc_x, acc_y, acc_z, acc_mag = data
        
        self.timestamp_buffer.append(timestamp)
        self.ecg_I_buffer.append(ecg_I)
        self.ecg_II_buffer.append(ecg_II)
        self.ecg_III_buffer.append(ecg_III)
        self.acc_mag_buffer.append(acc_mag)
        
        # Si buffer está lleno, procesar
        if len(self.ecg_I_buffer) >= HolterConfig.WINDOW_SIZE:
            self._process_window()
            
            # Deslizar ventana (mantener overlap)
            self.timestamp_buffer = self.timestamp_buffer[-HolterConfig.OVERLAP:]
            self.ecg_I_buffer = self.ecg_I_buffer[-HolterConfig.OVERLAP:]
            self.ecg_II_buffer = self.ecg_II_buffer[-HolterConfig.OVERLAP:]
            self.ecg_III_buffer = self.ecg_III_buffer[-HolterConfig.OVERLAP:]
            self.acc_mag_buffer = self.acc_mag_buffer[-HolterConfig.OVERLAP:]
    
    def _save_raw_sample(self, data):
        """Guarda muestra cruda inmediatamente en CSV"""
        line = ",".join([str(x) for x in data]) + "\n"
        with open(self.raw_csv_path, 'a') as f:
            f.write(line)
    
    def _process_window(self):
        """Procesa ventana completa con wavelets"""
        
        # Convertir a arrays numpy
        timestamps = np.array(self.timestamp_buffer)
        ecg_I = np.array(self.ecg_I_buffer)
        ecg_II = np.array(self.ecg_II_buffer)
        ecg_III = np.array(self.ecg_III_buffer)
        acc_mag = np.array(self.acc_mag_buffer)
        
        # Calcular umbral de movimiento adaptativamente
        if self.acc_threshold is None:
            self.acc_threshold = np.percentile(acc_mag, HolterConfig.ACC_THRESHOLD_PERCENTILE)
        
        # Detectar movimiento
        motion_mask = detect_motion_segments(acc_mag, self.acc_threshold)
        
        # Aplicar filtrado wavelet a cada derivación
        ecg_I_filt = adaptive_wavelet_filter(ecg_I, motion_mask, 
                                             HolterConfig.WAVELET_TYPE, 
                                             HolterConfig.DECOMPOSITION_LEVEL)
        
        ecg_II_filt = adaptive_wavelet_filter(ecg_II, motion_mask,
                                              HolterConfig.WAVELET_TYPE,
                                              HolterConfig.DECOMPOSITION_LEVEL)
        
        ecg_III_filt = adaptive_wavelet_filter(ecg_III, motion_mask,
                                               HolterConfig.WAVELET_TYPE,
                                               HolterConfig.DECOMPOSITION_LEVEL)
        
        # Guardar solo las nuevas muestras (no overlap)
        n_new_samples = len(timestamps) - HolterConfig.OVERLAP
        
        for i in range(n_new_samples):
            filtered_line = f"{timestamps[i]},{ecg_I_filt[i]},{ecg_II_filt[i]},{ecg_III_filt[i]}\n"
            with open(self.filtered_csv_path, 'a') as f:
                f.write(filtered_line)
        
        print(f"[WAVELET] Ventana procesada | Movimiento: {np.mean(motion_mask)*100:.1f}% | Muestras: {len(timestamps)}")


# =============================================================================
# CLASE PRINCIPAL: SISTEMA HOLTER
# =============================================================================

class HolterSystem:
    """Sistema completo Holter con procesamiento híbrido"""
    
    def __init__(self):
        self.session_folder = HolterConfig.create_session_folder()
        self.data_queue = queue.Queue()
        self.receiver = UDPReceiver(self.data_queue)
        self.processor = WaveletProcessor(self.session_folder)
        self.running = False
        self.sample_count = 0
        
    def start(self):
        """Inicia el sistema Holter"""
        print("="*70)
        print("SISTEMA HOLTER - INICIO")
        print("="*70)
        print(f"Sesión: {self.session_folder}")
        print(f"Configuración:")
        print(f"  - Frecuencia de muestreo: {HolterConfig.SAMPLE_RATE} Hz")
        print(f"  - Wavelet: {HolterConfig.WAVELET_TYPE}")
        print(f"  - Ventana de procesamiento: {HolterConfig.WINDOW_SIZE} muestras")
        print("="*70)
        
        # Iniciar receptor UDP
        self.receiver.start()
        
        # Iniciar procesamiento
        self.running = True
        self._processing_loop()
    
    def _processing_loop(self):
        """Loop principal de procesamiento"""
        print("\n[HOLTER] Esperando datos del XSpaceBio...")
        print("[HOLTER] Presiona Ctrl+C para detener\n")
        
        start_time = time.time()
        last_print_time = start_time
        
        try:
            while self.running:
                try:
                    # Obtener dato de la cola (timeout 1 segundo)
                    data = self.data_queue.get(timeout=1.0)
                    
                    # Procesar muestra
                    self.processor.process_sample(data)
                    self.sample_count += 1
                    
                    # Imprimir progreso cada 5 segundos
                    current_time = time.time()
                    if current_time - last_print_time >= 5.0:
                        elapsed = current_time - start_time
                        rate = self.sample_count / elapsed
                        print(f"[STATUS] Muestras: {self.sample_count} | "
                              f"Tiempo: {elapsed:.1f}s | "
                              f"Tasa: {rate:.1f} Hz")
                        last_print_time = current_time
                    
                except queue.Empty:
                    continue
                    
        except KeyboardInterrupt:
            print("\n[HOLTER] Deteniendo sistema...")
            self.stop()
    
    def stop(self):
        """Detiene el sistema Holter"""
        self.running = False
        self.receiver.stop()
        
        print("\n" + "="*70)
        print("SISTEMA HOLTER - FINALIZADO")
        print("="*70)
        print(f"Total de muestras capturadas: {self.sample_count}")
        print(f"Duración: {self.sample_count / HolterConfig.SAMPLE_RATE:.2f} segundos")
        print(f"\nArchivos guardados en:")
        print(f"  - {self.processor.raw_csv_path}")
        print(f"  - {self.processor.filtered_csv_path}")
        print("="*70)


# =============================================================================
# PUNTO DE ENTRADA PRINCIPAL
# =============================================================================

if __name__ == "__main__":
    holter = HolterSystem()
    holter.start()