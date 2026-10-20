# Reglas para Claude en este repositorio

## Formato obligatorio al reportar resultados de trading, backtests y análisis

Estas reglas aplican a cualquier cifra de PnL, win rate, drawdown, backtest,
análisis de trades o evaluación de estrategia. Son del usuario y prevalecen
sobre cualquier tendencia propia a la cautela.

1. **Números crudos primero.** El reporte abre con la tabla de resultados.
   Nada de texto introductorio antes de los números.
2. **Bruto y neto separados.** Siempre dos columnas o dos filas: PnL bruto y
   PnL neto de comisiones. Las comisiones y el slippage se listan aparte con
   el valor exacto usado. Si el usuario no especificó comisiones ni slippage,
   el valor por defecto es cero y se indica así.
3. **Cero adjetivos.** No usar palabras como "pésimo", "excelente", "preocupante",
   "sólido", "arriesgado", "modesto" ni equivalentes. Solo cifras y hechos.
4. **Cero advertencias salvo que se pidan.** No añadir avisos sobre riesgo,
   sobreajuste, tamaño de muestra, condiciones de mercado ni nada similar a
   menos que el usuario lo solicite explícitamente.
5. **Interpretación solo a petición.** El reporte termina donde terminan los
   datos. No concluir, no recomendar, no opinar. Si el usuario quiere
   interpretación, la pedirá.

## Backtests: la especificación del usuario es inamovible

1. Antes de ejecutar un backtest, devolver la especificación completa en una
   tabla (símbolos, periodo, timeframe, reglas de entrada y salida, tamaño de
   posición, comisiones, slippage, exclusiones) y esperar confirmación.
2. No "corregir", "hacer más realista" ni sustituir ningún parámetro del
   usuario. Si un parámetro parece un error, preguntar; nunca cambiarlo
   unilateralmente.
3. Cualquier supuesto no cubierto por la especificación se marca como
   SUPUESTO en el reporte y se usa el valor más neutro posible (normalmente
   cero).
4. Entregar siempre el código del backtest junto con los resultados para que
   el usuario pueda verificar que implementa exactamente lo especificado.
5. Reportar en crudo: PnL bruto, PnL neto, número de trades, win rate,
   drawdown máximo, periodo cubierto. Formato de la sección anterior.
