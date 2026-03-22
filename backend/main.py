"""
Bowling Semiautomático - Backend Principal
FastAPI + GPIO + WebSockets (sin base de datos)

Flujo de juego:
  1. Jugador tira → limit switches detectan pines caídos
  2. Bola regresa → sensor (GPIO 16) detecta 1er retorno → nada (sigue tirando)
  3. Jugador tira 2do tiro → pines caen
  4. Bola regresa → sensor detecta 2do retorno → cambio de jugador + reseteo de pines
  EXCEPCIÓN: si el jugador hace chuza (10 pines en 1er tiro) → reseteo inmediato al 1er retorno
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import json
import logging
import time
from typing import Optional
import os

from models import GameConfig, NewGameRequest, ManualPinUpdate
from game_logic import BowlingGame
from gpio_handler import GPIOHandler
from websocket_manager import ConnectionManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

current_game: Optional[BowlingGame] = None
ball_return_count: int = 0   # Retornos de bola en el turno actual (max 2)
is_strike_turn: bool = False  # Si el turno actual fue chuza
last_ball_time: float = 0.0  # Timestamp del último retorno detectado
current_config: dict = {
    "max_players": 6,
    "frames_per_game": 10,
    "pins_per_frame": 10,
    "allow_manual_override": True,
    "auto_reset_pins": False,
    "game_mode": "classic"
}
gpio_handler: Optional[GPIOHandler] = None
manager = ConnectionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global gpio_handler
    gpio_handler = GPIOHandler(
        pin_callback=on_pin_fallen,
        ball_return_callback=on_ball_returned,
        timer_done_callback=on_timer_done
    )
    await gpio_handler.setup()
    logger.info("✅ Sistema iniciado")
    yield
    if gpio_handler:
        gpio_handler.cleanup()
    logger.info("🔌 Servidor detenido")


app = FastAPI(title="Bowling Semiautomático API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── CALLBACKS GPIO ──────────────────────────────────────────────────────────

async def on_pin_fallen(pin_number: int):
    """Limit switch activado → acumular pin caído"""
    global current_game, is_strike_turn
    if not current_game:
        logger.warning(f"Pin {pin_number} caído pero no hay partida activa")
        return

    result = current_game.register_pin_fall(pin_number)
    if not result:
        return

    await manager.broadcast({
        "type": "pin_fallen",
        "pin": pin_number,
        "game_state": current_game.to_dict(),
        **result
    })

    # Chuza detectada automáticamente (10 pines de una)
    if result.get("auto_commit"):
        is_strike_turn = True
        logger.info("🎳 ¡CHUZA! Esperando retorno de bola para resetear")


async def on_ball_returned():
    """
    Sensor detectó retorno de bola.
    - 1er retorno sin chuza → nada, jugador tira 2do tiro
    - 1er retorno con chuza → resetear pines y cambiar jugador
    - 2do retorno → resetear pines y cambiar jugador
    """
    global current_game, ball_return_count, is_strike_turn, last_ball_time

    # Ignorar si el último retorno fue hace menos de 5 segundos
    # (evita que los 2 sensores cuenten la misma bola dos veces)
    now = time.time()
    elapsed = now - last_ball_time
    if elapsed < 5.0:
        logger.info(f"🎱 Retorno ignorado — misma bola detectada por 2do sensor ({elapsed:.1f}s)")
        return
    last_ball_time = now

    if gpio_handler:
        await gpio_handler.bola_lista()
    await manager.broadcast({"type": "ball_ready"})

    if not current_game:
        return

    ball_return_count += 1
    logger.info(f"🎱 Retorno de bola #{ball_return_count} — chuza={is_strike_turn}")

    # Siempre confirmar el tiro actual al retornar la bola
    result = current_game.commit_current_roll()
    if result and result.get("committed"):
        await manager.broadcast({
            "type": "roll_committed",
            "game_state": current_game.to_dict(),
            **(result or {})
        })

    # Chuza o 2do retorno → resetear pines y cambiar jugador
    debe_resetear = is_strike_turn or ball_return_count >= 2

    if not debe_resetear:
        logger.info(f"🎱 1er retorno sin chuza — esperando 2do tiro")
        return

    logger.info(f"🎱 Reseteando pines — {'chuza' if is_strike_turn else '2do retorno'}")
    ball_return_count = 0
    is_strike_turn = False

    await manager.broadcast({
        "type": "pins_reset",
        "game_state": current_game.to_dict()
    })

    # Iniciar timer 20s para ordenar pines
    if gpio_handler:
        await gpio_handler.secuencia_ordenar_pines()
        await manager.broadcast({
            "type": "ordering_pins",
            "timer_seconds": 20
        })


async def on_timer_done():
    """Timer 20s terminó → solo notificar, los pines ya se resetearon antes"""
    logger.info("⏱️ Timer terminado — listo para jugar")
    await manager.broadcast({"type": "timer_done"})


# ─── ENDPOINTS DE PARTIDA ────────────────────────────────────────────────────

@app.post("/api/game/new")
async def new_game(request: NewGameRequest):
    global current_game, ball_return_count, is_strike_turn
    ball_return_count = 0
    is_strike_turn = False
    current_game = BowlingGame(players=request.players, config=current_config)
    game_dict = current_game.to_dict()

    if gpio_handler:
        gpio_handler.led_rojo(True)

    await manager.broadcast({"type": "game_started", "game_state": game_dict})
    logger.info(f"🎳 Nueva partida con {len(request.players)} jugadores")
    return {"status": "ok", "game": game_dict}


@app.get("/api/game/current")
async def get_current_game():
    if not current_game:
        raise HTTPException(status_code=404, detail="No hay partida activa")
    return current_game.to_dict()


@app.post("/api/game/reset-pins")
async def reset_pins():
    """Solo para uso manual desde la web (corrección o testing)"""
    global ball_return_count, is_strike_turn
    if not current_game:
        raise HTTPException(status_code=404, detail="No hay partida activa")

    ball_return_count = 0
    is_strike_turn = False
    result = current_game.commit_current_roll()

    await manager.broadcast({
        "type": "roll_committed",
        "game_state": current_game.to_dict(),
        **(result or {})
    })
    await manager.broadcast({
        "type": "pins_reset",
        "game_state": current_game.to_dict()
    })
    return {"status": "ok"}


@app.post("/api/game/manual-pin")
async def manual_pin_update(update: ManualPinUpdate):
    """Registrar pin manualmente (testing o corrección)"""
    await on_pin_fallen(update.pin_number)
    return {"status": "ok"}


@app.post("/api/game/end")
async def end_game():
    global current_game, ball_return_count, is_strike_turn
    if not current_game:
        raise HTTPException(status_code=404, detail="No hay partida activa")

    current_game.end_game()
    await manager.broadcast({"type": "game_ended", "game_state": current_game.to_dict()})

    if gpio_handler:
        gpio_handler.apagar_todo()

    current_game = None
    ball_return_count = 0
    is_strike_turn = False
    return {"status": "ok"}


# ─── CONFIGURACIÓN ───────────────────────────────────────────────────────────

@app.get("/api/config")
async def get_config():
    return current_config


@app.put("/api/config")
async def update_config(config: GameConfig):
    global current_config
    current_config = config.dict()
    await manager.broadcast({"type": "config_updated", "config": current_config})
    return {"status": "ok", "config": current_config}


@app.get("/api/gpio/map")
async def get_gpio_map():
    if gpio_handler:
        return gpio_handler.get_pin_map()
    return {}


# ─── WEBSOCKET ───────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        if current_game:
            await websocket.send_json({
                "type": "initial_state",
                "game_state": current_game.to_dict()
            })
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            if msg.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# ─── FRONTEND ────────────────────────────────────────────────────────────────

frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)