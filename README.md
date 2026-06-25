# Bowling Semiautomático

Sistema de marcador automático para boliche con Raspberry Pi, FastAPI y WebSockets.
El estado del juego vive en memoria RAM — sin base de datos.

---

## Arquitectura del sistema

```
Raspberry Pi 4
├── pigpiod (daemon)         ← hardware PWM para servos (debe correr antes del backend)
├── FastAPI (puerto 8000)    ← API REST + WebSockets + sirve el frontend
└── GPIO BCM
    ├── ENTRADAS
    │   ├── Limit switches x10       → detectan pines caídos (GPIO 17,18,27,22,23,24,25,4,5,6)
    │   ├── Sensor bola derecha      → canaleta derecha (GPIO 16)
    │   └── Sensor bola izquierda   → canaleta izquierda (GPIO 14)
    └── SALIDAS
        ├── LED verde                → bola en camino de regreso (GPIO 19)
        ├── LED rojo                 → bola lista para tirar (GPIO 26)
        ├── LED amarillo             → timer 20s para colocar pines (GPIO 20)
        ├── Relay                    → motor alimentador de bolas (GPIO 21)
        ├── Servo palanca 1          → limpieza de pinos (GPIO 13)
        └── Servo palanca 2          → limpieza de pinos, movimiento espejo (GPIO 12)
```

---

## Mapa de pines GPIO (BCM)

### Entradas

| Componente               | GPIO (BCM) | Pin físico | Cableado                    |
|--------------------------|:----------:|:----------:|-----------------------------|
| Pin bowling 1            | 17         | 11         | Switch entre GPIO y GND     |
| Pin bowling 2            | 18         | 12         | Switch entre GPIO y GND     |
| Pin bowling 3            | 27         | 13         | Switch entre GPIO y GND     |
| Pin bowling 4            | 22         | 15         | Switch entre GPIO y GND     |
| Pin bowling 5            | 23         | 16         | Switch entre GPIO y GND     |
| Pin bowling 6            | 24         | 18         | Switch entre GPIO y GND     |
| Pin bowling 7            | 25         | 22         | Switch entre GPIO y GND     |
| Pin bowling 8            | 4          | 7          | Switch entre GPIO y GND     |
| Pin bowling 9            | 5          | 29         | Switch entre GPIO y GND     |
| Pin bowling 10           | 6          | 31         | Switch entre GPIO y GND     |
| Sensor bola derecha      | 16         | 36         | Pull-up interno, FALLING    |
| Sensor bola izquierda    | 14         | 8          | Pull-up interno, FALLING    |

### Salidas

| Componente               | GPIO (BCM) | Pin físico | Tipo              | Notas                     |
|--------------------------|:----------:|:----------:|-------------------|---------------------------|
| LED verde                | 19         | 35         | Digital           | 220Ω entre GPIO y GND     |
| LED rojo                 | 26         | 37         | Digital           | 220Ω entre GPIO y GND     |
| LED amarillo             | 20         | 38         | Digital           | 220Ω entre GPIO y GND     |
| Relay alimentador        | 21         | 40         | Digital           | Activo en LOW             |
| Servo palanca 1          | 13         | 33         | pigpio PWM        | VCC → 5V externo          |
| Servo palanca 2          | 12         | 32         | pigpio PWM        | VCC → 5V externo, espejo  |

---

## Cableado

### Limit switches (pines de bowling)
Pull-up interno activado. Cada switch va entre GPIO y GND:
- Switch **abierto** → GPIO HIGH → pin de pie
- Switch **cerrado** → GPIO LOW → pin caído → dispara interrupción

### Sensores de retorno de bola
Dos sensores, uno por canaleta (derecha e izquierda). El software hace debounce de 5 segundos entre detecciones para evitar contar el mismo retorno dos veces — el primer sensor que detecte la bola activa el retorno; el segundo se ignora.

Cuando la bola regresa sin haber derribado ningún pino (canaleta / gutter ball), el sistema espera 2 segundos antes de confirmar el tiro con 0 pinos. Esto evita commits prematuros si la bola pasa el sensor antes de que el jugador haya tirado.

### LEDs
Resistencia de 220Ω entre GPIO y GND. Se configuran como salida al arrancar (LOW = apagado). El sistema los controla automáticamente según el flujo de juego.

### Relay (alimentador de bolas)
Activo en LOW. El motor se conecta al circuito controlado por el relay.

### Servos palanca (Futaba S3003)
Controlados con `pigpio` (hardware PWM) — **no** con `RPi.GPIO.PWM`.
- Servo palanca 1 → GPIO 13 (Pin físico 33)
- Servo palanca 2 → GPIO 12 (Pin físico 32)
- VCC → 5V **externo** (no del pin de la Pi — los servos consumen demasiada corriente)
- GND → GND común con la Pi

Los dos servos se mueven en **espejo**: cuando el servo 1 avanza, el servo 2 retrocede, y viceversa.

| Ángulo  | Pulsewidth | Servo 1 (GPIO 13)  | Servo 2 (GPIO 12)  |
|:-------:|:----------:|:------------------:|:------------------:|
| 15°     | 667 µs     | Posición de reposo | Posición activa    |
| 137.5°  | 2028 µs    | Posición activa    | Posición de reposo |

Secuencia de limpieza (activada desde el botón en la UI):
1. Servo 1 → 15° / Servo 2 → 137.5° (reposo)
2. Servo 1 → 137.5° / Servo 2 → 15° (empuje en espejo)
3. Servo 1 → 15° / Servo 2 → 137.5° (vuelven a reposo)
4. Ambos → señal apagada

---

## Flujo de juego

```
Jugador tira
    ↓
Limit switches detectan pines caídos → se acumulan en el marcador
    ↓
[Si 10 pines en 1er tiro → CHUZA → saltar al reset automático]
    ↓
Bola regresa por la canaleta
    ↓
🟢 LED verde ON (bola en camino)
    ↓
Sensor detecta retorno #1 → confirma tiro
🟢 LED verde OFF → 🔴 LED rojo ON (bola lista para tirar)
    ↓
Jugador tira 2do tiro
    ↓
🟢 LED verde ON (bola en camino)
    ↓
Sensor detecta retorno #2 → confirma tiro
🟢 LED verde OFF → 🔴 LED rojo ON
    ↓
Reset automático:
    🟡 LED amarillo ON
    ⏱️  Timer 20 segundos (colocar pines manualmente)
    🟡 LED amarillo OFF → listo para nuevo turno

Limpieza manual (botón en UI, en cualquier momento):
    ⚙️  Servo 1 (GPIO 13): 15° → 137.5° → 15°
    ⚙️  Servo 2 (GPIO 12): 137.5° → 15° → 137.5° (espejo)
```

---

## Instalación

### Prueba local (Windows / Mac / Linux)

```bash
cd bowling/backend

# Crear entorno virtual
python -m venv venv

# Activar (Windows)
venv\Scripts\activate
# Activar (Mac / Linux)
source venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt

# Correr servidor
python main.py
```

Abrir en el navegador: `http://localhost:8000`

El GPIO corre en **modo simulación** automáticamente (no necesita Raspberry Pi).
Usar los botones de la pestaña CONTROLES para simular pines y sensores.

---

### Instalación en Raspberry Pi

#### 1. Instalar dependencias del sistema

```bash
sudo apt-get update
sudo apt-get install -y pigpio python3-pigpio
```

#### 2. Habilitar el daemon `pigpiod`

`pigpiod` debe estar activo **antes** de arrancar el backend. Configurarlo para arranque automático:

```bash
sudo systemctl enable pigpiod
sudo systemctl start pigpiod

# Verificar que está corriendo
sudo systemctl status pigpiod
```

#### 3. Instalar dependencias Python

```bash
cd ~/bowling/backend

python3 -m venv venv
source venv/bin/activate

pip install -r requirements_pi.txt
pip install pigpio
```

#### 4. Arrancar el servidor

```bash
source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000
```

Abrir desde cualquier dispositivo en la misma red:
```
http://<IP-DE-LA-PI>:8000
```

Obtener la IP de la Pi:
```bash
hostname -I
```

---

## Autostart en la Pi

Para que el servidor arranque automáticamente al encender la Pi:

```bash
sudo nano /etc/systemd/system/bowling.service
```

```ini
[Unit]
Description=Bowling Semiautomático
After=network.target pigpiod.service
Requires=pigpiod.service

[Service]
User=pi
WorkingDirectory=/home/pi/bowling/backend
ExecStart=/home/pi/bowling/backend/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable bowling
sudo systemctl start bowling

# Ver logs en vivo
sudo journalctl -u bowling -f
```

---

## Endpoints de la API

| Método | Ruta                   | Descripción                              |
|--------|------------------------|------------------------------------------|
| POST   | /api/game/new          | Iniciar nueva partida                    |
| GET    | /api/game/current      | Estado de la partida actual              |
| POST   | /api/game/reset-pins   | Confirmar tiro manualmente               |
| POST   | /api/game/manual-pin   | Registrar pin caído (testing)            |
| POST   | /api/game/simulate-ball-return | Simular retorno de bola (testing) |
| POST   | /api/game/end          | Finalizar partida                        |
| GET    | /api/config            | Obtener configuración                    |
| PUT    | /api/config            | Actualizar configuración                 |
| GET    | /api/gpio/map          | Ver mapa de pines GPIO activo            |
| WS     | /ws                    | WebSocket — eventos en tiempo real       |

Documentación interactiva: `http://<IP>:8000/docs`

### Eventos WebSocket

| Tipo             | Cuándo se emite                                    |
|------------------|----------------------------------------------------|
| `game_started`   | Nueva partida iniciada                             |
| `pin_fallen`     | Limit switch activado                              |
| `ball_ready`     | Sensor detectó retorno de bola                     |
| `roll_committed` | Tiro confirmado en el marcador                     |
| `pins_reset`     | Inicio de secuencia de reset                       |
| `ordering_pins`  | Servos en movimiento, timer activo                 |
| `timer_done`     | Timer 20s terminó, listo para siguiente turno      |
| `game_ended`     | Partida finalizada                                 |

---

## Configuración (gpio_handler.py)

```python
# ── Sensores de bola ──
GPIO_SENSOR_BOLA   = 16   # Canaleta derecha   → Pin físico 36
GPIO_SENSOR_BOLA_2 = 14   # Canaleta izquierda → Pin físico 8

# ── LEDs ──
GPIO_LED_VERDE    = 19   # Bola en camino de regreso → Pin físico 35
GPIO_LED_ROJO     = 26   # Bola lista para tirar     → Pin físico 37
GPIO_LED_AMARILLO = 20   # Timer 20s activo           → Pin físico 38

# ── Servos palanca (pigpio) ──
GPIO_SERVO_PALANCA   = 13  # Servo palanca 1 → Pin físico 33
GPIO_SERVO_PALANCA_2 = 12  # Servo palanca 2 → Pin físico 32 (movimiento espejo)

# Servo palanca 1: reposo=15° (667 µs),     activo=137.5° (2028 µs)
# Servo palanca 2: reposo=137.5° (2028 µs), activo=15° (667 µs)

# ── Timer de reset ──
TIMER_PINES_S = 20        # segundos para colocar pines manualmente

# ── Debounce ──
DEBOUNCE_MS = 300         # milisegundos entre activaciones de limit switch

# ── Periodo de gracia (canaleta) ──
GRACE_PERIOD_S = 2.0      # segundos antes de confirmar tiro de 0 pinos
```

---

## Estructura del proyecto

```
bowling/
├── backend/
│   ├── main.py              ← FastAPI, endpoints, WebSocket, callbacks GPIO
│   ├── gpio_handler.py      ← Control de hardware (RPi.GPIO + pigpio)
│   ├── game_logic.py        ← Lógica de partida, frames, puntaje
│   ├── models.py            ← Modelos Pydantic
│   ├── websocket_manager.py ← Broadcast a clientes conectados
│   ├── requirements.txt     ← Dependencias locales (sin GPIO)
│   └── requirements_pi.txt  ← Dependencias Raspberry Pi (incluye RPi.GPIO)
└── frontend/
    └── index.html           ← UI servida por FastAPI
```
