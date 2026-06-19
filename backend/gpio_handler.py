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
  - Servo U izq  → abre en U para limpiar carril (GPIO 7, 0° cerrado → 90° abierto)
  - Servo U der  → abre en U para limpiar carril (GPIO 8, 0° cerrado → 90° abierto)
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
#  Sensor bola izquierda → GPIO 14  → Pin físico 8
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
GPIO_SENSOR_BOLA_2 = 14  # Sensor canaleta izquierda → Pin físico 8

# ─── PINES DE SALIDA ─────────────────────────────────────────────────────────
#
#  Componente         → GPIO (BCM) → Pin físico
#  -----------------------------------------------
#  LED verde          → GPIO 19   → Pin físico 35   (bola en camino)
#  LED rojo           → GPIO 26   → Pin físico 37   (bola lista)
#  LED amarillo       → GPIO 20   → Pin físico 38   (timer 20s)
#  Relay alimentador  → GPIO 21   → Pin físico 40   (motor retorno bola)
#  Servo U izquierdo  → GPIO 12   → Pin físico 32   (PWM 50Hz)
#  Servo U derecho    → GPIO 13   → Pin físico 33   (PWM 50Hz)
#
#  LEDs: resistencia 220Ω entre GPIO y GND
#  Relay: activo en LOW
#  Servos U: VCC → 5V externo, GND común, señal → GPIO 12 / GPIO 13

GPIO_LED_VERDE    = 19   # Bola en camino de regreso   → Pin físico 35
GPIO_LED_ROJO     = 26   # Bola llegó, listo para tirar → Pin físico 37
GPIO_LED_AMARILLO = 20   # Timer 20s - colocar pines    → Pin físico 38

GPIO_RELAY_ALIMENTADOR = 21  # Relay motor retorno de bola → Pin físico 40
GPIO_SERVO_U_IZQ       = 12  # Servo U izquierdo (PWM)     → Pin físico 32
GPIO_SERVO_U_DER       = 13  # Servo U derecho   (PWM)     → Pin físico 33

# ─── CONFIGURACIÓN ───────────────────────────────────────────────────────────

DEBOUNCE_MS   = 300
TIMER_PINES_S = 20

# Ángulos del servo → duty cycle PWM (frecuencia 50Hz)
# Fórmula: duty = 2.5 + (angulo / 180) * 10
SERVO_REPOSO  = 90   # grados → duty ~7.5%
SERVO_EMPUJA  = 180  # grados → duty ~12.5%
SERVO_TIEMPO  = 1.5  # segundos empujando antes de volver

SERVO_U_REPOSO  = 10   # grados → posición cerrada
SERVO_U_ABIERTO = 170  # grados → posición abierta (forma U)
SERVO_U_TIEMPO  = 2.0  # segundos abierto antes de cerrar

def angulo_a_duty(angulo: int) -> float:
    """Convertir ángulo (0-180°) a duty cycle PWM (2.5% - 12.5%)"""
    return 2.5 + (angulo / 180.0) * 10.0

def angulo_a_pulsewidth(angulo: int) -> int:
    """Convertir ángulo (0-180°) a pulsewidth en microsegundos (500-2500µs)"""
    return int(500 + (angulo / 180.0) * 2000)

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
        self.pi = None  # pigpio.pi() para control hardware de servos
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
                    gpio_pin, GPIO.RISING,
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

            # ── Salida: Servos U (pigpio hardware PWM) ──
            # pigpio controla GPIO 12 y 13 directamente; no configurar con RPi.GPIO
            try:
                import pigpio
                self.pi = pigpio.pi()
                if not self.pi.connected:
                    raise RuntimeError("pigpiod no está corriendo (sudo systemctl start pigpiod)")
                self.pi.set_servo_pulsewidth(GPIO_SERVO_U_IZQ, angulo_a_pulsewidth(SERVO_U_REPOSO))
                self.pi.set_servo_pulsewidth(GPIO_SERVO_U_DER, angulo_a_pulsewidth(SERVO_U_REPOSO))
                logger.info(f"   Servo U izq → GPIO {GPIO_SERVO_U_IZQ} (pigpio, reposo {SERVO_U_REPOSO}°)")
                logger.info(f"   Servo U der → GPIO {GPIO_SERVO_U_DER} (pigpio, reposo {SERVO_U_REPOSO}°)")
            except Exception as e:
                logger.error(f"❌ Error inicializando servos pigpio: {e}")
                self.pi = None

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
        """Mover servo palanca (GPIO_SERVO_U_IZQ) a un ángulo"""
        if self.pi and not self._simulation_mode:
            pw = angulo_a_pulsewidth(angulo)
            self.pi.set_servo_pulsewidth(GPIO_SERVO_U_IZQ, pw)
            logger.info(f"⚙️  Servo → {angulo}° ({pw}µs)")
        else:
            logger.info(f"🎮 [SIM] Servo → {angulo}°")

    def _set_servo_u(self, angulo: int):
        """Mover ambos servos U simultáneamente (movimiento simétrico en U)"""
        if self.pi and not self._simulation_mode:
            pw = angulo_a_pulsewidth(angulo)
            self.pi.set_servo_pulsewidth(GPIO_SERVO_U_IZQ, pw)
            self.pi.set_servo_pulsewidth(GPIO_SERVO_U_DER, pw)
            logger.info(f"⚙️  Servo U → {angulo}° ({pw}µs)")
        else:
            logger.info(f"🎮 [SIM] Servo U → {angulo}°")

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

    async def secuencia_abrir_u(self):
        """Abrir los dos servos en U para limpiar el carril, luego cerrar"""
        logger.info("🔧 Abriendo servos U")
        self._set_servo_u(SERVO_U_ABIERTO)
        await asyncio.sleep(SERVO_U_TIEMPO)
        self._set_servo_u(SERVO_U_REPOSO)
        await asyncio.sleep(0.3)
        logger.info("✅ Servos U cerrados")

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
        if self.pi:
            self.pi.set_servo_pulsewidth(GPIO_SERVO_U_IZQ, 0)
            self.pi.set_servo_pulsewidth(GPIO_SERVO_U_DER, 0)

    def cleanup(self):
        self.apagar_todo()
        if self.pi:
            try:
                self.pi.set_servo_pulsewidth(GPIO_SERVO_U_IZQ, 0)
                self.pi.set_servo_pulsewidth(GPIO_SERVO_U_DER, 0)
                self.pi.stop()
                logger.info("pigpio detenido")
            except Exception as e:
                logger.error(f"Error cerrando pigpio: {e}")
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
            "sensor_bola_izquierda": f"GPIO_{GPIO_SENSOR_BOLA_2} (Pin físico 8)",
            "salidas": {
                "led_verde":    f"GPIO_{GPIO_LED_VERDE}",
                "led_rojo":     f"GPIO_{GPIO_LED_ROJO}",
                "led_amarillo": f"GPIO_{GPIO_LED_AMARILLO}",
                "relay_alimentador": f"GPIO_{GPIO_RELAY_ALIMENTADOR}",
                "servo_u_izquierdo": f"GPIO_{GPIO_SERVO_U_IZQ} (PWM, Pin físico 32)",
                "servo_u_derecho":   f"GPIO_{GPIO_SERVO_U_DER} (PWM, Pin físico 33)",
            }
        }