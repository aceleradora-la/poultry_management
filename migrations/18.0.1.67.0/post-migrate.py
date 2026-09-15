# -*- coding: utf-8 -*-
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Recalcula Total Peso Estimado de los Partes de Producción de huevo ya
    existentes: es un campo store=True, así que el cambio de fórmula (extrapolar
    el Peso Medio Elaborado a TODOS los huevos, no solo a los pesados) en
    _compute_final_totals no toca lo ya guardado hasta que el registro se
    recompute. Sin esto, los Partes viejos (y los indicadores de Masa de Huevo
    que se calcularon en su momento con la fórmula anterior) seguirían mostrando
    el valor viejo hasta que alguien editara una línea a mano."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    collections = env['poultry.egg.collection'].search([])
    if collections:
        collections._compute_final_totals()
        cr.commit()
    _logger.info('Poultry: Total Peso Estimado recalculado en %s Partes de Producción.',
                 len(collections))
