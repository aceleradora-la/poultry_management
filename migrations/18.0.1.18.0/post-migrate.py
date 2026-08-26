# -*- coding: utf-8 -*-
"""Migra production_start_date/housed_bird_count del lote (campos sueltos, recién
agregados) al nuevo modelo poultry.batch.period.change: el cambio de período ahora
es un registro propio (con su galpón), independiente del traslado físico entre
galpones, y sirve de auditoría de "cuándo entró en producción" cada lote.

Por cada lote con housed_bird_count ya confirmado bajo el esquema anterior, se
crea el Cambio de Período equivalente, infiriendo el galpón de la asignación a
galpón vigente en esa fecha (si hay más de una, se usa la primera por id: el
esquema anterior no distinguía cuál se había usado). Se preserva el
housed_bird_count ya calculado, sin recalcularlo, para no alterar valores que ya
pueden estar siendo usados por indicadores reales existentes.
"""

import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'poultry_batch' AND column_name = 'housed_bird_count'
    """)
    if not cr.fetchone():
        return

    env = api.Environment(cr, SUPERUSER_ID, {})

    cr.execute("""
        SELECT id, production_start_date, housed_bird_count
        FROM poultry_batch
        WHERE housed_bird_count IS NOT NULL AND housed_bird_count > 0
    """)
    rows = cr.fetchall()

    PeriodChange = env['poultry.batch.period.change']
    CoopLine = env['poultry.batch.coop.line']
    created = 0
    skipped = 0
    for batch_id, production_start_date, housed_bird_count in rows:
        if not production_start_date:
            skipped += 1
            continue
        line = CoopLine.search([
            ('batch_id', '=', batch_id),
            ('active', '=', True),
            ('date_from', '<=', production_start_date),
            '|', ('date_to', '=', False), ('date_to', '>=', production_start_date),
        ], order='id asc', limit=1)
        if not line:
            skipped += 1
            continue
        PeriodChange.create({
            'batch_id': batch_id,
            'coop_id': line.coop_id.id,
            'date': production_start_date,
            'period': 'produccion',
            'housed_bird_count': housed_bird_count,
            'notes': 'Migrado automáticamente desde el esquema anterior '
                     '(poultry.batch.production_start_date/housed_bird_count).',
        })
        created += 1

    if skipped:
        _logger.warning(
            'Poultry: %s lotes con Aves Alojadas confirmadas no se pudieron migrar a '
            'Cambio de Período (sin galpón identificable en esa fecha); revisar manualmente.',
            skipped
        )
    _logger.info('Poultry: se crearon %s Cambios de Período a partir del esquema anterior.', created)

    cr.execute("ALTER TABLE poultry_batch DROP COLUMN IF EXISTS production_start_date")
    cr.execute("ALTER TABLE poultry_batch DROP COLUMN IF EXISTS housed_bird_count")
