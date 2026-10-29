# -*- coding: utf-8 -*-
"""Semáforo de indicadores (19.0.1.94.0).

1) Carga el sentido inicial de cada indicador (Por Debajo / Por Encima del Rango:
   Normal o Alerta) según su categoría, para que el semáforo arranque con un
   criterio razonable. Se puede ajustar después en cada indicador.
   - Menor es mejor (Mortalidad, Conversión Alimenticia): debajo Normal, encima Alerta.
   - Mayor es mejor (Producción, Masa de Huevo, Viabilidad, Uniformidad): debajo
     Alerta, encima Normal.
   - Resto (Peso Corporal, Peso del Huevo, Consumos, sin categoría): Alerta de los
     dos lados (valor por defecto del campo).
   Solo se aplica en la primera actualización a esta versión (version < 19.0.1.94.0),
   para no pisar ajustes manuales en rebuilds posteriores.
2) Recalcula Desvío, Posición y Semáforo de todos los Valores Reales Semanales.
"""
import logging

from odoo import api, SUPERUSER_ID
from odoo.tools import parse_version

_logger = logging.getLogger(__name__)

LOWER_IS_BETTER = ('mortality', 'mortality_count', 'feed_conversion', 'feed_egg_mass_conversion')
HIGHER_IS_BETTER = ('egg_production', 'egg_mass', 'viability', 'uniformity')


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {'active_test': False})
    if not version or parse_version(version) < parse_version('19.0.1.94.0'):
        Indicator = env['poultry.indicator']
        lower = Indicator.search([('category', 'in', LOWER_IS_BETTER)])
        lower.write({'alert_below': 'normal', 'alert_above': 'alert'})
        higher = Indicator.search([('category', 'in', HIGHER_IS_BETTER)])
        higher.write({'alert_below': 'alert', 'alert_above': 'normal'})
        _logger.info('Poultry semáforo: %s indicadores "menor es mejor", %s "mayor es mejor".',
                     len(lower), len(higher))

    Weekly = env['poultry.batch.indicator.weekly.value']
    records = Weekly.search([])
    for start in range(0, len(records), 2000):
        chunk = records[start:start + 2000]
        chunk._compute_alert_status()
        chunk.flush_recordset()
    _logger.info('Poultry semáforo: recalculados %s valores semanales.', len(records))
