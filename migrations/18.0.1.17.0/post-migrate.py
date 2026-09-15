# -*- coding: utf-8 -*-
"""Backfill de indicadores reales derivados de Cierres de Galpón.

Esta versión agrega el cálculo de % Ave-Día y Huevos Acumulados Ave-Día, y agrega
numerator/denominator a los indicadores de Consumo (Alimento/Agua) para que los
rollups semanales sumen numerador y denominador en vez de promediar tasas diarias.

Los Cierres de Galpón confirmados ANTES de esta versión ya generaron su OF de
Huevo sin Clasificar, pero button_mark_done() solo se ejecuta una vez, al pasar
la OF a "Hecho" por primera vez — las OF que ya estaban en ese estado antes de
este cambio nunca van a re-disparar el cálculo por sí solas.

Se recorren TODOS los Cierres de Galpón con OF asociada, en orden cronológico
global (no por lote, porque el acumulado de huevos de un lote puede depender de
cierres de distintos galpones), y se recalculan desde cero: rebuild completo,
no incremental, porque el acumulado depende del valor anterior guardado y un
recálculo parcial o fuera de orden lo corrompería.
"""

import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("SELECT to_regclass('poultry_coop_close')")
    if not cr.fetchone()[0]:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    count = env['poultry.coop.close']._poultry_rebuild_all_indicator_values()
    _logger.info(
        'Poultry: recalculados indicadores reales (consumo + producción de huevos) '
        'para %s Cierres de Galpón históricos.', count
    )
