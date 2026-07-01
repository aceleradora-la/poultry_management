# -*- coding: utf-8 -*-
"""bird_count del Lote pasa a calcularse como la suma de los Movimientos de Aves
de tipo Ingreso confirmados (en vez de ser un campo cargado a mano).

Los lotes que ya tenían una Asignación a Galpón (poultry.batch.coop.line) de antes
de que existiera poultry.batch.movement (creados por la migración 18.0.1.13.0, o
cargados a mano en la lista editable del lote/galpón) no tienen ningún movimiento
que respalde esa cantidad. Sin un Ingreso confirmado, bird_count recalcularía a 0
para esos lotes aunque tengan aves asignadas reales.

Por cada lote que todavía no tiene NINGÚN movimiento registrado, se crea un
Ingreso confirmado "sintético" por cada una de sus líneas de asignación, para que
la suma vuelva a dar el total correcto. Los lotes que ya usaron el flujo de
Movimiento de Aves no se tocan (ya tienen sus propios movimientos reales).

Limitación conocida: si un lote sin movimientos tiene más de una línea de
asignación porque alguien las cargó a mano simulando un traslado (antes de que
existiera esta funcionalidad), este backfill las contará todas por separado y
podría sobreestimar el total. Dado que recién se introdujo el modelo de
Movimiento, se asume que este caso no se dio en la práctica; revisar manualmente
si algún lote muestra una Cantidad de Aves inesperada después de actualizar.
"""

import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    Batch = env['poultry.batch']
    Movement = env['poultry.batch.movement']

    batches = Batch.search([('movement_ids', '=', False), ('coop_line_ids', '!=', False)])
    created = 0
    for batch in batches:
        for line in batch.coop_line_ids:
            if not line.bird_count or line.bird_count <= 0:
                continue
            movement = Movement.create({
                'movement_type': 'ingreso',
                'date': line.date_from,
                'batch_id': batch.id,
                'dest_coop_id': line.coop_id.id,
                'bird_count': line.bird_count,
                'state': 'done',
                'dest_coop_line_id': line.id,
                'dest_coop_line_created': True,
                'notes': 'Movimiento generado automáticamente al migrar datos previos '
                         'a la existencia de Movimiento de Aves.',
            })
            created += 1

    _logger.info(
        'Poultry: se crearon %s Ingresos retroactivos para lotes migrados sin '
        'movimientos previos, de forma que Cantidad de Aves recalcule correctamente.',
        created
    )
