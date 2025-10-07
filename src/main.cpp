#include <Arduino.h>
#include <XSpaceBioV10.h>
#include <XSpaceIoT.h>
#include <Wire.h>
#include <Adafruit_ADXL345_U.h>

// ============================================================================
// OBJETOS PRINCIPALES
// ============================================================================
XSpaceBioV10Board MyBioBoard;
XSEthernet XSerial;
Adafruit_ADXL345_Unified accel = Adafruit_ADXL345_Unified(12345);

// ============================================================================
// CONFIGURACIÓN
// ============================================================================
const int SAMPLE_RATE_MS = 10;  // 100 Hz (10ms entre muestras)

void setup() {
  
  // Inicializar XSpaceBio
  MyBioBoard.init();

  // Conectar WiFi y UDP
  XSerial.Wifi_init("Delta", "c9aa28ba93");
  XSerial.UDP_Connect("192.168.4.101", 55000);
  
  // Activar sensores ECG
  MyBioBoard.AD8232_Wake(AD8232_XS1);
  MyBioBoard.AD8232_Wake(AD8232_XS2);
  
  // Inicializar I2C
  Wire.begin();
  
  // Inicializar ADXL345
  if(!accel.begin()) {
    XSerial.println("ERROR:ADXL345_NOT_FOUND");
    while(1) {
      delay(1000);
      XSerial.println("ERROR:ADXL345_NOT_FOUND");
    }
  }
  
  // Configurar ADXL345
  accel.setRange(ADXL345_RANGE_4_G);           // ±4g suficiente para movimiento corporal
  accel.setDataRate(ADXL345_DATARATE_100_HZ);  // 100Hz matching ECG
  
  XSerial.println("SYSTEM_READY");
  delay(1000);
}

void loop() {
  
  // Timestamp en milisegundos
  unsigned long timestamp = millis();
  
  // ===== LEER ECG =====
  double DerivationI   = MyBioBoard.AD8232_GetVoltage(AD8232_XS1);
  double DerivationII  = MyBioBoard.AD8232_GetVoltage(AD8232_XS2);
  double DerivationIII = DerivationII - DerivationI;
  
  // ===== LEER ACELERÓMETRO =====
  sensors_event_t event;
  accel.getEvent(&event);
  
  double accelX = event.acceleration.x;  // m/s²
  double accelY = event.acceleration.y;
  double accelZ = event.acceleration.z;
  
  // Calcular magnitud
  double accelMagnitude = sqrt(accelX*accelX + accelY*accelY + accelZ*accelZ);
  
  // ===== ENVIAR DATOS POR UDP =====
  // Formato: timestamp,ECG_I,ECG_II,ECG_III,AccX,AccY,AccZ,AccMag
  String dataPacket = String(timestamp) + "," +
                      String(DerivationI, 6) + "," +
                      String(DerivationII, 6) + "," +
                      String(DerivationIII, 6) + "," +
                      String(accelX, 4) + "," +
                      String(accelY, 4) + "," +
                      String(accelZ, 4) + "," +
                      String(accelMagnitude, 4);
  
  XSerial.println(dataPacket);
  
  // Control de tasa de muestreo
  delay(SAMPLE_RATE_MS);
}