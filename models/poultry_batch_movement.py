# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError


class PoultryBatchMovement(models.Model):
    _name = 'poultry.batch.movement'
    _description = 'Movimiento de Aves'
    _order = 'date desc, id desc'

    name = fields.Char(string='Referencia', required=True, copy=False, index=True,
                       default='Nuevo')
    movement_type = fields.Selection([
        ('ingreso', 'Ingreso'),
        ('traslado', 'Traslado'),
    ], string='Tipo de Movimiento', required=True, default='ingreso', index=True)
    date = fields.Date(string='Fecha', required=True, default=fields.Date.today)

    batch_id = fields.Many2one('poultry.batch', string='Lote de Aves', required=True, index=True)
    bird_count = fields.Integer(string='Cantidad de Aves', required=True, default=0)

    origin_coop_id = fields.Many2one('poultry.coop', string='Galpón de Origen',
                                      domain="[('active', '=', True)]",
                                      help='Requerido para Traslado: galpón desde el cual se mueven las aves.')
    dest_coop_id = fields.Many2one('poultry.coop', string='Galpón de Destino', required=True,
                                    domain="[('active', '=', True)]")

    truck_chassis_plate = fields.Char(string='Patente Chasis')
    truck_trailer_plate = fields.Char(string='Patente Acoplado')

    state = fields.Selection([
        ('draft', 'Borrador'),
        ('done', 'Confirmado'),
        ('cancel', 'Cancelado'),
    ], string='Estado', default='draft', required=True, index=True)

    notes = fields.Text(string='Notas')
    active = fields.Boolean(string='Activo', default=True)

    # Trazabilidad de las líneas de asignación afectadas, para poder deshacer al cancelar.
    dest_coop_line_id = fields.Many2one('poultry.batch.coop.line', string='Línea de Destino',
                                         readonly=True, copy=False)
    dest_coop_line_created = fields.Boolean(string='Línea de Destino Creada por este Movimiento',
                                             readonly=True, copy=False)
    origin_coop_line_id = fields.Many2one('poultry.batch.coop.line', string='Línea de Origen (cerrada)',
                                           readonly=True, copy=False)
    origin_replacement_coop_line_id = fields.Many2one(
        'poultry.batch.coop.line', string='Línea de Remanente en Origen',
        readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == 'Nuevo':
                vals['name'] = self.env['ir.sequence'].next_by_code('poultry.batch.movement') or 'Nuevo'
        return super().create(vals_list)

    @api.onchange('movement_type')
    def _onchange_movement_type(self):
        if self.movement_type == 'ingreso':
            self.origin_coop_id = False

    @api.constrains('bird_count')
    def _check_bird_count(self):
        for record in self:
            if record.bird_count <= 0:
                raise ValidationError('La cantidad de aves debe ser mayor a cero.')

    @api.constrains('movement_type', 'origin_coop_id', 'dest_coop_id')
    def _check_type_consistency(self):
        for record in self:
            if record.movement_type == 'traslado':
                if not record.origin_coop_id:
                    raise ValidationError('El Traslado requiere indicar el Galpón de Origen.')
                if record.origin_coop_id == record.dest_coop_id:
                    raise ValidationError('El Galpón de Origen y de Destino no pueden ser el mismo.')
            elif record.movement_type == 'ingreso' and record.origin_coop_id:
                raise ValidationError('El Ingreso no debe tener Galpón de Origen (las aves llegan de afuera).')

    def _find_active_coop_line(self, batch, coop):
        return self.env['poultry.batch.coop.line'].search([
            ('batch_id', '=', batch.id),
            ('coop_id', '=', coop.id),
            ('active', '=', True),
            ('date_to', '=', False),
        ], limit=1)

    def _apply_incoming(self, batch, coop, qty, date):
        """Suma aves a la línea vigente de (lote, galpón) si existe, o crea una nueva.
        Devuelve (línea, fue_creada)."""
        Line = self.env['poultry.batch.coop.line']
        existing = self._find_active_coop_line(batch, coop)
        if existing:
            existing.bird_count += qty
            return existing, False
        new_line = Line.create({
            'batch_id': batch.id,
            'coop_id': coop.id,
            'bird_count': qty,
            'date_from': date,
        })
        return new_line, True

    def action_confirm(self):
        for record in self:
            if record.state != 'draft':
                raise UserError('Solo se puede confirmar un movimiento en Borrador.')

            if record.movement_type == 'traslado':
                origin_line = record._find_active_coop_line(record.batch_id, record.origin_coop_id)
                if not origin_line:
                    raise UserError(
                        f'No hay una asignación vigente del lote {record.batch_id.name} '
                        f'en el galpón de origen {record.origin_coop_id.name}.'
                    )
                live_count = origin_line._get_live_bird_count_on(record.date)
                if record.bird_count > live_count:
                    raise UserError(
                        f'No se pueden trasladar {record.bird_count} aves: solo hay '
                        f'{live_count} aves vivas del lote {record.batch_id.name} '
                        f'en {record.origin_coop_id.name} a la fecha {record.date}.'
                    )

            # Se confirma el estado ANTES de tocar las líneas de asignación: la
            # cantidad de aves del lote (poultry.batch.bird_count) depende del estado
            # de los movimientos, y las validaciones de poultry.batch.coop.line (suma
            # de aves asignadas vs. cantidad de aves del lote) deben ver ya
            # contabilizado este movimiento, o rechazan de más un Ingreso válido. Si
            # algo falla más abajo, toda la transacción (incluido este write) se revierte.
            record.state = 'done'

            if record.movement_type == 'traslado':
                remainder = live_count - record.bird_count
                origin_line.write({'date_to': record.date})
                replacement_line = self.env['poultry.batch.coop.line'].browse()
                if remainder > 0:
                    replacement_line = self.env['poultry.batch.coop.line'].create({
                        'batch_id': record.batch_id.id,
                        'coop_id': record.origin_coop_id.id,
                        'bird_count': remainder,
                        'date_from': record.date,
                    })
                dest_line, dest_created = record._apply_incoming(
                    record.batch_id, record.dest_coop_id, record.bird_count, record.date)
                record.write({
                    'origin_coop_line_id': origin_line.id,
                    'origin_replacement_coop_line_id': replacement_line.id if replacement_line else False,
                    'dest_coop_line_id': dest_line.id,
                    'dest_coop_line_created': dest_created,
                })
            else:
                dest_line, dest_created = record._apply_incoming(
                    record.batch_id, record.dest_coop_id, record.bird_count, record.date)
                record.write({
                    'dest_coop_line_id': dest_line.id,
                    'dest_coop_line_created': dest_created,
                })
        return True

    def action_cancel(self):
        for record in self:
            if record.state != 'done':
                raise UserError('Solo se puede cancelar un movimiento Confirmado.')

            if record.dest_coop_line_id:
                if record.dest_coop_line_created:
                    record.dest_coop_line_id.unlink()
                else:
                    if record.dest_coop_line_id.bird_count < record.bird_count:
                        raise UserError(
                            'No se puede cancelar: la línea de destino ya fue modificada '
                            'por movimientos posteriores.'
                        )
                    record.dest_coop_line_id.bird_count -= record.bird_count

            if record.movement_type == 'traslado':
                if record.origin_replacement_coop_line_id:
                    record.origin_replacement_coop_line_id.unlink()
                if record.origin_coop_line_id:
                    record.origin_coop_line_id.write({'date_to': False})

            record.write({'state': 'cancel'})
        return True

    def action_set_to_draft(self):
        for record in self:
            if record.state != 'cancel':
                raise UserError('Solo se puede volver a Borrador un movimiento Cancelado.')
            record.write({
                'state': 'draft',
                'dest_coop_line_id': False,
                'dest_coop_line_created': False,
                'origin_coop_line_id': False,
                'origin_replacement_coop_line_id': False,
            })
        return True

    @api.ondelete(at_uninstall=False)
    def _unlink_only_draft(self):
        for record in self:
            if record.state == 'done':
                raise UserError('No se puede eliminar un movimiento Confirmado. Cancélelo primero.')
