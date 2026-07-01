# -*- coding: utf-8 -*-
"""Backfill de poultry.batch.indicator.weekly.value (agregado semanal persistente,
anclado a la Semana de Vida de cada lote) a partir de los Cierres de Galpón
históricos.

Esta tabla es nueva: aunque poultry.batch.indicator.value ya tenía los datos
diarios, el agregado semanal recién se empieza a calcular y guardar solo a
partir de esta versión (poultry.batch.indicator.value._set_value ahora también
actualiza la semana correspondiente). Se reutiliza el mismo mecanismo de
recálculo completo ya usado para los valores diarios, que como efecto
secundario también puebla la tabla semanal.
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
        'Poultry: recalculados indicadores diarios y semanales para %s Cierres de '
        'Galpón históricos (incluye el nuevo agregado semanal persistente).', count
    )
