# -*- coding: utf-8 -*-
"""Migra poultry.batch del modelo plano (coop_id + assignment_date) al historial
poultry.batch.coop.line.

Crea una línea de asignación vigente (date_to vacío) por cada lote que tenía un
galpón asignado, preservando coop_id/bird_count/assignment_date. Corre en
post-migrate (no pre-migrate) porque necesita que poultry.batch.coop.line ya
esté registrado como modelo real (usa el ORM, no SQL crudo, para que se
apliquen sus validaciones/computados normalmente).
"""

import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'poultry_batch' AND column_name = 'coop_id'
        )
    """)
    if not cr.fetchone()[0]:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    cr.execute("""
        SELECT id, coop_id, bird_count, assignment_date
        FROM poultry_batch
        WHERE coop_id IS NOT NULL
    """)
    rows = cr.fetchall()

    Line = env['poultry.batch.coop.line']
    created, skipped = 0, 0
    for batch_id, coop_id, bird_count, assignment_date in rows:
        if not bird_count or bird_count <= 0:
            skipped += 1
            continue
        Line.create({
            'batch_id': batch_id,
            'coop_id': coop_id,
            'bird_count': bird_count,
            'date_from': assignment_date,
        })
        created += 1

    if skipped:
        _logger.warning('Poultry: %s lotes con galpón asignado pero bird_count<=0 no '
                        'migrados a poultry.batch.coop.line (revisar manualmente).', skipped)
    _logger.info('Poultry: %s asignaciones batch->coop.line creadas desde columnas '
                 'anteriores de poultry.batch.', created)

    cr.execute("ALTER TABLE poultry_batch DROP COLUMN IF EXISTS coop_id")
    cr.execute("ALTER TABLE poultry_batch DROP COLUMN IF EXISTS assignment_date")
    _logger.info('Poultry: columnas coop_id/assignment_date eliminadas de poultry_batch '
                 '(reemplazadas por poultry.batch.coop.line).')
