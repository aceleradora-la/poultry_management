# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """El calendario ubica cada pesada del plan en la semana de vida de su fecha, no en la
    del plan (pedido del usuario del 2026-11-12). Los campos del calendario son almacenados:
    se recalculan una vez para las pesadas del plan que ya existen."""
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    Record = env['poultry.weight.record']
    records = Record.with_context(active_test=False).search([('plan_week', '!=', 0)])
    for name in ('calendar_start', 'calendar_stop'):
        env.add_to_compute(Record._fields[name], records)
    records.flush_recordset(['calendar_start', 'calendar_stop'])
