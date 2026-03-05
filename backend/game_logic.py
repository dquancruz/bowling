"""
Lógica del juego de bowling clásico (10 frames)
Flujo correcto:
  - Los pines se acumulan mientras caen (via limit switches o clicks)
  - El tiro se REGISTRA cuando se llama a commit_roll()
  - commit_roll() se llama automáticamente si caen los 10 pines (strike)
  - o manualmente cuando el jugador presiona RESETEAR PINES
"""

from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid


class Frame:
    def __init__(self, frame_number: int, is_last: bool = False):
        self.frame_number = frame_number
        self.is_last = is_last
        self.rolls: List[int] = []
        self.is_complete = False

    def can_add_roll(self) -> bool:
        if self.is_complete:
            return False
        if self.is_last:
            # Frame 10: hasta 3 tiros
            if len(self.rolls) == 0:
                return True
            if len(self.rolls) == 1:
                return True
            if len(self.rolls) == 2:
                # Solo si hubo strike o spare en los primeros 2
                return (self.rolls[0] == 10 or self.rolls[0] + self.rolls[1] == 10)
            return False
        else:
            return len(self.rolls) < 2 and not self.is_strike()

    def add_roll(self, pins: int) -> Dict:
        """Registrar un tiro completo (cantidad de pines caídos en ese tiro)"""
        self.rolls.append(pins)
        result = {"roll": len(self.rolls), "pins": pins, "type": None}

        if self.is_last:
            if len(self.rolls) == 1 and pins == 10:
                result["type"] = "strike"
            elif len(self.rolls) == 2:
                if self.rolls[0] == 10 and pins == 10:
                    result["type"] = "strike"
                elif self.rolls[0] != 10 and self.rolls[0] + pins == 10:
                    result["type"] = "spare"
                elif self.rolls[0] != 10 and self.rolls[0] + pins < 10:
                    self.is_complete = True
            elif len(self.rolls) == 3:
                if pins == 10:
                    result["type"] = "strike"
                self.is_complete = True
        else:
            if len(self.rolls) == 1 and pins == 10:
                result["type"] = "strike"
                self.is_complete = True
            elif len(self.rolls) == 2:
                if self.rolls[0] + pins == 10:
                    result["type"] = "spare"
                self.is_complete = True

        return result

    def is_strike(self) -> bool:
        return not self.is_last and len(self.rolls) >= 1 and self.rolls[0] == 10

    def is_spare(self) -> bool:
        return (not self.is_last and len(self.rolls) >= 2
                and self.rolls[0] != 10
                and self.rolls[0] + self.rolls[1] == 10)

    def to_dict(self) -> Dict:
        return {
            "frame_number": self.frame_number,
            "rolls": self.rolls,
            "is_strike": self.is_strike(),
            "is_spare": self.is_spare(),
            "is_complete": self.is_complete,
            "is_last": self.is_last
        }


class PlayerGame:
    def __init__(self, name: str):
        self.name = name
        self.frames: List[Frame] = [
            Frame(i + 1, is_last=(i == 9)) for i in range(10)
        ]
        self.current_frame_idx = 0
        # Pines parados actualmente (True = de pie, False = caído)
        self.pins_up: List[bool] = [True] * 10
        # Cantidad de pines caídos en el tiro actual (pendiente de commit)
        self.pending_pins: int = 0

    @property
    def current_frame(self) -> Optional[Frame]:
        if self.current_frame_idx < 10:
            return self.frames[self.current_frame_idx]
        return None

    def is_finished(self) -> bool:
        return (self.current_frame_idx >= 10 or
                (self.current_frame_idx == 9 and self.frames[9].is_complete))

    def knock_pin(self, pin_number: int) -> Optional[Dict]:
        """
        Registrar un pin caído (1-10).
        Acumula el pin en pending_pins.
        Si caen los 10 (strike), hace commit automático.
        Retorna info del evento o None si el pin ya estaba caído.
        """
        frame = self.current_frame
        if not frame or not frame.can_add_roll():
            return None

        pin_idx = pin_number - 1
        if not self.pins_up[pin_idx]:
            return None  # Ya estaba caído

        self.pins_up[pin_idx] = False
        self.pending_pins += 1

        pins_standing = self.pins_up.count(True)
        auto_commit = False

        # Strike: cayeron todos en el primer tiro del frame
        if pins_standing == 0:
            auto_commit = True

        result = {
            "pin": pin_number,
            "pending_pins": self.pending_pins,
            "pins_standing": pins_standing,
            "auto_commit": auto_commit,
        }

        if auto_commit:
            commit_result = self.commit_roll()
            result.update(commit_result)

        return result

    def commit_roll(self) -> Dict:
        """
        Confirmar el tiro actual con los pines acumulados.
        Se llama automáticamente en strike, o manualmente al RESETEAR PINES.
        """
        frame = self.current_frame
        if not frame:
            return {"committed": False}

        pins = self.pending_pins
        self.pending_pins = 0

        roll_result = frame.add_roll(pins)

        result = {
            "committed": True,
            "pins_in_roll": pins,
            "roll_type": roll_result.get("type"),
            "frame_complete": frame.is_complete,
            "turn_changed": False,
        }

        if frame.is_complete:
            self.current_frame_idx += 1
            result["turn_changed"] = True

        # Resetear pines para el siguiente tiro
        # En frame 10 con strike/spare, resetear pines para el tiro bonus
        self.pins_up = [True] * 10

        return result

    def calculate_score(self) -> List[Optional[int]]:
        scores = []
        all_rolls = []
        for frame in self.frames:
            all_rolls.extend(frame.rolls)

        roll_idx = 0
        cumulative = 0

        for i, frame in enumerate(self.frames):
            if not frame.rolls:
                scores.append(None)
                continue

            if i == 9:
                frame_score = sum(frame.rolls)
                cumulative += frame_score
                scores.append(cumulative if frame.is_complete else None)
                break

            if frame.is_strike():
                b1 = all_rolls[roll_idx + 1] if roll_idx + 1 < len(all_rolls) else None
                b2 = all_rolls[roll_idx + 2] if roll_idx + 2 < len(all_rolls) else None
                if b1 is not None and b2 is not None:
                    cumulative += 10 + b1 + b2
                    scores.append(cumulative)
                else:
                    scores.append(None)
                roll_idx += 1
            elif frame.is_spare():
                b1 = all_rolls[roll_idx + 2] if roll_idx + 2 < len(all_rolls) else None
                if b1 is not None:
                    cumulative += 10 + b1
                    scores.append(cumulative)
                else:
                    scores.append(None)
                roll_idx += 2
            else:
                if frame.is_complete:
                    cumulative += sum(frame.rolls)
                    scores.append(cumulative)
                else:
                    scores.append(None)
                roll_idx += len(frame.rolls)

        # Rellenar frames vacíos al final
        while len(scores) < 10:
            scores.append(None)

        return scores

    def total_score(self) -> int:
        scores = self.calculate_score()
        for s in reversed(scores):
            if s is not None:
                return s
        return 0

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "frames": [f.to_dict() for f in self.frames],
            "scores": self.calculate_score(),
            "total": self.total_score(),
            "current_frame": self.current_frame_idx + 1,
            "is_finished": self.is_finished(),
            "pins_up": self.pins_up,
            "pending_pins": self.pending_pins,
        }


class BowlingGame:
    def __init__(self, players: List[str], config: Dict):
        self.game_id = str(uuid.uuid4())
        self.players = [PlayerGame(name) for name in players]
        self.config = config
        self.current_player_idx = 0
        self.status = "active"
        self.created_at = datetime.utcnow().isoformat()
        self.finished_at = None

    @property
    def current_player(self) -> Optional[PlayerGame]:
        if self.current_player_idx < len(self.players):
            return self.players[self.current_player_idx]
        return None

    def register_pin_fall(self, pin_number: int) -> Optional[Dict]:
        """Pin cae → acumular. Si son 10 → strike automático."""
        if self.status != "active" or not self.current_player:
            return None

        player = self.current_player
        result = player.knock_pin(pin_number)
        if not result:
            return None

        result["player"] = player.name
        result["frame"] = player.current_frame_idx + 1 if not result.get("turn_changed") else player.current_frame_idx

        if result.get("turn_changed"):
            self._advance_player()
            result["next_player"] = self.current_player.name if self.current_player else None

        result["game_over"] = all(p.is_finished() for p in self.players)
        if result["game_over"]:
            self.end_game()
            result["winner"] = self._get_winner()

        return result

    def commit_current_roll(self) -> Optional[Dict]:
        """
        Confirmar el tiro actual (llamado al RESETEAR PINES).
        Solo actúa si hay pines pendientes de confirmar.
        """
        if self.status != "active" or not self.current_player:
            return None

        player = self.current_player
        if player.pending_pins == 0:
            # No hay nada pendiente, solo resetear visualmente
            player.pins_up = [True] * 10
            return {"committed": False, "message": "Sin pines pendientes"}

        result = player.commit_roll()
        result["player"] = player.name

        if result.get("turn_changed"):
            self._advance_player()
            result["next_player"] = self.current_player.name if self.current_player else None

        result["game_over"] = all(p.is_finished() for p in self.players)
        if result["game_over"]:
            self.end_game()
            result["winner"] = self._get_winner()

        return result

    def _advance_player(self):
        self.current_player_idx = (self.current_player_idx + 1) % len(self.players)

    def _get_winner(self) -> Optional[str]:
        if not self.players:
            return None
        return max(self.players, key=lambda p: p.total_score()).name

    def end_game(self):
        self.status = "finished"
        self.finished_at = datetime.utcnow().isoformat()

    def to_dict(self) -> Dict:
        return {
            "game_id": self.game_id,
            "status": self.status,
            "players": [p.to_dict() for p in self.players],
            "current_player": self.current_player.name if self.current_player else None,
            "current_player_idx": self.current_player_idx,
            "config": self.config,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "winner": self._get_winner() if self.status == "finished" else None
        }