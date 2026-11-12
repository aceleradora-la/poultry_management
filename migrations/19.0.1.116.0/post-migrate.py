# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """App Avícola Campo en tres permisos combinables (pedido del usuario del 2026-11-12):
    quien tenía la app entera asignada a mano (grupo "Operador de Campo", ahora "Avícola
    Campo: acceso a la app") recibe las tres funciones, así nadie pierde nada al actualizar.
    Después la oficina le saca a cada uno lo que no corresponde. Al Gestor Avícola se las da
    su rol, así que no se le asignan a mano."""
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    base = env.ref('poultry_management.poultry_field_user')
    manager = env.ref('poultry_management.poultry_manager')
    functions = (env.ref('poultry_management.poultry_field_weighing')
                 | env.ref('poultry_management.poultry_field_collection')
                 | env.ref('poultry_management.poultry_field_unclassified'))
    users = env['res.users'].with_context(active_test=False).search([('group_ids', 'in', base.ids)])
    users = users.filtered(lambda user: manager not in user.all_group_ids)
    if users:
        users.write({'group_ids': [(4, group.id) for group in functions]})
