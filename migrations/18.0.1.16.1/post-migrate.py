# -*- coding: utf-8 -*-
"""Recalcula poultry.batch.bird_count para todos los lotes existentes.

La versión anterior (18.0.1.16.0) tenía un orden de operaciones incorrecto en
poultry.batch.movement.action_confirm(): las líneas de asignación se
actualizaban antes de marcar el movimiento como Confirmado, por lo que
bird_count (que depende del estado de los movimientos) podía quedar
desactualizado para lotes que ya tenían movimientos confirmados antes de este
arreglo. Se fuerza el recálculo para que autocorrija cualquier valor
guardado incorrecto sin intervención manual.
"""


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    batches = env['poultry.batch'].search([])
    if not batches:
        return
    batches._compute_bird_count()
    batches.flush_recordset(['bird_count'])
