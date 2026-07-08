# -*- coding: utf-8 -*-
"""Siembra un Movimiento de Aves (Ingreso) sintético por cada lote existente, antes
de que poultry.batch.bird_count pase de columna fija a computado (suma de Ingresos
confirmados).

Sin este paso, todo lote existente quedaría con Cantidad de Aves = 0 apenas algo
dispare el recálculo del campo (no hay Ingresos que sumar). El movimiento sintético
usa como cantidad el valor de bird_count vigente antes de esta migración -todavía
disponible acá porque Odoo no fuerza el recálculo de un campo que pasa de columna
fija a store=True computado si la columna ya existía con datos-, así el valor
recalculado coincide exactamente con el histórico.
"""

import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Batch = env['poultry.batch']
    Movement = env['poultry.batch.movement']
    CoopLine = env['poultry.batch.coop.line']

    batches = Batch.search([])
    created, skipped, mismatches = 0, 0, 0
    for batch in batches:
        if Movement.search_count([('batch_id', '=', batch.id)]):
            continue  # idempotencia: ya migrado o ya tiene movimientos propios

        previous_bird_count = batch.bird_count
        if not previous_bird_count or previous_bird_count <= 0:
            skipped += 1
            continue

        open_line = CoopLine.search([
            ('batch_id', '=', batch.id), ('date_to', '=', False), ('active', '=', True),
        ], limit=1, order='date_from asc')
        if not open_line:
            _logger.warning('Poultry: lote %s sin asignación de galpón vigente; no se '
                            'crea Ingreso sintético.', batch.display_name)
            skipped += 1
            continue

        Movement.create({
            'movement_type': 'ingreso',
            'date': batch.birth_date,
            'batch_id': batch.id,
            'bird_count': previous_bird_count,
            'dest_coop_id': open_line.coop_id.id,
            'state': 'done',
            'dest_coop_line_id': open_line.id,
            'dest_coop_line_created': False,
            'notes': 'Ingreso sintético generado por migración 19.0 (preserva la '
                     'Cantidad de Aves histórica al pasar bird_count a computado).',
        })
        created += 1

    # bird_count ya es un campo computado a esta altura (el modelo se cargó antes de
    # este post-migrate); se fuerza el recálculo y se verifica contra el valor sembrado.
    batches.invalidate_recordset(['bird_count'])
    for batch in batches:
        movement = Movement.search([('batch_id', '=', batch.id)], limit=1)
        if movement and batch.bird_count != movement.bird_count:
            mismatches += 1
            _logger.warning('Poultry: lote %s quedó con bird_count=%s tras recalcular, '
                            'distinto al Ingreso sintético (%s). Revisar manualmente.',
                            batch.display_name, batch.bird_count, movement.bird_count)

    _logger.info('Poultry: %s movimientos de Ingreso sintéticos creados, %s lotes '
                 'omitidos (sin aves o sin galpón vigente), %s discrepancias tras '
                 'recalcular bird_count.', created, skipped, mismatches)
