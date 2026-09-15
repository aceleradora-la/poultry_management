# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import UserError


class PoultryCoopCloseWizard(models.TransientModel):
    _name = 'poultry.coop.close.wizard'
    _description = 'Wizard Cierre de Galpón'

    coop_ids = fields.Many2many(
        'poultry.coop', 'poultry_coop_close_wizard_coop_rel',
        'wizard_id', 'coop_id', string='Galpones',
        domain="[('active', '=', True)]",
        help='Galpones a cerrar para la fecha indicada')
    date = fields.Date(string='Fecha', required=True, default=fields.Date.today)
    close_id = fields.Many2one(
        'poultry.coop.close', string='Cierre a editar',
        help='Si se indica, se edita este cierre en lugar de crear uno nuevo')

    def action_confirm(self):
        if self.close_id:
            return self._action_edit()
        return self._action_create()

    def _action_create(self):
        """Crea cierres en draft para cada galpón seleccionado"""
        if not self.coop_ids:
            raise UserError('Debe seleccionar al menos un galpón.')
        if not self.date:
            raise UserError('Debe indicar la fecha.')

        created = []
        skipped = []
        no_parts = []

        for coop in self.coop_ids:
            existing = self.env['poultry.coop.close'].search([
                ('coop_id', '=', coop.id),
                ('date', '=', self.date),
                ('state', 'in', ('draft', 'done')),
            ], limit=1)
            if existing:
                skipped.append(coop.name)
                continue

            collections = self.env['poultry.egg.collection'].search([
                ('coop_id', '=', coop.id),
                ('date', '=', self.date),
                ('state', '=', 'done'),
                ('coop_close_id', '=', False),
            ])
            if not collections:
                no_parts.append(coop.name)
                continue

            close = self.env['poultry.coop.close'].create({
                'coop_id': coop.id,
                'date': self.date,
                'state': 'draft',
            })
            collections.write({'coop_close_id': close.id})
            created.append(close.id)

        if not created:
            msg_parts = []
            if skipped:
                msg_parts.append('Ya tienen cierre: %s' % ', '.join(skipped))
            if no_parts:
                msg_parts.append(
                    'Sin partes Procesada: %s' % ', '.join(no_parts))
            raise UserError(
                'No se creó ningún cierre.\n\n' + '\n'.join(msg_parts))

        return {
            'name': 'Cierres de Galpón',
            'type': 'ir.actions.act_window',
            'res_model': 'poultry.coop.close',
            'view_mode': 'list,form',
            'domain': [('id', 'in', created)],
            'context': {'create': False},
        }

    def _action_edit(self):
        """Edita un cierre existente en draft"""
        close = self.close_id
        if close.state != 'draft':
            raise UserError('Solo se puede editar un cierre en estado Borrador.')

        if not self.coop_ids or len(self.coop_ids) != 1:
            raise UserError('En modo edición debe seleccionar un solo galpón.')

        coop = self.coop_ids[0]
        date = self.date

        existing = self.env['poultry.coop.close'].search([
            ('coop_id', '=', coop.id),
            ('date', '=', date),
            ('state', 'in', ('draft', 'done')),
            ('id', '!=', close.id),
        ], limit=1)
        if existing:
            raise UserError(
                'Ya existe un cierre para el galpón %s en la fecha %s.'
                % (coop.name, date))

        close.egg_collection_ids.write({'coop_close_id': False})

        collections = self.env['poultry.egg.collection'].search([
            ('coop_id', '=', coop.id),
            ('date', '=', date),
            ('state', '=', 'done'),
            ('coop_close_id', '=', False),
        ])
        if not collections:
            raise UserError(
                'No hay partes en estado Procesada para el galpón %s en la fecha %s.'
                % (coop.name, date))

        close.write({
            'coop_id': coop.id,
            'date': date,
        })
        collections.write({'coop_close_id': close.id})

        return {
            'name': 'Cierre de Galpón',
            'type': 'ir.actions.act_window',
            'res_model': 'poultry.coop.close',
            'res_id': close.id,
            'view_mode': 'form',
        }
