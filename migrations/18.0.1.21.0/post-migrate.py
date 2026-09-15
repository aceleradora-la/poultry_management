# -*- coding: utf-8 -*-
"""Completa value_low/value_high en poultry.batch.indicator.weekly.value.

Estos dos campos son nuevos: las filas semanales ya existentes (creadas antes
de esta versión) solo tienen real_value. No hace falta un rebuild completo
(real_value ya está bien calculado) — alcanza con recorrer las filas
existentes y calcular Bajo/Alto con la Versión de Estándar predeterminada de
la genética de cada lote, igual que hace
poultry.batch.indicator.value._recompute_weekly_value de ahora en más.
"""

import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("SELECT to_regclass('poultry_batch_indicator_weekly_value')")
    if not cr.fetchone()[0]:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    weekly_values = env['poultry.batch.indicator.weekly.value'].search([])
    count = 0
    for weekly in weekly_values:
        batch = weekly.batch_id
        if not batch.genetics_id:
            continue
        value_low, value_high = batch.genetics_id.get_standard_range(
            weekly.week, weekly.indicator_id, period=weekly.period
        )
        weekly.write({'value_low': value_low, 'value_high': value_high})
        count += 1

    _logger.info(
        'Poultry: completado Bajo/Alto en %s valores reales semanales existentes.', count
    )
