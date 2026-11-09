# -*- coding: utf-8 -*-
"""Parte de producción de huevos desde el celular (app Avícola Campo).

El operador carga el Inicial a la mañana y el Bruto al final del día, por calibre y en las
mismas unidades del parte (Cajón, Maple, Huevo), y opcionalmente las aves muertas y el
alimento consumido del galpón; el Cierre de Galpón vuelca estos dos últimos en la OF de
Huevo sin Clasificar. Todo vive en el mismo poultry.egg.collection: la oficina ve el parte
como siempre, ya escrito, y lo procesa igual que hoy.
"""
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

FEED_BAG_KG_PARAM = 'poultry_management.feed_bag_kg'
DEFAULT_FEED_BAG_KG = 25.0
# Partes empezados en el celular y sin completar se siguen ofreciendo estos días.
LATE_DAYS = 7


class PoultryEggCollection(models.Model):
    _inherit = 'poultry.egg.collection'

    initial_date = fields.Datetime(string='Inicial cargado', readonly=True, copy=False,
                                   help='Cuándo se cargó el inicial desde el celular.')
    initial_uid = fields.Many2one('res.users', string='Inicial cargado por', readonly=True, copy=False)
    gross_date = fields.Datetime(string='Bruto cargado', readonly=True, copy=False,
                                 help='Cuándo se cargó el bruto desde el celular.')
    gross_uid = fields.Many2one('res.users', string='Bruto cargado por', readonly=True, copy=False)
    mobile_source = fields.Boolean(string='Cargado desde el celular', compute='_compute_mobile_source',
                                   store=True)
    # Datos del galpón del día: hoy se tipean en la OF de Huevo sin Clasificar que crea el
    # Cierre de Galpón; cargados acá, el cierre los vuelca él mismo en esa OF.
    dead_count = fields.Integer(string='Aves muertas', tracking=True,
                                help='Aves muertas del galpón en el día del parte. El Cierre de '
                                     'Galpón las pasa a la OF de Huevo sin Clasificar.')
    feed_consumed_kg = fields.Float(string='Alimento consumido (kg)', digits=(16, 2), tracking=True,
                                    help='Kilos de alimento consumidos en el galpón en el día. El '
                                         'Cierre de Galpón los pasa al componente de tipo Alimento '
                                         'de la OF de Huevo sin Clasificar.')
    farm_notes = fields.Text(string='Observaciones del galpón')
    farm_data_date = fields.Datetime(string='Datos del galpón cargados', readonly=True, copy=False)
    farm_data_uid = fields.Many2one('res.users', string='Datos del galpón cargados por',
                                    readonly=True, copy=False)

    _POULTRY_MOBILE_FIELDS = {
        'initial': ('initial_box', 'initial_map', 'initial_egg'),
        'final': ('final_box', 'final_map', 'final_egg'),
    }

    @api.depends('initial_date', 'gross_date', 'farm_data_date')
    def _compute_mobile_source(self):
        for record in self:
            record.mobile_source = bool(record.initial_date or record.gross_date or record.farm_data_date)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _poultry_mobile_check_open(self):
        self.ensure_one()
        if self.state in ('done', 'cancel'):
            raise UserError('El parte %s ya fue procesado por la oficina y no se puede cambiar '
                            'desde el celular.' % self.name)

    def _poultry_mobile_lines(self):
        """Líneas en el orden de los calibres (secuencia del valor del atributo)."""
        self.ensure_one()
        return self.line_ids.sorted(
            key=lambda l: (l.attribute_value_id.sequence or 0, l.attribute_value_id.id or 0, l.id))

    def _poultry_mobile_uoms(self):
        """[(nombre, factor)] de las 3 unidades del parte, de la mayor a la menor (Cajón,
        Maple, Huevo), con el mismo criterio que las columnas del parte en Odoo."""
        self.ensure_one()
        Line = self.env['poultry.egg.collection.line']
        variant = self.line_ids[:1].product_variant_id or self.product_tmpl_id.product_variant_ids[:1]
        uoms = Line._get_poultry_uoms(variant)[:3] if variant else self.env['uom.uom']
        result = [(Line._strip_t_suffix((uom.poultry_display_name or uom.name) or ''), uom.factor or 0.0)
                  for uom in uoms]
        while len(result) < 3:
            result.append(('', 0.0))
        return result

    @staticmethod
    def _poultry_mobile_eggs(values, factors):
        return sum((value or 0.0) * factor for value, factor in zip(values, factors))

    def _poultry_mobile_previous(self, states):
        """Último parte anterior del mismo galpón en alguno de esos estados."""
        self.ensure_one()
        return self.search([
            ('coop_id', '=', self.coop_id.id), ('date', '<', self.date), ('state', 'in', states),
        ], order='date desc, id desc', limit=1)

    def _poultry_mobile_stamp(self, value):
        if not value:
            return ''
        return fields.Datetime.context_timestamp(self, value).strftime('%H:%M')

    @api.model
    def _poultry_feed_bag_kg(self):
        raw = self.env['ir.config_parameter'].sudo().get_param(FEED_BAG_KG_PARAM, DEFAULT_FEED_BAG_KG)
        try:
            return float(raw) or DEFAULT_FEED_BAG_KG
        except (TypeError, ValueError):
            return DEFAULT_FEED_BAG_KG

    # ------------------------------------------------------------------
    # Lectura para el celular
    # ------------------------------------------------------------------
    def _poultry_mobile_header(self):
        self.ensure_one()
        lines = self.line_ids
        return {
            'id': self.id,
            'name': self.name,
            'state': self.state,
            'coop_id': self.coop_id.id,
            'coop': self.coop_id.name,
            'date': fields.Date.to_string(self.date),
            'date_label': self.date.strftime('%d/%m') if self.date else '',
            'product': self.product_tmpl_id.name or '',
            'initial_time': self._poultry_mobile_stamp(self.initial_date),
            'gross_time': self._poultry_mobile_stamp(self.gross_date),
            'farm_data_time': self._poultry_mobile_stamp(self.farm_data_date),
            'has_initial': any(l.initial_box or l.initial_map or l.initial_egg for l in lines),
            'has_gross': any(l.final_box or l.final_map or l.final_egg for l in lines),
            'total_eggs': round(self.total_eggs),
            'total_boxes': round(self.total_boxes, 1),
            'average_weight_elaborated': round(self.average_weight_elaborated, 1),
            'dead_count': self.dead_count,
            'feed_consumed_kg': self.feed_consumed_kg,
            'farm_notes': self.farm_notes or '',
        }

    def poultry_mobile_data(self):
        """Todo lo que el celular muestra de un parte: cabecera, unidades, líneas por calibre
        (inicial, bruto, producido), totales, el parte anterior para comparar y los datos
        del galpón."""
        self.ensure_one()
        uoms = self._poultry_mobile_uoms()
        factors = [factor for _, factor in uoms]
        lines = []
        for line in self._poultry_mobile_lines():
            initial = [line.initial_box, line.initial_map, line.initial_egg]
            final = [line.final_box, line.final_map, line.final_egg]
            lines.append({
                'id': line.id,
                'calibre': line.attribute_value_name or line.product_variant_name or '',
                'initial': initial,
                'final': final,
                'initial_eggs': self._poultry_mobile_eggs(initial, factors),
                'final_eggs': self._poultry_mobile_eggs(final, factors),
                'average_weight': line.average_weight,
                'produced': [line.produced_box, line.produced_map, line.produced_egg],
                'produced_eggs': line.total_produced_reference,
            })
        previous = self._poultry_mobile_previous(('completed', 'done'))
        coop = self.coop_id.sudo()
        data = self._poultry_mobile_header()
        data.update({
            'uoms': [{'name': name, 'factor': factor} for name, factor in uoms],
            'lines': lines,
            'total_weight': round(self.total_weight, 1),
            'total_weight_estimated': round(self.total_weight_estimated, 1),
            'previous_total_eggs': round(previous.total_eggs) if previous else 0,
            'previous_date': previous.date.strftime('%d/%m') if previous else '',
            'live_bird_count': coop.live_bird_count,
            'feed_bag_kg': self._poultry_feed_bag_kg(),
            'feed_product': coop.active_bom_id.bom_product_id.display_name or '',
        })
        return data

    @api.model
    def poultry_mobile_coops(self):
        """Galpones activos con el parte de hoy de cada uno (si existe), más los partes
        empezados en el celular otros días y todavía sin completar."""
        today = fields.Date.context_today(self)
        coops = self.env['poultry.coop'].search([('active', '=', True)], order='cage_number, code, id')
        records = self.search([
            ('coop_id', 'in', coops.ids), ('date', '=', today), ('state', '!=', 'cancel'),
        ], order='id')
        by_coop = {}
        for record in records:
            by_coop.setdefault(record.coop_id.id, record)
        items = []
        for coop in coops:
            coop_sudo = coop.sudo()
            batch = coop_sudo._get_active_coop_lines().mapped('batch_id')[:1]
            record = by_coop.get(coop.id)
            items.append({
                'coop_id': coop.id,
                'coop': coop.name,
                'batch': batch.name or '',
                'week': batch._poultry_week_of(today) if batch else 0,
                'live_bird_count': coop_sudo.live_bird_count,
                'record': record._poultry_mobile_header() if record else None,
            })
        late = self.search([
            ('coop_id', 'in', coops.ids),
            ('date', '<', today), ('date', '>=', today - timedelta(days=LATE_DAYS)),
            ('state', 'in', ('draft', 'counted')), ('initial_date', '!=', False),
        ], order='date desc, id')
        return {
            'date': fields.Date.to_string(today),
            'coops': items,
            'late': [record._poultry_mobile_header() for record in late],
        }

    # ------------------------------------------------------------------
    # Abrir / crear el parte del día
    # ------------------------------------------------------------------
    @api.model
    def poultry_mobile_open_coop(self, coop_id):
        """El parte de hoy del galpón; si no existe, se crea (con el producto del último
        parte del galpón y el operador logueado como responsable)."""
        coop = self.env['poultry.coop'].browse(coop_id)
        today = fields.Date.context_today(self)
        record = self.search([
            ('coop_id', '=', coop.id), ('date', '=', today), ('state', '!=', 'cancel'),
        ], order='id', limit=1)
        if not record:
            record = self._poultry_mobile_create(coop, today)
        return record.poultry_mobile_data()

    def _poultry_mobile_create(self, coop, date):
        previous = self.search([('coop_id', '=', coop.id), ('state', '!=', 'cancel')],
                               order='date desc, id desc', limit=1)
        template = previous.product_tmpl_id
        if not template:
            templates = self.env['product.template'].search([
                ('is_egg_production', '=', True), ('active', '=', True)])
            if len(templates) != 1:
                raise UserError(
                    'El galpón %s no tiene partes anteriores y hay %d productos de huevo para '
                    'elegir. La oficina tiene que crear el primer parte de este galpón.'
                    % (coop.name, len(templates)))
            template = templates
        variants = template.product_variant_ids or template.product_variant_id
        # La secuencia del galpón se busca (o crea) con sudo: el operador de campo no puede
        # crear secuencias, pero sí tiene que poder abrir el parte del día.
        sequence = self.sudo()._get_sequence_for_coop(coop.id)
        vals = {
            'name': (sequence and sequence.next_by_id()) or 'NUEVA',
            'coop_id': coop.id,
            'product_tmpl_id': template.id,
            'date': date,
            'operator_id': self.env.user.sudo().employee_id.id or False,
            'line_ids': [(0, 0, {'product_variant_id': variant.id}) for variant in variants],
        }
        record = self.create(vals)
        record.message_post(body='Parte creado desde el celular.')
        return record

    # ------------------------------------------------------------------
    # Cantidades por calibre
    # ------------------------------------------------------------------
    def poultry_mobile_write_values(self, kind, values):
        """Guarda cantidades por calibre sin cambiar el estado. kind: 'initial' (parte en
        Inicio) o 'final' (parte en Bruto). values: [{'line_id', 'qty': [cajón, maple, huevo],
        'average_weight' (solo bruto, opcional)}]. Los vacíos valen 0."""
        self.ensure_one()
        self._poultry_mobile_check_open()
        expected = {'initial': 'draft', 'final': 'counted'}[kind]
        if self.state != expected:
            raise UserError({
                'initial': 'El inicial ya está registrado. Para corregirlo hay que volver el parte a Inicio.',
                'final': 'El bruto se carga con el inicial ya registrado y el parte sin completar.',
            }[kind])
        field_names = self._POULTRY_MOBILE_FIELDS[kind]
        lines = {line.id: line for line in self.line_ids}
        for item in values or []:
            line = lines.get(item.get('line_id'))
            if not line:
                raise UserError('La línea no pertenece a este parte.')
            label = line.attribute_value_name or line.product_variant_name or ''
            qty = list(item.get('qty') or [])[:3]
            qty += [0] * (3 - len(qty))
            clean = []
            for value in qty:
                number = float(value or 0)
                if number < 0:
                    raise UserError('Las cantidades no pueden ser negativas (calibre %s).' % label)
                clean.append(number)
            vals = dict(zip(field_names, clean))
            if kind == 'final' and 'average_weight' in item:
                average = float(item.get('average_weight') or 0)
                if average < 0:
                    raise UserError('El peso medio no puede ser negativo (calibre %s).' % label)
                vals['average_weight'] = average
            line.write(vals)
        return self.poultry_mobile_data()

    def poultry_mobile_save_initial(self, values):
        """Guarda el inicial y pasa el parte a Bruto (inicial registrado)."""
        self.ensure_one()
        self.poultry_mobile_write_values('initial', values)
        if any(l.initial_box or l.initial_map or l.initial_egg for l in self.line_ids):
            self.action_count_initial()
        else:
            # Galpón vacío al empezar el día: el inicial en cero es un dato real.
            self.write({'state': 'counted'})
        self.write({'initial_date': fields.Datetime.now(), 'initial_uid': self.env.uid})
        self.message_post(body='Inicial cargado desde el celular.')
        return self.poultry_mobile_data()

    def poultry_mobile_copy_previous_gross(self):
        """Inicial de hoy = bruto del último parte del galpón (cuando no salió nada)."""
        self.ensure_one()
        self._poultry_mobile_check_open()
        if self.state != 'draft':
            raise UserError('El inicial ya está registrado.')
        previous = self._poultry_mobile_previous(('counted', 'completed', 'done'))
        if not previous or not any(l.final_box or l.final_map or l.final_egg for l in previous.line_ids):
            raise UserError('No hay un parte anterior del galpón con el bruto cargado.')
        by_variant = {line.product_variant_id.id: line for line in previous.line_ids}
        for line in self.line_ids:
            source = by_variant.get(line.product_variant_id.id)
            line.write({
                'initial_box': source.final_box if source else 0.0,
                'initial_map': source.final_map if source else 0.0,
                'initial_egg': source.final_egg if source else 0.0,
            })
        return self.poultry_mobile_data()

    def poultry_mobile_save_gross(self, values):
        """Guarda el bruto (y el peso medio) y deja constancia de cuándo se cargó."""
        self.ensure_one()
        self.poultry_mobile_write_values('final', values)
        self.write({'gross_date': fields.Datetime.now(), 'gross_uid': self.env.uid})
        return self.poultry_mobile_data()

    def poultry_mobile_complete(self):
        """Completa el parte: ningún calibre puede quedar con el bruto por debajo del inicial.
        Procesar sigue siendo de la oficina."""
        self.ensure_one()
        self._poultry_mobile_check_open()
        if self.state == 'draft':
            raise UserError('Primero hay que cargar el inicial.')
        if self.state == 'completed':
            return self.poultry_mobile_data()
        factors = [factor for _, factor in self._poultry_mobile_uoms()]
        below = []
        for line in self._poultry_mobile_lines():
            initial = self._poultry_mobile_eggs([line.initial_box, line.initial_map, line.initial_egg], factors)
            final = self._poultry_mobile_eggs([line.final_box, line.final_map, line.final_egg], factors)
            if final < initial:
                below.append(line.attribute_value_name or line.product_variant_name or '?')
        if below:
            raise UserError('El bruto quedó por debajo del inicial en el calibre %s. Revisá la '
                            'cuenta antes de completar.' % ', '.join(below))
        self.action_complete()
        if not self.gross_date:
            self.write({'gross_date': fields.Datetime.now(), 'gross_uid': self.env.uid})
        self.message_post(body='Parte completado desde el celular.')
        return self.poultry_mobile_data()

    def poultry_mobile_reopen(self):
        """Completada vuelve a Bruto y Bruto vuelve a Inicio, mientras la oficina no lo procesó."""
        self.ensure_one()
        self._poultry_mobile_check_open()
        if self.state == 'draft':
            return self.poultry_mobile_data()
        self.action_set_to_draft()
        labels = dict(self._fields['state']._description_selection(self.env))
        self.message_post(body='Parte reabierto desde el celular para corregir: vuelve a %s.'
                               % labels.get(self.state, self.state))
        return self.poultry_mobile_data()

    # ------------------------------------------------------------------
    # Datos del galpón
    # ------------------------------------------------------------------
    def poultry_mobile_save_farm(self, dead_count, feed_consumed_kg, notes=''):
        self.ensure_one()
        self._poultry_mobile_check_open()
        dead = int(dead_count or 0)
        feed = float(feed_consumed_kg or 0)
        if dead < 0 or feed < 0:
            raise UserError('Las aves muertas y el alimento no pueden ser negativos.')
        live = self.coop_id.sudo().live_bird_count
        if live and dead > live:
            raise UserError('Las aves muertas (%d) superan las aves vivas del galpón (%d).' % (dead, live))
        self.write({
            'dead_count': dead,
            'feed_consumed_kg': feed,
            'farm_notes': (notes or '').strip() or False,
            'farm_data_date': fields.Datetime.now(),
            'farm_data_uid': self.env.uid,
        })
        self.message_post(body='Datos del galpón cargados desde el celular: %d aves muertas, '
                               '%s kg de alimento.' % (dead, ('%.2f' % feed).rstrip('0').rstrip('.')))
        return self.poultry_mobile_data()
