# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Inicializa la Fecha de Recolección/Postura de las OFs de Huevo sin
    Clasificar existentes con la fecha de su Cierre de Galpón (todos los
    estados). Hasta ahora los cálculos usaban coop_close_id.date directamente y
    el helper nuevo cae a esa misma fecha si el campo está vacío, así que el
    backfill no cambia ningún valor calculado (no requiere recálculo)."""
    cr.execute("""
        UPDATE mrp_production p
           SET poultry_collection_date = c.date
          FROM poultry_coop_close c
         WHERE p.coop_close_id = c.id
           AND p.poultry_collection_date IS NULL
    """)
    _logger.info(
        'Poultry: Fecha de Recolección/Postura inicializada en %s OFs de cierre.',
        cr.rowcount)
