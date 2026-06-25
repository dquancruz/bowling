# Contexto del Proyecto: Bowling Semiautomático

## 1. Qué es y para qué sirve

Sistema de marcador automático para una pista de boliche física construida sobre una Raspberry Pi 4. El sistema detecta los pinos caídos mediante sensores físicos, lleva el marcador completo con la lógica oficial del bowling (10 frames, strikes, spares, bonificaciones), controla el retorno de la bola y la limpieza de pinos con servomotores. El estado del juego vive completamente en memoria RAM, sin base de datos.

El jugador simplemente juega; el sistema registra todo automáticamente y muestra el marcador en tiempo real desde cualquier navegador en la misma red.

---

## 2. Arquitectura general

```
Raspberry Pi 4
├── pigpiod                → daemon de hardware PWM (necesario para los servos)
├── FastAPI (puerto 8000)  → API REST + WebSockets + sirve el frontend estático
└── GPIO (modo BCM)
    ├── Entradas
    │   ├── 10 limit switches   → detectan pinos caídos (GPIO 17,18,27,22,23,24,25,4,5,6)
    │   ├── Sensor bola derecha  → canaleta derecha (GPIO 16)
    │   └── Sensor bola izquierda → canaleta izquierda (GPIO 14)
    └── Salidas
        ├── LED verde    → jugador puede tirar (GPIO 19)
        ├── LED rojo     → partida activa (GPIO 26)
        ├── LED amarillo → bola retornando / timer 20s (GPIO 20)
        ├── Relay        → motor alimentador de bolas (GPIO 21)
        ├── Servo 1      → limpieza de pinos (GPIO 13)
        └── Servo 2      → limpieza de pinos, movimiento espejo (GPIO 12)
```

**Capas del software:**

| Capa | Archivo | Responsabilidad |
|---|---|---|
| Hardware | `gpio_handler.py` | Leer sensores, controlar LEDs, relay y servos |
| Logica | `game_logic.py` | Frames, tiros, scores, strikes, spares, turnos |
| API | `main.py` | Endpoints REST, WebSocket, coordinacion de callbacks |
| Frontend | `frontend/index.html` | UI completa, una sola pagina sin frameworks |

En local (Windows/Mac/Linux), el GPIO corre en modo simulacion automaticamente. No se necesita Raspberry Pi para desarrollar.

---

## 3. Funcionalidades principales

### Marcador automatico
- Soporta de 1 a 6 jugadores.
- Lógica completa de 10 frames: strikes, spares y bonificaciones calculados correctamente.
- El puntaje acumulado se muestra en tiempo real en la tabla.
- El 10mo frame admite hasta 3 tiros segun las reglas oficiales.

### Deteccion de pinos
- Cada pino tiene un limit switch (final de carrera) entre su GPIO y GND con pull-up interno.
- Al caer, el switch cierra el circuito (flanco RISING) y dispara una interrupcion con debounce de 300 ms.
- Los pinos se acumulan como `pending_pins` hasta que se confirma el tiro.
- Si caen los 10 pinos en el primer tiro se detecta como chuza y el tiro se confirma automaticamente.

### Retorno de bola y flujo de tiros
- Dos sensores (canaleta izquierda y derecha) detectan cuando la bola regresa.
- El primero que se activa cuenta como retorno valido; el segundo se ignora por debounce de 5 segundos.
- Primer retorno: confirma el tiro, LED verde ON, el jugador puede tirar de nuevo.
- Segundo retorno (o primero si fue chuza): confirma el tiro, inicia la secuencia de reset de pinos.
- Si la bola regresa sin haber derribado ningun pino (canaleta), el sistema espera 2 segundos de gracia antes de confirmar 0 pinos, para evitar commits prematuros.

### LEDs de estado
- Verde: la bola esta en camino de regreso / el jugador puede tirar.
- Rojo: partida activa.
- Amarillo: timer de 20 segundos activo (colocar pinos manualmente).
Los LEDs fisicos y los LEDs virtuales en la UI se sincronizan via WebSocket.

### Servos de limpieza
- Dos servos Futaba S3003 controlados por `pigpio` (hardware PWM, no software).
- Se mueven en espejo: Servo 1 avanza mientras Servo 2 retrocede.
- Secuencia: 15 grados -> 137.5 grados -> 15 grados (Servo 1) / inverso (Servo 2), ejecutada 2 ciclos.
- Se activan desde un boton en la UI o automaticamente tras el reset de pinos.
- Los servos quedan sin señal PWM en reposo para no consumir corriente innecesariamente.

### Relay (motor alimentador)
- Controla el motor que hace regresar la bola por la canaleta.
- Activo en LOW. Se activa al iniciar la secuencia de retorno y se apaga cuando la bola llega.

### WebSocket en tiempo real
- Conexion persistente entre el backend y todos los clientes conectados.
- Cada evento del juego (pin caido, bola lista, tiro confirmado, timer, fin de partida) se transmite como un mensaje JSON.
- El frontend actualiza el marcador y los LEDs virtuales sin hacer polling.
- Si la conexion se pierde, el cliente reintenta cada 3 segundos.

---

## 4. Flujo de juego resumido

```
1. Jugador inicia partida desde la UI (CONTROLES -> Nueva Partida)
2. Jugador tira la bola
3. Limit switches detectan pinos caidos -> se acumulan en el marcador
4. Si caen los 10 (chuza): tiro confirmado automaticamente -> ir al paso 7
5. Bola regresa -> LED verde ON -> jugador tira segundo tiro
6. Segundo retorno de bola -> tiro confirmado
7. LED amarillo ON + timer 20s (el jugador coloca los pinos manualmente)
8. Timer termina -> LED amarillo OFF, LED verde ON -> nuevo turno
9. Al terminar los 10 frames de todos los jugadores, la partida finaliza
   y se anuncia el ganador
```

**Correcciones manuales disponibles en cualquier momento:**
- Registrar un pin caido manualmente (boton en UI o endpoint `/api/game/manual-pin`).
- Confirmar el tiro manualmente (`/api/game/reset-pins`).
- Simular retorno de bola sin hardware (`/api/game/simulate-ball-return`).
- Activar limpieza de pinos con servo (`/api/servo/limpiar`).

---

## 5. Tecnologias usadas

| Categoria | Tecnologia |
|---|---|
| Lenguaje backend | Python 3 |
| Framework web | FastAPI |
| Servidor ASGI | Uvicorn |
| Comunicacion tiempo real | WebSockets (nativo en FastAPI) |
| Control GPIO | RPi.GPIO (entradas/salidas digitales) |
| Control PWM servos | pigpio / pigpiod |
| Modelos de datos | Pydantic |
| Frontend | HTML + CSS + JavaScript vanilla (sin frameworks) |
| Fuentes UI | Bebas Neue, Share Tech Mono, Barlow Condensed (Google Fonts) |
| Hardware | Raspberry Pi 4, servos Futaba S3003, limit switches, LEDs, relay |

El proyecto no usa base de datos. Todo el estado de la partida vive en RAM y se pierde al reiniciar el servidor. El historial de partidas que aparece en la UI intenta llamar a un endpoint `/api/games/history` que actualmente no esta implementado en el backend.
