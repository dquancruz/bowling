"""
Bowling Semiautomático - Backend Principal
FastAPI + GPIO + WebSockets (sin base de datos)

Secuencia completa:
  1. Jugador tira → limit switches detectan pines caídos
  2. RESETEAR PINES → confirma tiro, activa retorno de bola + LED verde
  3. Sensor detecta bola → LED rojo ON, bola lista para tirar
  4. Fin de frame → servo empuja pines + LED amarillo + timer 20s
  5. Timer termina → LED amarillo OFF, listo para nuevo turno
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import json
import logging
from typing import Optional
import os

from models import GameConfig, NewGameRequest, ManualPinUpdate
from game_logic import BowlingGame
from gpio_handler import GPIOHandler
from websocket_manager import ConnectionManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

current_game: Optional[BowlingGame] = None
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
        ball_return_callback=on_ball_returned
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
    """Limit switch activado → registrar pin caído"""
    global current_game
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

    # Strike: commit automático → iniciar secuencia post-tiro
    if result.get("auto_commit"):
        await _post_roll(result)


async def on_ball_returned():
    """Sensor detectó que la bola llegó de vuelta"""
    if gpio_handler:
        await gpio_handler.bola_lista()
    await manager.broadcast({"type": "ball_ready"})


async def _post_roll(commit_result: dict):
    """
    Acciones después de confirmar un tiro:
    - Siempre: retornar bola (relay + LED verde)
    - Si frame completo: servo empuja pines + LED amarillo + timer 20s
    """
    if not gpio_handler:
        return

    await gpio_handler.secuencia_retorno_bola()
    await manager.broadcast({"type": "ball_returning"})

    if commit_result.get("frame_complete"):
        await gpio_handler.secuencia_ordenar_pines()
        await manager.broadcast({
            "type": "ordering_pins",
            "timer_seconds": 20
        })


# ─── ENDPOINTS DE PARTIDA ────────────────────────────────────────────────────

@app.post("/api/game/new")
async def new_game(request: NewGameRequest):
    global current_game
    current_game = BowlingGame(players=request.players, config=current_config)
    game_dict = current_game.to_dict()

    # LED rojo ON → bola lista para el primer tiro
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
    """
    Confirmar el tiro actual e iniciar secuencia post-tiro.
    En hardware real: llamar cuando el jugador termina de tirar.
    """
    if not current_game:
        raise HTTPException(status_code=404, detail="No hay partida activa")

    result = current_game.commit_current_roll()

    await manager.broadcast({
        "type": "roll_committed",
        "game_state": current_game.to_dict(),
        **(result or {})
    })

    # Iniciar secuencia post-tiro
    if result and result.get("committed"):
        await _post_roll(result)

    return {"status": "ok", "result": result}


@app.post("/api/game/manual-pin")
async def manual_pin_update(update: ManualPinUpdate):
    """Registrar pin manualmente (testing o corrección)"""
    await on_pin_fallen(update.pin_number)
    return {"status": "ok"}


@app.post("/api/game/end")
async def end_game():
    global current_game
    if not current_game:
        raise HTTPException(status_code=404, detail="No hay partida activa")

    current_game.end_game()
    await manager.broadcast({"type": "game_ended", "game_state": current_game.to_dict()})

    if gpio_handler:
        gpio_handler.apagar_todo()

    current_game = None
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
    """Ver el mapa de pines GPIO"""
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