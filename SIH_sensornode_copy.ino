#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <Wire.h>

#define VIB_PIN    18
#define CRACK_PIN  19

#define I2C_SDA    21
#define I2C_SCL    22

#define MPU_ADDR   0x68

uint8_t broadcastAddress[] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

enum RiskLevel : uint8_t { STATE_NORMAL = 1, STATE_WARNING = 2, STATE_ALERT = 3 };

// Exact 21-byte struct matching your Gateway receiver
struct __attribute__((packed)) SubsidenceData {
  float tilt_x_deg;
  float tilt_y_deg;
  float vibration_g;
  float crack_disp_mm;
  float battery_v;
  uint8_t alertStatus;
};

SubsidenceData sensorPacket;
esp_now_peer_info_t peerInfo;

// Hardware 9-pulse unwedge
void recoverI2CBus() {
  Wire.end();
  pinMode(I2C_SDA, INPUT_PULLUP);
  pinMode(I2C_SCL, OUTPUT);

  for (int i = 0; i < 9; i++) {
    digitalWrite(I2C_SCL, LOW);
    delayMicroseconds(10);
    digitalWrite(I2C_SCL, HIGH);
    delayMicroseconds(10);
  }

  pinMode(I2C_SDA, OUTPUT);
  digitalWrite(I2C_SDA, LOW);
  delayMicroseconds(10);
  digitalWrite(I2C_SCL, HIGH);
  delayMicroseconds(10);
  digitalWrite(I2C_SDA, HIGH);
  delayMicroseconds(10);

  Wire.begin(I2C_SDA, I2C_SCL, 50000); // 50 kHz for jumper wire stability
  Wire.setTimeOut(30);
}

bool initMPUDirect() {
  recoverI2CBus();
  delay(15);

  // Wake up MPU6050: write 0 to PWR_MGMT_1 (0x6B)
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x6B);
  Wire.write(0x00);
  if (Wire.endTransmission() != 0) return false;

  delay(10);

  // Set Accelerometer to +/- 4G (Register 0x1C -> 0x08)
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x1C);
  Wire.write(0x08);
  if (Wire.endTransmission() != 0) return false;

  return true;
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\n--- Sensor Node Initializing ---");

  pinMode(VIB_PIN, INPUT);
  pinMode(CRACK_PIN, INPUT_PULLUP);

  if (!initMPUDirect()) {
    Serial.println("[ERROR] MPU6050 communication failed! Check wiring.");
  } else {
    Serial.println("[OK] MPU6050 direct I2C connection established.");
  }

  // Set Wi-Fi STA and Lock explicitly to Channel 11
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  esp_wifi_set_promiscuous(true);
  esp_wifi_set_channel(11, WIFI_SECOND_CHAN_NONE);
  esp_wifi_set_promiscuous(false);

  // Reduce RF output power to stop electrical interference on breadboard wires
  esp_wifi_set_max_tx_power(44); // ~11 dBm

  if (esp_now_init() != ESP_OK) {
    Serial.println("[Error] ESP-NOW init failed!");
    return;
  }

  memset(&peerInfo, 0, sizeof(peerInfo));
  memcpy(peerInfo.peer_addr, broadcastAddress, 6);
  peerInfo.channel = 11;
  peerInfo.encrypt = false;

  if (esp_now_add_peer(&peerInfo) != ESP_OK) {
    Serial.println("[Error] Failed to add broadcast peer");
    return;
  }

  Serial.println("[OK] Broadcasting on Channel 11 ready.\n");
}

void loop() {
  int16_t raw_ax = 0, raw_ay = 0, raw_az = 0;
  bool readSuccess = false;

  static int16_t last_ax = 0;
  static int freezeCounter = 0;

  // Direct register read: Accelerometer starts at 0x3B (6 bytes: X_H, X_L, Y_H, Y_L, Z_H, Z_L)
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x3B);
  if (Wire.endTransmission(false) == 0) {
    if (Wire.requestFrom((uint8_t)MPU_ADDR, (size_t)6) == 6) {
      raw_ax = (Wire.read() << 8) | Wire.read();
      raw_ay = (Wire.read() << 8) | Wire.read();
      raw_az = (Wire.read() << 8) | Wire.read();
      readSuccess = true;
    }
  }

  // Detect frozen sensor state
  if (readSuccess) {
    if (raw_ax == last_ax && raw_ax != 0) {
      freezeCounter++;
    } else {
      freezeCounter = 0;
      last_ax = raw_ax;
    }
  }

  // If reading fails or values freeze for 2 consecutive cycles, force re-initialization
  if (!readSuccess || freezeCounter >= 2) {
    initMPUDirect();
    freezeCounter = 0;
  } else {
    // Scale factor for +/- 4G range is 8192.0 LSB/g
    float ax = (float)raw_ax / 8192.0;
    float ay = (float)raw_ay / 8192.0;
    float az = (float)raw_az / 8192.0;

    sensorPacket.tilt_x_deg = atan2(ay, sqrt(ax * ax + az * az)) * 180.0 / PI;
    sensorPacket.tilt_y_deg = atan2(-ax, az) * 180.0 / PI;
  }

  uint8_t vib   = (digitalRead(VIB_PIN) == HIGH) ? 1 : 0;
  uint8_t crack = (digitalRead(CRACK_PIN) == HIGH) ? 1 : 0;

  sensorPacket.vibration_g   = (vib == 1) ? 0.250 : 0.015;
  sensorPacket.crack_disp_mm = (crack == 1) ? 4.50 : 0.00;
  sensorPacket.battery_v     = 3.70;

  // Strata Risk Classification
  if (sensorPacket.crack_disp_mm > 2.0 || abs(sensorPacket.tilt_x_deg) > 25.0 || abs(sensorPacket.tilt_y_deg) > 25.0) {
    sensorPacket.alertStatus = STATE_ALERT;
  } else if (sensorPacket.vibration_g > 0.10 || abs(sensorPacket.tilt_x_deg) > 10.0 || abs(sensorPacket.tilt_y_deg) > 10.0) {
    sensorPacket.alertStatus = STATE_WARNING;
  } else {
    sensorPacket.alertStatus = STATE_NORMAL;
  }

  esp_err_t result = esp_now_send(broadcastAddress, (uint8_t *)&sensorPacket, sizeof(sensorPacket));

  const char* statusStr = (sensorPacket.alertStatus == STATE_ALERT)   ? "ALERT" :
                          (sensorPacket.alertStatus == STATE_WARNING) ? "WARNING" : "NORMAL";

  Serial.printf("[TX %s] tilt_x_deg: %6.3f | tilt_y_deg: %6.3f | vibration_g: %5.3f | status: %s\n",
                (result == ESP_OK ? "OK" : "FAIL"),
                sensorPacket.tilt_x_deg,
                sensorPacket.tilt_y_deg,
                sensorPacket.vibration_g,
                statusStr);

  delay(300); // Fast ~3 Hz refresh rate for real-time responsiveness
}