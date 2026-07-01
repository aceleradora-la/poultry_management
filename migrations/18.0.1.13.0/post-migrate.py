# -*- coding: utf-8 -*-
"""Migra la asignación de galpón de poultry.batch al nuevo modelo
poultry.batch.coop.line (un lote puede repartirse o trasladarse entre
varios galpones, y darse de alta sin galpón asignado).

A diferencia de la migración de estándares de genética, acá SÍ hay datos
reales de producción (lote -> galpón -> cantidad -> fecha) que hay que
preservar: por cada lote con galpón asignado en el esquema anterior, se
crea la línea de asignación vigente equivalente antes de eliminar las
columnas viejas (que además tenían NOT NULL y romperían altas nuevas de
lotes sin galpón si se dejaran).

Se ejecuta en post-migrate (no pre-migrate) porque necesita que el modelo
nuevo poultry.batch.coop.line ya exista (lo crea _auto_init con el código
nuevo), pero lee las columnas viejas de poultry_batch por SQL directo ya
que el modelo Python ya no las declara.
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
        return  # instalación nueva: no hay columnas viejas que migrar

    env = api.Environment(cr, SUPERUSER_ID, {})

    cr.execute("""
        SELECT id, coop_id, bird_count, assignment_date
        FROM poultry_batch
        WHERE coop_id IS NOT NULL
    """)
    rows = cr.fetchall()

    Line = env['poultry.batch.coop.line']
    created = 0
    skipped = 0
    for batch_id, coop_id, bird_count, assignment_date in rows:
        if not bird_count or bird_count <= 0:
            # El modelo nuevo exige cantidad > 0; un lote viejo con 0 aves asignadas
            # no representa una asignación real a migrar.
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
        _logger.warning(
            'Poultry: %s lotes con galpón asignado pero cantidad de aves 0 no se '
            'migraron (revisar manualmente si corresponde crear la asignación).', skipped
        )

    _logger.info(
        'Poultry: se crearon %s asignaciones de lote a galpón a partir de los '
        'campos coop_id/bird_count/assignment_date existentes.', created
    )

    cr.execute("ALTER TABLE poultry_batch DROP COLUMN IF EXISTS coop_id")
    cr.execute("ALTER TABLE poultry_batch DROP COLUMN IF EXISTS assignment_date")
    _logger.info('Poultry: columnas coop_id/assignment_date eliminadas de poultry_batch.')
