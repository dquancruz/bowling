# 🎳 Bowling Semiautomático

Sistema de marcador automático para bowling con Raspberry Pi, FastAPI y WebSockets.
El estado del juego vive en memoria RAM — simple, sin base de datos.

---

## Arquitectura del sistema

```
Raspberry Pi 4
├── FastAPI (puerto 8000)     ← API + WebSockets + sirve el frontend
└── GPIO BCM
    ├── ENTRADAS
    │   ├── Limit switches x10  → detectan pines caídos
    │   └── Sensor de bola      → detecta retorno de bola al jugador
    └── SALIDAS
        ├── LED verde            → bola en camino de regreso
        ├── LED rojo             → bola lista para tirar
        ├── LED amarillo         → timer 20s (colocar pines)
        ├── Relay                → motor alimentador de bolas
        └── Servomotor PWM       → palanca que empuja pines
```

---

## Mapa de pines GPIO (BCM)

### Entradas

| Componente           | GPIO (BCM) | Pin físico |
|----------------------|:----------:|:----------:|
| Pin bowling 1        | 17         | 11         |
| Pin bowling 2        | 18         | 12         |
| Pin bowling 3        | 27         | 13         |
| Pin bowling 4        | 22         | 15         |
| Pin bowling 5        | 23         | 16         |
| Pin bowling 6        | 24         | 18         |
| Pin bowling 7        | 25         | 22         |
| Pin bowling 8        | 4          | 7          |
| Pin bowling 9        | 5          | 29         |
| Pin bowling 10       | 6          | 31         |
| Sensor retorno bola  | 16         | 36         |

### Salidas

| Componente           | GPIO (BCM) | Pin físico | Tipo       |
|----------------------|:----------:|:----------:|------------|
| LED verde            | 19         | 35         | Digital    |
| LED rojo             | 26         | 37         | Digital    |
| LED amarillo         | 20         | 38         | Digital    |
| Relay alimentador    | 21         | 40         | Digital    |
| Servo palanca        | 12         | 32         | PWM 50Hz   |

---

## Cableado

### Limit switches (pines de bowling)
Cada switch se conecta entre el GPIO y GND (pull-up interno activado):
- Switch **abierto**  → GPIO lee HIGH → pin de pie
- Switch **cerrado**  → GPIO lee LOW  → pin caído → dispara interrupción

### LEDs
Cada LED se conecta con una resistencia de 220Ω entre el GPIO y GND.

### Relay (alimentador de bolas)
- El relay es **activo en LOW** (se activa cuando el GPIO va a LOW)
- Conectar el motor al circuito controlado por el relay

### Servomotor (palanca)
- Señal PWM → GPIO 12
- VCC → 5V (pin físico 2 o 4)
- GND → GND (pin físico 6, 9, etc.)
- Ángulos: **90° reposo → 180° empuja → 90° vuelve**
- Tiempo de empuje: 1.5 segundos

---

## Secuencia automática del juego

```
Jugador tira
    ↓
Limit switches detectan pines caídos
    ↓
Jugador presiona RESETEAR (o strike automático)
    ↓
✅ Tiro registrado en el marcador
⚙️  Relay ON → alimentador retorna bola
💚 LED verde ON → bola en camino
    ↓
Sensor detecta bola
    ↓
⚙️  Relay OFF
💚 LED verde OFF
🔴 LED rojo ON → bola lista para tirar
    ↓
  [Si frame completo]
    ↓
⚙️  Servo 90° → 180° → 90° (empuja pines)
🟡 LED amarillo ON
⏱️  Timer 20 segundos (colocar pines manualmente)
    ↓
🟡 LED amarillo OFF → listo para nuevo turno
```

---

## Instalación

### 🖥️ Prueba local (Windows/Mac/Linux)

```bash
cd bowling/backend

# Crear entorno virtual
python -m venv venv

# Activar (Windows)
venv\Scripts\activate
# Activar (Mac/Linux)
source venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt

# Correr servidor
python main.py
```

Abrir en el navegador: `http://localhost:8000`

> El GPIO corre en **modo simulación** automáticamente.
> Usá los botones de pines en la pestaña CONTROLES para probar.

---

### 🍓 Instalación en Raspberry Pi

```bash
cd ~/bowling/backend

# Crear entorno virtual
python3 -m venv venv
source venv/bin/activate

# Instalar dependencias (incluye RPi.GPIO)
pip install -r requirements-pi.txt

# Correr servidor
python main.py
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

## Endpoints de la API

| Método | Ruta                  | Descripción                              |
|--------|-----------------------|------------------------------------------|
| POST   | /api/game/new         | Iniciar nueva partida                    |
| GET    | /api/game/current     | Estado de la partida actual              |
| POST   | /api/game/reset-pins  | Confirmar tiro + activar secuencia       |
| POST   | /api/game/manual-pin  | Registrar pin manualmente (testing)      |
| POST   | /api/game/end         | Finalizar partida                        |
| GET    | /api/config           | Obtener configuración                    |
| PUT    | /api/config           | Actualizar configuración                 |
| GET    | /api/gpio/map         | Ver mapa de pines GPIO                   |
| WS     | /ws                   | WebSocket para tiempo real               |

Documentación interactiva: `http://<IP>:8000/docs`

---

## Autostart en la Pi (opcional)

Para que el servidor arranque solo al encender la Pi:

```bash
sudo nano /etc/systemd/system/bowling.service
```

```ini
[Unit]
Description=Bowling Semiautomático
After=network.target

[Service]
User=pi
WorkingDirectory=/home/pi/bowling/backend
ExecStart=/home/pi/bowling/backend/venv/bin/python main.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable bowling
sudo systemctl start bowling
```

---

## Ajustar pines GPIO

Editar `gpio_handler.py` para cambiar cualquier asignación:

```python
# Limit switches pines de bowling
PIN_GPIO_MAP = {
    1: 17, 2: 18, 3: 27, ...
}

# Sensor y salidas
GPIO_SENSOR_BOLA       = 16
GPIO_LED_VERDE         = 19
GPIO_LED_ROJO          = 26
GPIO_LED_AMARILLO      = 20
GPIO_RELAY_ALIMENTADOR = 21
GPIO_SERVO_PALANCA     = 12

# Ángulos del servo
SERVO_REPOSO = 90
SERVO_EMPUJA = 180
SERVO_TIEMPO = 1.5   # segundos empujando

# Timer para colocar pines
TIMER_PINES_S = 20
```