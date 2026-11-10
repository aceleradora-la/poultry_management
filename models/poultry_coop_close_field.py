# -*- coding: utf-8 -*-
"""Mortandad y consumos de la OF de Huevo sin Clasificar desde el celular.

La OF que crea el Cierre de Galpón se marca Hecha al otro día: hasta entonces el operador
carga desde la app las aves muertas del galpón y la cantidad consumida de CADA componente de
la OF (alimento, agua, lo que tenga la lista), que es lo que hoy tipea la oficina en la OF.
Es el ÚNICO lugar de carga: el parte de huevos no lleva mortandad ni consumos, así que un día
sin OF todavía no tiene dónde cargarse (se espera a que la oficina confirme el cierre).
La API vive en el cierre (dato avícola que el Operador de Campo puede leer) y toca la OF con
sudo tras verificar el rol: así no hace falta abrirle Manufactura al operador.
"""
from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

PENDING_STATES = ('draft', 'confirmed', 'progress', 'to_close')
FEED_BAG_KG_PARAM = 'poultry_management.feed_bag_kg'
DEFAULT_FEED_BAG_KG = 25.0


class PoultryCoopClose(models.Model):
    _inherit = 'poultry.coop.close'

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @api.model
    def _poultry_mobile_check_user(self):
        user = self.env.user
        if self.env.su:
            return
        if not (user.has_group('poultry_management.poultry_field_user')
                or user.has_group('poultry_management.poultry_user')):
            raise AccessError('Solo los operadores de campo y los usuarios avícolas cargan la '
                              'mortandad y los consumos desde el celular.')

    def _poultry_mobile_order(self):
        """La OF de Huevo sin Clasificar del cierre, con sudo (sus campos de mortandad tienen
        groups= y el operador no tiene Manufactura)."""
        self.ensure_one()
        order = self.sudo().unclassified_production_id
        if not order:
            raise UserError('El cierre %s todavía no tiene OF de Huevo sin Clasificar.' % self.name)
        return order

    def _poultry_mobile_check_open(self, order):
        self.ensure_one()
        if order.state not in PENDING_STATES:
            labels = dict(order._fields['state']._description_selection(self.env))
            raise UserError('La OF %s ya está %s: la mortandad y los consumos los corrige la '
                            'oficina.' % (order.name, labels.get(order.state, order.state)))

    @staticmethod
    def _poultry_mobile_moves(order):
        """Componentes vivos de la OF: primero el alimento, después el agua, después el resto."""
        rank = {'feed': 0, 'water': 1}
        return order.move_raw_ids.filtered(lambda m: m.state != 'cancel').sorted(
            key=lambda m: (rank.get(m._poultry_consumption_type(), 2), m.id))

    @api.model
    def _poultry_feed_bag_kg(self):
        """Kilos de una bolsa de alimento, para cargar el consumo en bolsas."""
        raw = self.env['ir.config_parameter'].sudo().get_param(FEED_BAG_KG_PARAM, DEFAULT_FEED_BAG_KG)
        try:
            return float(raw) or DEFAULT_FEED_BAG_KG
        except (TypeError, ValueError):
            return DEFAULT_FEED_BAG_KG

    # ------------------------------------------------------------------
    # Lectura
    # ------------------------------------------------------------------
    def _poultry_mobile_header(self):
        self.ensure_one()
        order = self._poultry_mobile_order()
        target = order._poultry_target_date()
        moves = self._poultry_mobile_moves(order)
        loaded = moves.filtered('picked')
        return {
            'id': self.id,
            'name': self.name,
            'order_name': order.name,
            'order_state': order.state,
            'coop_id': self.coop_id.id,
            'coop': self.coop_id.name,
            'date': fields.Date.to_string(target),
            'date_label': target.strftime('%d/%m'),
            'eggs': order.product_qty,
            'eggs_uom': order.product_uom_id.name,
            'dead_count': order.poultry_dead_count_total,
            'line_count': len(moves),
            # Odoo precarga en cada componente la cantidad de la lista al crear la OF: un
            # consumo cuenta como cargado recién cuando alguien lo confirmó (picked).
            'loaded_count': len(loaded),
            # Cargada = todos los consumos confirmados (Guardar los confirma a todos). Las aves
            # muertas solas no alcanzan: un día sin bajas deja 0 y no por eso falta cargarlo.
            'complete': len(loaded) == len(moves) if moves else order.poultry_dead_count_total > 0,
        }

    def poultry_mobile_data(self):
        """Aves muertas y componentes de la OF del cierre, para la pantalla del celular."""
        self._poultry_mobile_check_user()
        self.ensure_one()
        order = self._poultry_mobile_order()
        target = order._poultry_target_date()
        _batches, _by_batch, total_birds = order._poultry_get_coop_batches_and_birds(target)
        kg = self.env.ref('uom.product_uom_kgm', raise_if_not_found=False)
        data = self._poultry_mobile_header()
        data.update({
            'live_bird_count': total_birds,
            'feed_bag_kg': self._poultry_feed_bag_kg(),
            'lines': [{
                'id': move.id,
                'product': move.product_id.display_name,
                'uom': move.product_uom.name,
                'planned': move.product_uom_qty,
                'quantity': move.quantity,
                'picked': move.picked,
                'type': move._poultry_consumption_type() or '',
                'is_kg': bool(kg) and move.product_uom == kg,
            } for move in self._poultry_mobile_moves(order)],
        })
        return data

    @api.model
    def poultry_mobile_pending(self):
        """Las OF de Huevo sin Clasificar todavía sin hacer, la más reciente primero."""
        self._poultry_mobile_check_user()
        closes = self.sudo().search([
            ('state', '=', 'done'),
            ('unclassified_production_id', '!=', False),
            ('unclassified_production_id.state', 'in', PENDING_STATES),
        ])
        closes = closes.sorted(key=lambda c: (c._poultry_mobile_order()._poultry_target_date(), c.id),
                               reverse=True)
        return {'orders': [close._poultry_mobile_header() for close in closes]}

    # ------------------------------------------------------------------
    # Guardado
    # ------------------------------------------------------------------
    def poultry_mobile_save(self, dead_count, lines, note=''):
        """Guarda en la OF las aves muertas y la cantidad consumida de cada componente.
        lines: [{'move_id', 'quantity'}] en la unidad del componente. Marcar la OF como
        hecha sigue siendo de la oficina."""
        self._poultry_mobile_check_user()
        self.ensure_one()
        order = self._poultry_mobile_order()
        self._poultry_mobile_check_open(order)
        dead = int(dead_count or 0)
        if dead < 0:
            raise UserError('Las aves muertas no pueden ser negativas.')
        target = order._poultry_target_date()
        _batches, _by_batch, total_birds = order._poultry_get_coop_batches_and_birds(target)
        if total_birds and dead > total_birds:
            raise UserError('Las aves muertas (%d) superan las aves vivas del galpón (%d) al %s.'
                            % (dead, total_birds, target.strftime('%d/%m/%Y')))
        moves = {move.id: move for move in self._poultry_mobile_moves(order)}
        for item in lines or []:
            move = moves.get(item.get('move_id'))
            if not move:
                raise UserError('El componente no pertenece a esta OF.')
            quantity = float(item.get('quantity') or 0)
            if quantity < 0:
                raise UserError('El consumo de %s no puede ser negativo.' % move.product_id.display_name)
            # Todas las líneas enviadas quedan confirmadas (picked), también las que el
            # operador dejó como las propuso la lista o en cero: es lo que consumió el día.
            if quantity != move.quantity or not move.picked:
                move.write({'quantity': quantity, 'picked': True})
        if dead != order.poultry_dead_count_total:
            order.write({'poultry_dead_count_total': dead})
        consumed = ', '.join(
            '%s %g %s' % (move.product_id.display_name, move.quantity, move.product_uom.name)
            for move in moves.values())
        body = 'Cargado desde el celular: %d aves muertas. Consumos: %s.' % (dead, consumed or 'ninguno')
        if (note or '').strip():
            body += ' Observaciones: %s' % note.strip()
        order.message_post(body=body, author_id=self.env.user.partner_id.id)
        return self.poultry_mobile_data()
