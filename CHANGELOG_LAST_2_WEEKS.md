# Changelog - Últimas 2 Semanas

## 2026-04-20 (HOY)

### FIX: Restore algo orders for stop loss - fixes error -4120 [8967c47]
**Problema identificado:**
- Commit 37b26c2 rompió órdenes SL para TRADOORUSDT, MONUSDT y otros pares
- Error Binance -4120: "Order type not supported for this endpoint"
- Posiciones se abrían **sin protección de stop loss**

**Causa raíz:**
- Se cambió de endpoint `/fapi/v1/algoOrder` (funciona) a `/fapi/v1/order` (no funciona para ciertos pares)
- Se cambió de `algoType: CONDITIONAL` a `STOP_MARKET` regular
- Ciertos pares requieren órdenes algorítmicas obligatoriamente

**Solución:**
- ✓ Revertido a usar `algoType: CONDITIONAL` via `/fapi/v1/algoOrder`
- ✓ Mantenidas mejoras de reintentos y logging de errores
- ✓ Actualizado `cancel_all_orders()` para cancelar órdenes regulares Y algorítmicas
- ✓ Colocado SL faltante para posición MONUSDT actualmente abierta
- ✓ Agregada verificación automática y colocación de SL faltantes cada 5 candles
- ✓ Cierre automático de posición si no se puede colocar SL

**Impacto:**
- Stop loss ahora funciona en TODOS los pares (TRADOORUSDT, MONUSDT, etc.)
- Mantiene buffer de 0.5% para garantizar ejecución
- Mejor manejo de errores con 3 reintentos automáticos

---

## 2026-04-18

### CRITICAL FIX: Stop loss not executing - prevent account blowouts [37b26c2]
**Problema original:**
- Pérdida de 80% de cuenta en un solo trade
- Stop loss no se ejecutaba cuando precio saltaba más de 0.5%

**Cambios implementados:**
1. **Position Size Safety:**
   - MAX_LEVEL: 10 → 3 (reduce exposición máxima)
   - Agregado MARTINGALE_MULTIPLIER = 1.5 (configurable)
   - Agregado MAX_POSITION_PCT = 0.25 (freno de emergencia)

2. **Emergency Brake:**
   - Limita posición a 25% del margen de cuenta
   - Logs de advertencia cuando se aplica el límite

3. **Stop Loss Execution (REVERTIDO EN 2026-04-20):**
   - ❌ Cambió de STOP_LIMIT a STOP_MARKET (causó error -4120)
   - ❌ Cambió de `/fapi/v1/algoOrder` a `/fapi/v1/order` (rompió soporte para algunos pares)

**Impacto de position sizing:**
- Tamaño máximo de posición: 202% vs 3460% antes
- Pérdida máxima por trade: 0.4% vs 80% antes
- Pérdida máxima de chain completo: ~1% de cuenta

---

## 2026-04-15

### Update config: scan interval and martingale multiplier [c0bd336]
- Intervalo de escaneo: 150 segundos (2.5 minutos)
- Martingale multiplier: 3x → 1.5x (más conservador)

**Razón:**
- Reducir agresividad del martingale
- Evitar sobredimensionamiento de posiciones

---

## 2026-04-14

### Initial commit: Binance Railway Bot v1.0 [3a02aa5]
- Configuración inicial del proyecto
- Implementación de estrategia martingale
- Scanner de pares con señales RSI, Bollinger, Z-score
- Sistema de gestión de riesgo
- Deployment en Railway

**Características principales:**
- Leverage: 20x
- TP: 10% | SL: 4%
- Base size: 3% de cuenta
- Filtros de volumen y liquidez
- Detección de régimen de mercado (trending/ranging)

---

## Resumen de Problemas y Soluciones

### Problema 1: Account blowout (80% pérdida)
- **Causa:** Stop loss STOP_LIMIT no ejecutaba cuando precio saltaba
- **Fix:** Reducir MAX_LEVEL de 10 a 3, agregar emergency brake

### Problema 2: SL no se coloca (error -4120)
- **Causa:** Cambio de algo orders a regular STOP_MARKET
- **Fix:** Revertir a usar algoType: CONDITIONAL via /fapi/v1/algoOrder

### Problema 3: Posiciones sin SL después de restart
- **Causa:** Bot adoptaba posiciones pero no verificaba/colocaba SL faltantes
- **Fix:** Agregada verificación automática al adoptar posiciones y cada 5 candles

---

## Configuración Actual (2026-04-20)

```python
# Stop Loss
SL_PCT = 0.04  # 4% price-based stop loss
SL_LIMIT_BUFFER_PCT = 0.005  # 0.5% buffer beyond trigger

# Position Sizing
BASE_SIZE_PCT = 0.03  # 3% of account
MARTINGALE_MULTIPLIER = 1.5  # 1.5x per level
MAX_LEVEL = 3  # Maximum 3 levels (0-3)
MAX_POSITION_PCT = 0.25  # Emergency brake: 25% max margin

# Leverage & Targets
LEVERAGE = 20  # 20x leverage
TP_PCT = 0.10  # 10% take profit

# Safety
MAX_HOLD_CANDLES = 54  # 2.25 hours timeout
COOLDOWN_CANDLES = 4  # 10 min cooldown after loss
```

**Tamaños de posición por nivel:**
- Level 0: 60% de cuenta (3% × 1.0 × 20x)
- Level 1: 90% de cuenta (3% × 1.5 × 20x)
- Level 2: 135% de cuenta (3% × 2.25 × 20x)
- Level 3: 202% de cuenta (3% × 3.38 × 20x) **MAX**

**Pérdida máxima por trade:**
- Level 0: 0.12% de cuenta
- Level 1: 0.18% de cuenta
- Level 2: 0.27% de cuenta
- Level 3: 0.40% de cuenta
- **Total chain:** ~0.97% de cuenta

---

## Estado Actual

✓ Stop loss funciona en todos los pares (usando órdenes algorítmicas)
✓ Verificación automática de SL cada 5 candles
✓ Cierre automático si no se puede colocar SL
✓ Position sizing seguro (max 202% vs 3460% antes)
✓ Emergency brake activo (25% max margin)
✓ Reintentos automáticos (3 intentos) para órdenes SL
✓ Mejor logging de errores de Binance

**Próximos pasos recomendados:**
1. Monitorear ejecución de SL en vivo durante 48 horas
2. Verificar que timeout close funciona correctamente
3. Revisar logs de "EMERGENCY BRAKE" si aparecen
4. Considerar agregar alertas de Telegram para posiciones sin SL
