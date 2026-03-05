"""
GPIO Handler para Raspberry Pi
Maneja los 10 limit switches (finales de carrera), uno por pin de bowling
Usa interrupciones para detectar cambios sin polling
"""

import asyncio
import logging
from typing import Callable, Optional
import os

logger = logging.getLogger(__name__)

# Pines GPIO BCM asignados a cada pin de bowling (1-10)
# Ajustar según el cableado real en la Raspberry Pi
PIN_GPIO_MAP = {
    1:  17,   # Pin de bowling 1  → GPIO 17
    2:  18,   # Pin de bowling 2  → GPIO 18
    3:  27,   # Pin de bowling 3  → GPIO 27
    4:  22,   # Pin de bowling 4  → GPIO 22
    5:  23,   # Pin de bowling 5  → GPIO 23
    6:  24,   # Pin de bowling 6  → GPIO 24
    7:  25,   # Pin de bowling 7  → GPIO 25
    8:  4,    # Pin de bowling 8  → GPIO 4
    9:  5,    # Pin de bowling 9  → GPIO 5
    10: 6,    # Pin de bowling 10 → GPIO 6
}

# Debounce en ms para evitar lecturas múltiples de un mismo golpe
DEBOUNCE_MS = 300

# Detectar si estamos en una Raspberry Pi real
IS_RASPBERRY_PI = os.path.exists("/sys/bus/platform/drivers/raspberrypi-firmware")


class GPIOHandler:
    """
    Maneja los 10 limit switches vía GPIO.
    En modo simulación (no Raspberry Pi) permite testing sin hardware.
    """

    def __init__(self, pin_callback: Callable):
        self.pin_callback = pin_callback  # async callback(pin_number: int)
        self.gpio = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._simulation_mode = not IS_RASPBERRY_PI

    async def setup(self):
        """Inicializar GPIO o modo simulación"""
        self.loop = asyncio.get_event_loop()

        if self._simulation_mode:
            logger.warning("⚠️  GPIO en MODO SIMULACIÓN (no es Raspberry Pi)")
            logger.info("   Usar POST /api/game/manual-pin para simular pines")
            return

        try:
            import RPi.GPIO as GPIO
            self.gpio = GPIO
            self.gpio.setmode(GPIO.BCM)
            self.gpio.setwarnings(False)

            for pin_num, gpio_pin in PIN_GPIO_MAP.items():
                # Configurar como entrada con resistencia pull-up
                # El limit switch conecta el pin a GND cuando se activa
                self.gpio.setup(gpio_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

                # Detectar flanco de bajada (HIGH→LOW = switch activado)
                self.gpio.add_event_detect(
                    gpio_pin,
                    GPIO.FALLING,
                    callback=self._make_callback(pin_num),
                    bouncetime=DEBOUNCE_MS
                )
                logger.info(f"   Pin bowling {pin_num} → GPIO {gpio_pin} configurado")

            logger.info("✅ GPIO configurado correctamente")

        except ImportError:
            logger.error("❌ RPi.GPIO no instalado. Ejecutar: pip install RPi.GPIO")
            self._simulation_mode = True
        except Exception as e:
            logger.error(f"❌ Error al configurar GPIO: {e}")
            self._simulation_mode = True

    def _make_callback(self, pin_number: int):
        """Crear callback para un pin específico"""
        def callback(channel):
            logger.info(f"🎳 Limit switch activado: Pin {pin_number} (GPIO {channel})")
            # Programar la corrutina async desde el thread de GPIO
            if self.loop and self.loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self.pin_callback(pin_number),
                    self.loop
                )
        return callback

    async def simulate_pin(self, pin_number: int):
        """Simular la caída de un pin (solo para testing)"""
        if 1 <= pin_number <= 10:
            logger.info(f"🎮 Simulando pin {pin_number}")
            await self.pin_callback(pin_number)
        else:
            logger.error(f"Número de pin inválido: {pin_number} (debe ser 1-10)")

    def cleanup(self):
        """Limpiar recursos GPIO"""
        if self.gpio and not self._simulation_mode:
            try:
                self.gpio.cleanup()
                logger.info("GPIO limpiado correctamente")
            except Exception as e:
                logger.error(f"Error al limpiar GPIO: {e}")

    @property
    def is_simulation(self) -> bool:
        return self._simulation_mode

    def get_pin_map(self) -> dict:
        """Retornar el mapa de pines para documentación"""
        return {
            f"bowling_pin_{k}": f"GPIO_{v} (BCM)"
            for k, v in PIN_GPIO_MAP.items()
        }
