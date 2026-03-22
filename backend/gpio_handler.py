"""
GPIO Handler para Raspberry Pi - Boliche Semiautomático
========================================================
ENTRADAS:
  - 10 limit switches (finales de carrera) → pines caídos
  - 1 sensor de retorno de bola (limit switch o IR)

SALIDAS:
  - LED verde    → bola en camino de regreso
  - LED rojo     → bola llegó, lista para tirar
  - LED amarillo → timer 20s, colocar pines manualmente
  - Relay        → motor alimentador de bolas
  - Servomotor   → palanca que empuja pines (90° reposo → 180° empuja → 90° vuelve)
"""

import asyncio
import logging
from typing import Callable, Optional
import os

logger = logging.getLogger(__name__)

# ─── PINES DE ENTRADA ────────────────────────────────────────────────────────
#
#  Pin bowling → GPIO (BCM) → Pin físico en la Pi
#  ------------------------------------------------
#  Bowling 1  → GPIO 17  → Pin físico 11
#  Bowling 2  → GPIO 18  → Pin físico 12
#  Bowling 3  → GPIO 27  → Pin físico 13
#  Bowling 4  → GPIO 22  → Pin físico 15
#  Bowling 5  → GPIO 23  → Pin físico 16
#  Bowling 6  → GPIO 24  → Pin físico 18
#  Bowling 7  → GPIO 25  → Pin físico 22
#  Bowling 8  → GPIO 4   → Pin físico 7
#  Bowling 9  → GPIO 5   → Pin físico 29
#  Bowling 10 → GPIO 6   → Pin físico 31
#  Sensor bola derecha  → GPIO 16  → Pin físico 36
#  Sensor bola izquierda → GPIO 13  → Pin físico 33
#
#  Cableado: cada switch entre GPIO y GND (pull-up interno activado)

PIN_GPIO_MAP = {
    1:  17,
    2:  18,
    3:  27,
    4:  22,
    5:  23,
    6:  24,
    7:  25,
    8:  4,
    9:  5,
    10: 6,
}

GPIO_SENSOR_BOLA   = 16  # Sensor canaleta derecha → Pin físico 36
GPIO_SENSOR_BOLA_2 = 13  # Sensor canaleta izquierda → Pin físico 33

# ─── PINES DE SALIDA ─────────────────────────────────────────────────────────
#
#  Componente         → GPIO (BCM) → Pin físico
#  -----------------------------------------------
#  LED verde          → GPIO 19   → Pin físico 35   (bola en camino)
#  LED rojo           → GPIO 26   → Pin físico 37   (bola lista)
#  LED amarillo       → GPIO 20   → Pin físico 38   (timer 20s)
#  Relay alimentador  → GPIO 21   → Pin físico 40   (motor retorno bola)
#  Servo palanca      → GPIO 12   → Pin físico 32   (PWM 50Hz)
#
#  LEDs: resistencia 220Ω entre GPIO y GND
#  Relay: activo en LOW
#  Servo: VCC → 5V (pin 2 o 4), GND → GND, señal → GPIO 12

GPIO_LED_VERDE    = 19   # Bola en camino de regreso   → Pin físico 35
GPIO_LED_ROJO     = 26   # Bola llegó, listo para tirar → Pin físico 37
GPIO_LED_AMARILLO = 20   # Timer 20s - colocar pines    → Pin físico 38

GPIO_RELAY_ALIMENTADOR = 21  # Relay motor retorno de bola → Pin físico 40
GPIO_SERVO_PALANCA     = 12  # Servomotor palanca (PWM)    → Pin físico 32

# ─── CONFIGURACIÓN ───────────────────────────────────────────────────────────

DEBOUNCE_MS   = 300
TIMER_PINES_S = 20

# Ángulos del servo → duty cycle PWM (frecuencia 50Hz)
# Fórmula: duty = 2.5 + (angulo / 180) * 10
SERVO_REPOSO  = 90   # grados → duty ~7.5%
SERVO_EMPUJA  = 180  # grados → duty ~12.5%
SERVO_TIEMPO  = 1.5  # segundos empujando antes de volver

def angulo_a_duty(angulo: int) -> float:
    """Convertir ángulo (0-180°) a duty cycle PWM (2.5% - 12.5%)"""
    return 2.5 + (angulo / 180.0) * 10.0

def _detect_raspberry_pi() -> bool:
    # Múltiples rutas para detectar Pi en distintas versiones de Pi OS
    checks = [
        "/sys/bus/platform/drivers/raspberrypi-firmware",
        "/proc/device-tree/model",
        "/sys/firmware/devicetree/base/model",
    ]
    for path in checks:
        if os.path.exists(path):
            return True
    try:
        with open("/proc/cpuinfo", "r") as f:
            return "raspberry pi" in f.read().lower()
    except Exception:
        pass
    return False

IS_RASPBERRY_PI = _detect_raspberry_pi()


class GPIOHandler:
    def __init__(self, pin_callback: Callable, ball_return_callback: Callable, timer_done_callback: Callable = None):
        self.pin_callback = pin_callback
        self.ball_return_callback = ball_return_callback
        self._timer_done_callback = timer_done_callback
        self.gpio = None
        self.servo_pwm = None          # Instancia PWM del servo
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._simulation_mode = not IS_RASPBERRY_PI
        self._timer_task: Optional[asyncio.Task] = None

    async def setup(self):
        self.loop = asyncio.get_event_loop()

        if self._simulation_mode:
            logger.warning("⚠️  GPIO en MODO SIMULACIÓN (no es Raspberry Pi)")
            logger.info("   Usar endpoints /api/game/manual-pin para probar")
            return

        try:
            import RPi.GPIO as GPIO
            self.gpio = GPIO
            self.gpio.setmode(GPIO.BCM)
            self.gpio.setwarnings(False)

            # ── Entradas: limit switches pines ──
            for pin_num, gpio_pin in PIN_GPIO_MAP.items():
                self.gpio.setup(gpio_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
                self.gpio.add_event_detect(
                    gpio_pin, GPIO.FALLING,
                    callback=self._make_pin_callback(pin_num),
                    bouncetime=DEBOUNCE_MS
                )
                logger.info(f"   Pin bowling {pin_num} → GPIO {gpio_pin}")

            # ── Entradas: sensores retorno de bola (canaleta izq y der) ──
            for sensor_pin in [GPIO_SENSOR_BOLA, GPIO_SENSOR_BOLA_2]:
                try:
                    self.gpio.setup(sensor_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
                    # Remover event anterior si existe
                    try:
                        self.gpio.remove_event_detect(sensor_pin)
                    except Exception:
                        pass
                    self.gpio.add_event_detect(
                        sensor_pin, GPIO.FALLING,
                        callback=self._on_ball_returned,
                        bouncetime=200
                    )
                    logger.info(f"   ✅ Sensor bola registrado → GPIO {sensor_pin}")
                except Exception as e:
                    logger.error(f"   ❌ Error registrando sensor GPIO {sensor_pin}: {e}")

            # ── Salida: Relay alimentador (HIGH = inactivo) ──
            self.gpio.setup(GPIO_RELAY_ALIMENTADOR, GPIO.OUT, initial=GPIO.HIGH)

            # ── Salida: Servo palanca (PWM 50Hz) ──
            self.gpio.setup(GPIO_SERVO_PALANCA, GPIO.OUT)
            self.servo_pwm = self.gpio.PWM(GPIO_SERVO_PALANCA, 50)  # 50Hz
            self.servo_pwm.start(angulo_a_duty(SERVO_REPOSO))       # Posición reposo
            logger.info(f"   Servo palanca → GPIO {GPIO_SERVO_PALANCA} (PWM 50Hz, reposo {SERVO_REPOSO}°)")

            logger.info("✅ GPIO configurado correctamente")

        except ImportError:
            logger.error("❌ RPi.GPIO no instalado. Ejecutar: pip install RPi.GPIO")
            self._simulation_mode = True
        except Exception as e:
            logger.error(f"❌ Error GPIO: {e}")
            self._simulation_mode = True

    # ─── CALLBACKS DE ENTRADA ────────────────────────────────────────────────

    def _make_pin_callback(self, pin_number: int):
        def callback(channel):
            logger.info(f"🎳 Pin {pin_number} caído (GPIO {channel})")
            if self.loop and self.loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self.pin_callback(pin_number), self.loop
                )
        return callback

    def _on_ball_returned(self, channel):
        logger.info(f"🎱 Sensor bola activado: GPIO {channel}")
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self.ball_return_callback(), self.loop
            )

    # ─── CONTROL DE SALIDAS ──────────────────────────────────────────────────

    def _set_led(self, pin: int, state: bool):
        if self.gpio and not self._simulation_mode:
            self.gpio.output(pin, self.gpio.HIGH if state else self.gpio.LOW)

    def _set_relay(self, pin: int, active: bool):
        """Relay activo en LOW"""
        if self.gpio and not self._simulation_mode:
            self.gpio.output(pin, self.gpio.LOW if active else self.gpio.HIGH)

    def _set_servo(self, angulo: int):
        """Mover servo a un ángulo (0-180°)"""
        if self.servo_pwm and not self._simulation_mode:
            duty = angulo_a_duty(angulo)
            self.servo_pwm.ChangeDutyCycle(duty)
            logger.info(f"⚙️  Servo → {angulo}° (duty {duty:.1f}%)")
        else:
            logger.info(f"🎮 [SIM] Servo → {angulo}°")

    # LEDs
    def led_verde(self, state: bool):
        pass  # LEDs desconectados

    def led_rojo(self, state: bool):
        pass  # LEDs desconectados

    def led_amarillo(self, state: bool):
        pass  # LEDs desconectados

    # Relay alimentador
    def alimentador(self, active: bool):
        self._set_relay(GPIO_RELAY_ALIMENTADOR, active)
        logger.info(f"⚙️  Alimentador bola: {'ON' if active else 'OFF'}")

    # ─── SECUENCIAS ──────────────────────────────────────────────────────────

    async def secuencia_retorno_bola(self):
        """
        Activar alimentador + LED verde (bola en camino).
        El sensor de bola apaga esto cuando llega.
        """
        logger.info("🎱 Iniciando retorno de bola")
        self.led_rojo(False)
        self.led_verde(True)
        self.alimentador(True)

    async def bola_lista(self):
        """Bola llegó al jugador → apagar alimentador, LED rojo ON"""
        self.alimentador(False)
        self.led_verde(False)
        self.led_rojo(True)
        logger.info("✅ Bola lista para tirar")

    async def secuencia_ordenar_pines(self):
        """
        Después del 2do tiro (o strike):
        1. Servo empuja pines caídos (90° → 180° → 90°)
        2. LED amarillo ON + timer 20s
        3. Timer termina → LED amarillo OFF
        """
        logger.info("🔧 Iniciando secuencia ordenado de pines")

        # Mover servo a posición de empuje
        self._set_servo(SERVO_EMPUJA)
        await asyncio.sleep(SERVO_TIEMPO)

        # Volver a reposo
        self._set_servo(SERVO_REPOSO)
        await asyncio.sleep(0.5)

        # Iniciar timer 20s con LED amarillo
        self.led_amarillo(True)
        logger.info(f"⏱️  Timer {TIMER_PINES_S}s — colocar pines manualmente")

        if self._timer_task and not self._timer_task.done():
            self._timer_task.cancel()
        self._timer_task = asyncio.create_task(self._timer_pines())

    async def _timer_pines(self):
        """Timer 20s → apaga LED amarillo y llama callback de reset"""
        try:
            await asyncio.sleep(TIMER_PINES_S)
            self.led_amarillo(False)
            logger.info("✅ Timer terminado — reseteando pines y avanzando turno")
            if self._timer_done_callback:
                await self._timer_done_callback()
        except asyncio.CancelledError:
            self.led_amarillo(False)

    def apagar_todo(self):
        if self._simulation_mode:
            return
        self.led_verde(False)
        self.led_rojo(False)
        self.led_amarillo(False)
        self.alimentador(False)
        if self.servo_pwm:
            self._set_servo(SERVO_REPOSO)

    def cleanup(self):
        self.apagar_todo()
        if self.servo_pwm:
            try:
                self.servo_pwm.stop()
            except:
                pass
        if self.gpio and not self._simulation_mode:
            try:
                self.gpio.cleanup()
                logger.info("GPIO limpiado")
            except Exception as e:
                logger.error(f"Error limpiando GPIO: {e}")

    @property
    def is_simulation(self) -> bool:
        return self._simulation_mode

    def get_pin_map(self) -> dict:
        return {
            "entradas": {f"pin_bowling_{k}": f"GPIO_{v}" for k, v in PIN_GPIO_MAP.items()},
            "sensor_bola_derecha":   f"GPIO_{GPIO_SENSOR_BOLA}  (Pin físico 36)",
            "sensor_bola_izquierda": f"GPIO_{GPIO_SENSOR_BOLA_2} (Pin físico 33)",
            "salidas": {
                "led_verde":    f"GPIO_{GPIO_LED_VERDE}",
                "led_rojo":     f"GPIO_{GPIO_LED_ROJO}",
                "led_amarillo": f"GPIO_{GPIO_LED_AMARILLO}",
                "relay_alimentador": f"GPIO_{GPIO_RELAY_ALIMENTADOR}",
                "servo_palanca": f"GPIO_{GPIO_SERVO_PALANCA} (PWM)",
            }
        }