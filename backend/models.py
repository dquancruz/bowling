"""
Modelos Pydantic para validación de requests
"""

from pydantic import BaseModel, Field, validator
from typing import List, Optional


class NewGameRequest(BaseModel):
    players: List[str] = Field(..., min_items=1, max_items=6)

    @validator("players")
    def validate_players(cls, v):
        cleaned = [name.strip() for name in v if name.strip()]
        if not cleaned:
            raise ValueError("Se necesita al menos un jugador")
        if len(cleaned) > 6:
            raise ValueError("Máximo 6 jugadores")
        return cleaned


class ManualPinUpdate(BaseModel):
    pin_number: int = Field(..., ge=1, le=10)


class GameConfig(BaseModel):
    max_players: int = Field(default=6, ge=1, le=8)
    frames_per_game: int = Field(default=10, ge=1, le=10)
    pins_per_frame: int = Field(default=10, ge=1, le=10)
    allow_manual_override: bool = True
    auto_reset_pins: bool = False
    game_mode: str = "classic"