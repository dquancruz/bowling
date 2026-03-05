# 🎳 Bowling Semiautomático

Sistema de marcador automático para bowling con Raspberry Pi, FastAPI y WebSockets.
El estado del juego vive en memoria RAM — simple, sin base de datos.

---

## Arquitectura

```
Raspberry Pi
├── FastAPI (puerto 8000)     ← API + WebSockets + sirve el frontend
└── GPIO BCM
    ├── Pin bowling 1  → GPIO 17
    ├── Pin bowling 2  → GPIO 18
    ├── Pin bowling 3  → GPIO 27
    ├── Pin bowling 4  → GPIO 22
    ├── Pin bowling 5  → GPIO 23
    ├── Pin bowling 6  → GPIO 24
    ├── Pin bowling 7  → GPIO 25
    ├── Pin bowling 8  → GPIO 4
    ├── Pin bowling 9  → GPIO 5
    └── Pin bowling 10 → GPIO 6
```

### Cableado de los Limit Switches
Cada limit switch se conecta entre el pin GPIO y GND.
La Raspberry Pi usa resistencias pull-up internas (PUD_UP).
- Switch abierto  → GPIO lee HIGH (pin de pie)
- Switch cerrado  → GPIO lee LOW  (pin caído) → dispara la interrupción

---

## Instalación

### 1. Instalar dependencias Python
```bash
cd bowling/backend
pip install -r requirements.txt

# En Raspberry Pi (para GPIO real):
pip install RPi.GPIO
```

### 2. Ejecutar
```bash
cd bowling/backend
python main.py
# o:
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 3. Acceder
Abrir en el navegador (desde cualquier dispositivo en la misma red):
```
http://<IP-DE-LA-PI>:8000
```

---

## Endpoints de la API

| Método | Ruta                  | Descripción                        |
|--------|-----------------------|------------------------------------|
| POST   | /api/game/new         | Iniciar nueva partida              |
| GET    | /api/game/current     | Estado de la partida actual        |
| POST   | /api/game/reset-pins  | Resetear pines para siguiente tiro |
| POST   | /api/game/manual-pin  | Registrar pin manualmente          |
| POST   | /api/game/end         | Finalizar partida                  |
| GET    | /api/config           | Obtener configuración              |
| PUT    | /api/config           | Actualizar configuración           |
| WS     | /ws                   | WebSocket para tiempo real         |

Documentación interactiva: `http://<IP>:8000/docs`

---

## Ejecutar como servicio (autostart)

```bash
sudo nano /etc/systemd/system/bowling.service
```

```ini
[Unit]
Description=Bowling API
After=network.target

[Service]
User=pi
WorkingDirectory=/home/pi/bowling/backend
ExecStart=/usr/bin/python3 main.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable bowling && sudo systemctl start bowling
```

---

## Modo simulación
Sin Raspberry Pi, el sistema corre en modo simulación:
- Los pines GPIO no se inicializan
- Usar el panel **CONTROLES → Simular Pin** o el endpoint `POST /api/game/manual-pin`

---

## Ajustar pines GPIO
Editar `gpio_handler.py`, sección `PIN_GPIO_MAP`:
```python
PIN_GPIO_MAP = {
    1:  17,   # Pin de bowling 1 → GPIO 17 (BCM)
    2:  18,   # Pin de bowling 2 → GPIO 18
    ...
}
```
