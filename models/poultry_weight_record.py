# -*- coding: utf-8 -*-

from datetime import timedelta

from odoo import models, fields, api
from odoo.exceptions import ValidationError


class PoultryWeightRecord(models.Model):
    _name = 'poultry.weight.record'
    _description = 'Parte de Registro de Peso de Aves'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, coop_id'

    # Avisos por jaula (solapa Por Jaula y tarjetas del celular). No interrumpen la carga
    # de pesos: el operador los ve en la tarjeta al cerrar la jaula.
    CAGE_CV_ALERT_PCT = 10.0
    CAGE_DEVIATION_ALERT_PCT = 5.0

    name = fields.Char(string='Referencia', required=True, default='Nuevo',
                       copy=False, index=True)
    coop_id = fields.Many2one('poultry.coop', string='Galpón', required=True,
                              domain="[('active', '=', True)]", index=True, tracking=True)
    batch_id = fields.Many2one('poultry.batch', string='Lote de Aves', required=True,
                               domain="[('current_coop_ids', '=', coop_id), ('active', '=', True)]",
                               index=True, tracking=True)
    date = fields.Date(string='Fecha', required=True, default=fields.Date.today,
                       index=True, tracking=True)
    operator_id = fields.Many2one('hr.employee', string='Responsable',
                                  domain="[('active', '=', True)]",
                                  help='Quien hace la pesada. El usuario que la registra '
                                       'queda en el historial del parte.')
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('in_progress', 'En Curso'),
        ('registered', 'Registrado'),
        ('done', 'Confirmado'),
        ('cancel', 'Cancelado'),
    ], string='Estado', default='draft', required=True, tracking=True, copy=False,
        help='Borrador: la oficina prepara el parte (líneas, planilla). En Curso: se envió '
             'a pesar y aparece en la app del celular. Registrado: la pesada terminó y '
             'queda a verificar. Confirmado: publica los indicadores.')
    line_ids = fields.One2many('poultry.weight.record.line', 'record_id', string='Pesos')
    cage_summary_ids = fields.One2many('poultry.weight.record.cage', 'record_id',
                                       string='Por Jaula')
    closed_cage_ids = fields.Many2many(
        'poultry.cage', 'poultry_weight_record_closed_cage_rel', 'record_id', 'cage_id',
        string='Jaulas Cerradas', copy=False,
        help='Jaulas que el operador dio por terminadas desde el celular.')
    birds_per_cage = fields.Integer(string='Aves por Jaula', copy=False,
                                    help='Líneas que generó el asistente por cada jaula.')
    registered_date = fields.Datetime(string='Registrado el', readonly=True, copy=False)
    registered_uid = fields.Many2one('res.users', string='Registrado por', readonly=True,
                                     copy=False)
    notes = fields.Text(string='Notas')

    batch_age_weeks = fields.Integer(string='Edad del Lote (semanas)',
                                     compute='_compute_batch_age', store=True)

    # Banda de uniformidad: % de desvío respecto del promedio dentro del cual un ave
    # se considera "uniforme". El estándar de la industria es ±10%.
    uniformity_band_pct = fields.Float(string='Banda de Uniformidad (±%)', default=10.0)

    # Los totales cuentan solo las líneas con peso: las que quedan en cero son aves que
    # todavía no se pesaron (o que no estaban) y no deben bajar el promedio.
    planned_bird_count = fields.Integer(string='Aves Previstas', compute='_compute_totals',
                                        store=True)
    cage_count = fields.Integer(string='Jaulas', compute='_compute_totals', store=True)
    weighed_cage_count = fields.Integer(string='Jaulas Pesadas', compute='_compute_totals',
                                        store=True)
    bird_count = fields.Integer(string='Aves Pesadas', compute='_compute_totals', store=True)
    progress_pct = fields.Float(string='Avance (%)', compute='_compute_totals', store=True,
                                aggregator='avg', help='Aves pesadas sobre las previstas.')
    total_weight_g = fields.Float(string='Peso Total (g)', compute='_compute_totals',
                                  store=True, digits=(16, 1))
    average_weight_g = fields.Float(string='Peso Promedio (g)', compute='_compute_totals',
                                    store=True, digits=(16, 1))
    uniformity_pct = fields.Float(string='Uniformidad (%)', compute='_compute_totals',
                                  store=True, digits=(16, 2))
    cv_pct = fields.Float(string='Coef. de Variación (%)', compute='_compute_totals',
                          store=True, digits=(16, 2))
    # Compute propio (no _compute_totals): son los únicos NO almacenados del
    # grupo, y Odoo exige métodos separados para almacenados y no almacenados
    # (si comparten método, leer min/max dispararía recomputar los almacenados).
    min_weight_g = fields.Float(string='Peso Mínimo (g)', compute='_compute_min_max',
                                digits=(16, 1))
    max_weight_g = fields.Float(string='Peso Máximo (g)', compute='_compute_min_max',
                                digits=(16, 1))

    @api.depends('batch_id', 'batch_id.birth_date', 'date')
    def _compute_batch_age(self):
        """Calcula la edad del lote en semanas al momento de la pesada"""
        for record in self:
            if record.batch_id and record.batch_id.birth_date and record.date:
                record.batch_age_weeks = record.batch_id._poultry_week_of(record.date)
            else:
                record.batch_age_weeks = 0

    @api.depends('line_ids.weight_g', 'line_ids.cage_id', 'uniformity_band_pct')
    def _compute_totals(self):
        """Totales del parte: promedio, uniformidad (% de aves dentro de la banda
        respecto del promedio) y coeficiente de variación (desvío estándar
        poblacional / promedio)."""
        for record in self:
            weighed = record._poultry_weighed_lines()
            weights = weighed.mapped('weight_g')
            count = len(weights)
            planned = len(record.line_ids)
            record.planned_bird_count = planned
            record.cage_count = len(record.line_ids.cage_id)
            record.weighed_cage_count = len(weighed.cage_id)
            record.bird_count = count
            record.progress_pct = count / planned * 100.0 if planned else 0.0
            if not count:
                record.total_weight_g = 0.0
                record.average_weight_g = 0.0
                record.uniformity_pct = 0.0
                record.cv_pct = 0.0
                continue
            total = sum(weights)
            avg = total / count
            record.total_weight_g = total
            record.average_weight_g = avg
            if avg:
                band = avg * (record.uniformity_band_pct or 10.0) / 100.0
                in_band = sum(1 for w in weights if abs(w - avg) <= band)
                record.uniformity_pct = in_band / count * 100.0
                variance = sum((w - avg) ** 2 for w in weights) / count
                record.cv_pct = (variance ** 0.5) / avg * 100.0
            else:
                record.uniformity_pct = 0.0
                record.cv_pct = 0.0

    @api.depends('line_ids.weight_g')
    def _compute_min_max(self):
        """Peso mínimo y máximo del parte (no almacenados)."""
        for record in self:
            weights = record._poultry_weighed_lines().mapped('weight_g')
            record.min_weight_g = min(weights) if weights else 0.0
            record.max_weight_g = max(weights) if weights else 0.0

    def _poultry_weighed_lines(self):
        return self.line_ids.filtered(lambda line: line.weight_g > 0)

    def _poultry_sorted_lines(self):
        """Líneas en el orden de la planilla: jaula por ubicación física (fila, lado,
        claro, piso, jaula) y dentro de la jaula por número de ave."""
        self.ensure_one()
        return self.line_ids.sorted(
            key=lambda line: (line.cage_id._poultry_sort_key(), line.bird_no, line.id))

    def _poultry_pending_cages(self):
        """Jaulas con líneas pero sin ningún peso: las que faltan pesar."""
        self.ensure_one()
        pending = self.line_ids.cage_id - self._poultry_weighed_lines().cage_id
        return pending.sorted(key=lambda cage: cage._poultry_sort_key())

    def _poultry_cage_summaries(self):
        """Resumen por jaula leído de la vista SQL, con los pesos recién escritos."""
        self.ensure_one()
        Summary = self.env['poultry.weight.record.cage']
        Summary._poultry_flush_sources()
        # Los ids de la vista son estables (la primera línea de cada jaula): hay que
        # soltar lo cacheado para releer los pesos recién escritos.
        Summary.invalidate_model()
        return Summary.search([('record_id', '=', self.id)])

    # ------------------------------------------------------------------
    # Numeración: GALPÓN-AÑO-correlativo, el correlativo arranca en 1 cada año
    # ------------------------------------------------------------------
    @api.model
    def _poultry_sequence_for(self, coop):
        """Secuencia propia de cada galpón (G1-2026-001). Se crea al primer parte; el
        rango anual hace que el correlativo vuelva a 1 cada año."""
        code = 'poultry.weight.record.coop.%d' % coop.id
        prefix = '%s-%%(year)s-' % (coop.code or 'GAL')
        Sequence = self.env['ir.sequence'].sudo()
        sequence = Sequence.search([('code', '=', code), ('company_id', '=', False)], limit=1)
        if not sequence:
            sequence = Sequence.create({
                'name': 'Partes de Peso %s' % (coop.code or coop.name),
                'code': code,
                'prefix': prefix,
                'padding': 3,
                'use_date_range': True,
                'company_id': False,
            })
        elif sequence.prefix != prefix:
            sequence.prefix = prefix
        return sequence

    @api.model
    def _poultry_next_name(self, coop, date):
        return self._poultry_sequence_for(coop).next_by_id(sequence_date=date)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == 'Nuevo':
                coop = self.env['poultry.coop'].browse(vals.get('coop_id'))
                date = fields.Date.to_date(vals.get('date')) or fields.Date.context_today(self)
                vals['name'] = self._poultry_next_name(coop, date) if coop else 'NUEVO'
        return super().create(vals_list)

    def write(self, vals):
        before = {record.id: (record.coop_id, record.date.year) for record in self}
        res = super().write(vals)
        if 'coop_id' in vals or 'date' in vals:
            # El número lleva el galpón y el año: si cambian en Borrador, se renumera.
            for record in self.filtered(lambda r: r.state == 'draft'):
                if before[record.id] != (record.coop_id, record.date.year):
                    record.name = self._poultry_next_name(record.coop_id, record.date)
        return res

    @api.onchange('coop_id')
    def _onchange_coop_id(self):
        """Al cambiar el galpón, resetear el lote (y auto-seleccionarlo si hay uno solo)."""
        self.batch_id = False
        if self.coop_id:
            batches = self.env['poultry.batch'].search([
                ('current_coop_ids', '=', self.coop_id.id),
                ('active', '=', True),
            ])
            if len(batches) == 1:
                self.batch_id = batches

    def _get_coop_line(self):
        """Asignación (poultry.batch.coop.line) del lote en el galpón vigente a la fecha
        de la pesada. Misma lógica que poultry.mortality._get_coop_line."""
        self.ensure_one()
        if not (self.batch_id and self.coop_id and self.date):
            return self.env['poultry.batch.coop.line']
        return self.env['poultry.batch.coop.line'].search([
            ('batch_id', '=', self.batch_id.id),
            ('coop_id', '=', self.coop_id.id),
            ('active', '=', True),
            ('date_from', '<=', self.date),
            '|', ('date_to', '=', False), ('date_to', '>=', self.date),
        ], limit=1)

    def _poultry_previous_record(self):
        """Último parte registrado o confirmado del mismo galpón, anterior a este."""
        self.ensure_one()
        return self.search([
            ('coop_id', '=', self.coop_id.id),
            ('state', 'in', ('registered', 'done')),
            ('id', '!=', self.id),
            ('date', '<=', self.date),
        ], order='date desc, id desc', limit=1)

    def _poultry_weighed_counts(self):
        """Aves con peso por jaula: {cage: cantidad}. Es la estructura que se repite en
        la pesada siguiente."""
        self.ensure_one()
        counts = {}
        for line in self._poultry_weighed_lines():
            counts[line.cage_id] = counts.get(line.cage_id, 0) + 1
        return counts

    def _poultry_add_cage_lines(self, cages, birds_per_cage, counts=None):
        """Agrega líneas por jaula, numeradas, en el orden físico y a continuación de
        las que ya hay: counts[cage] líneas si se indica, si no birds_per_cage."""
        self.ensure_one()
        counts = counts or {}
        next_sequence = max(self.line_ids.mapped('sequence'), default=0) + 1
        vals_list = []
        for cage in cages.sorted(key=lambda c: c._poultry_sort_key()):
            for bird_no in range(1, counts.get(cage, birds_per_cage) + 1):
                vals_list.append({
                    'record_id': self.id,
                    'cage_id': cage.id,
                    'bird_no': bird_no,
                    'sequence': next_sequence,
                    'weight_g': 0.0,
                })
                next_sequence += 1
        return self.env['poultry.weight.record.line'].create(vals_list)

    def action_open_lines_wizard(self):
        self.ensure_one()
        return {
            'name': 'Generar Líneas de Pesaje',
            'type': 'ir.actions.act_window',
            'res_model': 'poultry.weight.lines.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_record_id': self.id},
        }

    def action_send(self):
        """Manda la pesada al galpón: pasa a En Curso y aparece en la app Avícola Campo."""
        for record in self:
            if record.state != 'draft':
                raise ValidationError('Solo se puede enviar a pesar un parte en Borrador.')
            if not record.line_ids:
                raise ValidationError('Generá las líneas antes de enviar a pesar.')
        self.write({'state': 'in_progress'})

    def action_register(self, force=False):
        """Termina la pesada: el parte queda Registrado, a verificar por la oficina.
        Si quedan jaulas sin pesar, primero avisa (force=True registra igual)."""
        self.ensure_one()
        if self.state not in ('draft', 'in_progress'):
            raise ValidationError('Solo se puede registrar un parte en Borrador o En Curso.')
        if not self._poultry_weighed_lines():
            raise ValidationError('El parte no tiene pesos cargados.')
        if self._poultry_pending_cages() and not force:
            return {
                'name': 'Jaulas sin pesar',
                'type': 'ir.actions.act_window',
                'res_model': 'poultry.weight.register.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {'default_record_id': self.id},
            }
        self.write({
            'state': 'registered',
            'registered_date': fields.Datetime.now(),
            'registered_uid': self.env.uid,
        })
        if self.env.context.get('poultry_mobile'):
            self.message_post(body='Pesada registrada desde el celular.')
        return True

    def action_reopen(self):
        """Vuelve un parte En Curso o Registrado a Borrador: se puede corregir, enviar a
        pesar y registrar de nuevo."""
        for record in self:
            if record.state not in ('in_progress', 'registered'):
                raise ValidationError(
                    'Solo se puede volver a Borrador un parte En Curso o Registrado.')
        self.write({'state': 'draft', 'registered_date': False, 'registered_uid': False})

    def action_done(self):
        """Confirma el parte y publica los indicadores Peso Corporal y Uniformidad."""
        for record in self:
            if record.state not in ('draft', 'in_progress', 'registered'):
                raise ValidationError(
                    'Solo se puede confirmar un parte en Borrador, En Curso o Registrado.')
            if not record._poultry_weighed_lines():
                raise ValidationError('El parte no tiene pesos cargados.')
            if record.date > fields.Date.today():
                raise ValidationError('La fecha de la pesada no puede ser futura.')
            if not record._get_coop_line():
                raise ValidationError(
                    'El lote %s no tiene una asignación vigente en el galpón %s a la '
                    'fecha %s.' % (record.batch_id.name, record.coop_id.name, record.date))
        # Las líneas sin peso son aves que no estaban: se borran al confirmar, así el
        # parte queda solo con las aves pesadas.
        self.line_ids.filtered(lambda line: line.weight_g <= 0).unlink()
        self.write({'state': 'done'})
        self._poultry_apply_indicator_values()

    def action_cancel(self):
        for record in self:
            if record.state == 'cancel':
                raise ValidationError('El parte ya está cancelado.')
        was_done = self.filtered(lambda r: r.state == 'done')
        self.write({'state': 'cancel'})
        # Recalcular desde los partes confirmados restantes del mismo lote y fecha
        # (o limpiar los valores si este era el último).
        was_done._poultry_apply_indicator_values()

    # ------------------------------------------------------------------
    # Planilla en papel
    # ------------------------------------------------------------------
    def _poultry_sheet_pages(self, rows_per_column=36, columns=3):
        """Secciones de la planilla: se llenan de arriba abajo, cada jaula con su título
        y sus aves. Las jaulas no se cortan: si una no entra en lo que queda de la
        sección, pasa entera a la siguiente. Solo se parte (marcada "continúa") una
        jaula con más aves de las que entran en una sección. Entre secciones se
        reparten lo más parejo posible. Devuelve páginas → columnas → grupos
        {cage, continued, rows}."""
        self.ensure_one()
        capacity = max(rows_per_column, 2)
        # Bloques: una jaula entera (título + aves), o los pedazos de una jaula más
        # grande que una sección.
        chunks = []
        for cage, cage_lines in self._poultry_sorted_lines().grouped('cage_id').items():
            rows = list(cage_lines)
            first = True
            while rows:
                chunks.append({'cage': cage, 'continued': not first,
                               'rows': rows[:capacity - 1]})
                rows = rows[capacity - 1:]
                first = False
        if not chunks:
            return []
        units = [1 + len(chunk['rows']) for chunk in chunks]
        sheets = max(1, -(-sum(units) // (capacity * columns)))
        while True:
            parts = self._poultry_partition(units, columns * sheets)
            if all(sum(units[start:end]) <= capacity for start, end in parts):
                break
            sheets += 1
        pages = []
        for index, (start, end) in enumerate(parts):
            if index % columns == 0:
                pages.append([])
            pages[-1].append(chunks[start:end])
        return pages

    @staticmethod
    def _poultry_partition(units, parts):
        """Corta la secuencia de bloques en `parts` tramos seguidos (algunos pueden
        quedar vacíos) de modo que el tramo más cargado sea lo más chico posible.
        Programación dinámica clásica. Devuelve [(inicio, fin), ...]."""
        count = len(units)
        prefix = [0]
        for unit in units:
            prefix.append(prefix[-1] + unit)
        infinity = float('inf')
        # best[k][i]: menor carga máxima repartiendo los primeros i bloques en k tramos
        best = [[infinity] * (count + 1) for _ in range(parts + 1)]
        cut = [[0] * (count + 1) for _ in range(parts + 1)]
        best[0][0] = 0
        for k in range(1, parts + 1):
            for i in range(count + 1):
                for j in range(i + 1):
                    if best[k - 1][j] == infinity:
                        continue
                    load = max(best[k - 1][j], prefix[i] - prefix[j])
                    if load < best[k][i]:
                        best[k][i] = load
                        cut[k][i] = j
        bounds = []
        end = count
        for k in range(parts, 0, -1):
            start = cut[k][end]
            bounds.append((start, end))
            end = start
        return list(reversed(bounds))

    # ------------------------------------------------------------------
    # Pantalla de celular (acción cliente poultry_weighing)
    # ------------------------------------------------------------------
    @api.model
    def poultry_mobile_list(self):
        """Pesadas para el celular: las que la oficina envió a pesar (En Curso), y las
        registradas en las últimas 24 horas para que el operador vea que quedaron hechas."""
        since = fields.Datetime.now() - timedelta(days=1)
        records = self.search([
            '|', ('state', '=', 'in_progress'),
            '&', ('state', '=', 'registered'), ('registered_date', '>=', since),
        ], order='state, date desc, coop_id, id desc')
        return [record._poultry_mobile_header() for record in records]

    def _poultry_mobile_header(self):
        self.ensure_one()
        registered = self.registered_date and fields.Datetime.context_timestamp(
            self, self.registered_date).strftime('%d/%m %H:%M')
        return {
            'id': self.id,
            'name': self.name,
            'state': self.state,
            'coop': self.coop_id.name,
            'batch': self.batch_id.name,
            'date': fields.Date.to_string(self.date),
            'week': self.batch_age_weeks,
            'birds_per_cage': self.birds_per_cage,
            'planned_bird_count': self.planned_bird_count,
            'bird_count': self.bird_count,
            'cage_count': self.cage_count,
            'weighed_cage_count': self.weighed_cage_count,
            'closed_cage_count': len(self.closed_cage_ids & self.line_ids.cage_id),
            'progress_pct': round(self.progress_pct),
            'average_weight_g': round(self.average_weight_g, 1),
            'registered': registered or '',
        }

    def _poultry_mobile_cage(self, cage, lines, summary, closed, with_lines=True):
        weighed = [line for line in lines if line.weight_g > 0]
        data = {
            'cage_id': cage.id,
            'code': cage.code,
            'line_count': len(lines),
            'bird_count': len(weighed),
            'average_weight_g': round(summary.average_weight_g, 1) if summary else 0.0,
            'cv_pct': round(summary.cv_pct, 1) if summary else 0.0,
            # El aviso se muestra en la tarjeta recién al cerrar la jaula: mientras se
            # carga, "2 de 4 aves" es solo el avance.
            'alert': (summary.alert if summary and closed and weighed else ''),
            'status': 'closed' if closed else ('open' if weighed else 'pending'),
        }
        if with_lines:
            data['lines'] = [{'id': line.id, 'bird_no': line.bird_no, 'weight_g': line.weight_g}
                             for line in lines]
        return data

    def poultry_mobile_data(self):
        """Encabezado y una tarjeta por jaula, con sus líneas, en el orden físico."""
        self.ensure_one()
        summaries = {summary.cage_id.id: summary for summary in self._poultry_cage_summaries()}
        lines_by_cage = {}
        for line in self._poultry_sorted_lines():
            lines_by_cage.setdefault(line.cage_id, []).append(line)
        closed = set(self.closed_cage_ids.ids)
        data = self._poultry_mobile_header()
        data['cages'] = [
            self._poultry_mobile_cage(cage, lines, summaries.get(cage.id), cage.id in closed)
            for cage, lines in lines_by_cage.items()]
        return data

    def _poultry_mobile_cage_state(self, cage):
        """Lo que cambia al escribir un peso: la tarjeta de la jaula y los totales."""
        self.ensure_one()
        summary = self._poultry_cage_summaries().filtered(lambda s: s.cage_id == cage)[:1]
        lines = self._poultry_sorted_lines().filtered(lambda line: line.cage_id == cage)
        return {
            'cage': self._poultry_mobile_cage(cage, lines, summary, cage in self.closed_cage_ids,
                                              with_lines=False),
            'record': self._poultry_mobile_header(),
        }

    def _poultry_mobile_check_editable(self):
        """Desde el celular solo se pesa lo que la oficina envió a pesar."""
        self.ensure_one()
        if self.state != 'in_progress':
            label = dict(self._fields['state']._description_selection(self.env))[self.state]
            raise ValidationError('La pesada %s está %s, no En Curso: no se pueden cambiar '
                                  'los pesos desde el celular.' % (self.name, label))

    def poultry_mobile_set_weight(self, line_id, weight_g):
        self.ensure_one()
        self._poultry_mobile_check_editable()
        line = self.env['poultry.weight.record.line'].browse(line_id)
        if line.record_id != self:
            raise ValidationError('La línea no pertenece a esta pesada.')
        line.weight_g = weight_g
        return self._poultry_mobile_cage_state(line.cage_id)

    def poultry_mobile_add_line(self, cage_id):
        """Una ave más de la que preveía el asistente."""
        self.ensure_one()
        self._poultry_mobile_check_editable()
        cage = self.env['poultry.cage'].browse(cage_id)
        lines = self.line_ids.filtered(lambda line: line.cage_id == cage)
        if not lines:
            raise ValidationError('La jaula %s no está en esta pesada.' % cage.code)
        self.env['poultry.weight.record.line'].create({
            'record_id': self.id,
            'cage_id': cage.id,
            'bird_no': max(lines.mapped('bird_no')) + 1,
            'sequence': max(lines.mapped('sequence')),
            'weight_g': 0.0,
        })
        return self.poultry_mobile_data()

    def poultry_mobile_remove_line(self, cage_id):
        """Una ave menos: saca la última línea de la jaula. Si todas tienen peso, el
        celular pide confirmar antes porque se pierde un peso cargado."""
        self.ensure_one()
        self._poultry_mobile_check_editable()
        cage = self.env['poultry.cage'].browse(cage_id)
        lines = self.line_ids.filtered(lambda line: line.cage_id == cage).sorted(
            key=lambda line: (line.bird_no, line.id))
        if len(lines) <= 1:
            raise ValidationError('La jaula %s tiene que quedar con al menos una ave.' % cage.code)
        empty = lines.filtered(lambda line: line.weight_g <= 0)
        (empty[-1] if empty else lines[-1]).unlink()
        return self.poultry_mobile_data()

    def poultry_mobile_close_cage(self, cage_id):
        self.ensure_one()
        self._poultry_mobile_check_editable()
        cage = self.env['poultry.cage'].browse(cage_id)
        self.closed_cage_ids |= cage
        return self._poultry_mobile_cage_state(cage)

    def poultry_mobile_find_cage(self, code):
        """Resuelve el QR leído: devuelve la jaula si es de esta pesada. Una jaula de
        muestreo marcada después de generar las líneas se agrega en el momento."""
        self.ensure_one()
        code = (code or '').strip()
        Cage = self.env['poultry.cage'].with_context(active_test=False)
        cage = Cage.search([('coop_id', '=', self.coop_id.id), ('code', '=', code)], limit=1)
        if not cage:
            other = Cage.search([('code', '=', code)], limit=1)
            if other:
                return {'error': 'La jaula %s es del galpón %s, no de %s.'
                                 % (code, other.coop_id.name, self.coop_id.name)}
            return {'error': 'No hay ninguna jaula con el código %s.' % code}
        added = False
        if cage not in self.line_ids.cage_id:
            if not cage.is_sampling or not cage.active:
                return {'error': 'La jaula %s no es de muestreo.' % cage.code}
            self._poultry_mobile_check_editable()
            self._poultry_add_cage_lines(cage, self.birds_per_cage or 1)
            added = True
        return {'cage_id': cage.id, 'added': added}

    def poultry_mobile_pending_cages(self):
        self.ensure_one()
        return self._poultry_pending_cages().mapped('code')

    def action_draft(self):
        for record in self:
            if record.state != 'cancel':
                raise ValidationError('Solo se puede volver a Borrador un parte Cancelado.')
        self.write({'state': 'draft'})

    @api.ondelete(at_uninstall=False)
    def _unlink_except_done(self):
        for record in self:
            if record.state in ('registered', 'done'):
                raise ValidationError(
                    'No se puede eliminar un parte Registrado o Confirmado. Cancelalo primero.')

    def _poultry_apply_indicator_values(self, only_indicators=None):
        """Publica (o limpia) los Valores Reales de los indicadores Peso Corporal y
        Uniformidad para cada (lote, fecha) tocado por estos partes.

        only_indicators (opcional): recordset de poultry.indicator para publicar SOLO
        esos (botón "Recalcular este indicador"), sin tocar los valores de los demás.

        Como el valor real es único por (lote, indicador, fecha) y un lote puede pesarse
        el mismo día en más de un galpón, siempre se agregan TODOS los partes confirmados
        del lote en esa fecha (no solo self): promedio ponderado por ave y uniformidad
        recalculada contra la media combinada.

        Se guarda numerator=gramos totales y denominator=aves pesadas para que el rollup
        semanal (accumulation_type='none') pondere correctamente pesadas múltiples en la
        misma semana, en vez de promediar promedios.

        IMPORTANTE: las categorías weight/uniformity NO deben agregarse a la lista de
        _poultry_rebuild_all_indicator_values (poultry_coop_close.py): ese rebuild
        borraría estos valores y solo sabe recalcular desde OFs de Huevo sin Clasificar.
        Los partes de peso son la única fuente de estas dos categorías.

        Se usa sudo() acotado sobre los modelos de valores para que el Usuario Avícola
        (solo lectura sobre indicadores) pueda confirmar sus propios partes."""
        Indicator = self.env['poultry.indicator'].sudo()
        Value = self.env['poultry.batch.indicator.value'].sudo()
        weight_indicator = Indicator._poultry_legacy_indicator('weight', 'none')
        uniformity_indicator = Indicator._poultry_legacy_indicator('uniformity', 'none')
        # Indicadores con fórmula cuya fuente es el Parte de Peso: los calcula el
        # motor. Los que no tienen fórmula siguen con el cálculo cableado de abajo.
        formula_indicators = Indicator._poultry_formula_indicators('weight_record')
        if only_indicators is not None:
            weight_indicator &= only_indicators
            uniformity_indicator &= only_indicators
            formula_indicators &= only_indicators
        indicators = weight_indicator | uniformity_indicator | formula_indicators
        if not indicators:
            # Sin indicadores configurados no hay dónde publicar: se omite en silencio
            # (misma convención que los cálculos de mrp_production).
            return

        pairs = {(record.batch_id.id, record.date): record.batch_id for record in self}
        for (batch_id, target_date), batch in pairs.items():
            siblings = self.search([
                ('batch_id', '=', batch_id),
                ('date', '=', target_date),
                ('state', '=', 'done'),
            ])
            lines = siblings.mapped('line_ids')
            if lines:
                weights = lines.mapped('weight_g')
                birds = len(weights)
                total_g = sum(weights)
                avg_g = total_g / birds
                coop = siblings.sorted(key=lambda r: r.id)[-1].coop_id
                in_band = 0
                for line in lines:
                    band_pct = line.record_id.uniformity_band_pct or 10.0
                    if avg_g and abs(line.weight_g - avg_g) <= avg_g * band_pct / 100.0:
                        in_band += 1
                if formula_indicators:
                    # Mismos datos crudos que el cálculo cableado, con las claves que
                    # ofrecen los campos Numerador/Denominador del indicador.
                    Indicator._poultry_apply_formulas(
                        {batch.id: {
                            'batch': batch,
                            'weighed_g': float(total_g),
                            'uniform_birds': float(in_band),
                            'weighed_birds': float(birds),
                            'one': 1.0,
                        }},
                        coop, target_date, source='weight_record',
                        only_indicators=formula_indicators)
                if weight_indicator:
                    Value._set_value(batch, coop, target_date, weight_indicator, avg_g,
                                     numerator=total_g, denominator=birds)
                if uniformity_indicator:
                    Value._set_value(batch, coop, target_date, uniformity_indicator,
                                     in_band / birds * 100.0,
                                     numerator=in_band * 100.0, denominator=birds)
            else:
                # Se canceló el último parte del día: borrar los valores diarios y
                # limpiar/recalcular el semanal a mano, porque _recompute_weekly_value
                # no hace nada cuando la semana queda sin valores diarios (mismo motivo
                # que la limpieza de _poultry_rebuild_all_indicator_values).
                Value.search([
                    ('batch_id', '=', batch_id),
                    ('indicator_id', 'in', indicators.ids),
                    ('date', '=', target_date),
                ]).unlink()
                for indicator in indicators:
                    self._poultry_refresh_week(batch, indicator, target_date)

    @api.model
    def _poultry_refresh_week(self, batch, indicator, target_date):
        """Rehace el valor semanal de la semana de target_date después de borrar valores
        diarios: _recompute_weekly_value no hace nada cuando la semana queda sin valores
        diarios, así que en ese caso el semanal se borra a mano."""
        Value = self.env['poultry.batch.indicator.value'].sudo()
        Weekly = self.env['poultry.batch.indicator.weekly.value'].sudo()
        if not batch.birth_date or target_date < batch.birth_date:
            return
        week = batch._poultry_week_of(target_date)
        remaining = Value.search([
            ('batch_id', '=', batch.id),
            ('indicator_id', '=', indicator.id),
            ('date', '>=', batch._poultry_week_start(week)),
            ('date', '<=', batch._poultry_week_end(week)),
        ], limit=1)
        if remaining:
            Value._recompute_weekly_value(batch, indicator, target_date)
            return
        weekly_domain = [
            ('batch_id', '=', batch.id),
            ('indicator_id', '=', indicator.id),
            ('week', '=', week),
        ]
        # Solo se borra el semanal de Origen=Sistema: uno Manual es un dato histórico
        # cargado a mano y no depende de estos partes.
        if 'source' in Weekly._fields:
            weekly_domain.append(('source', '=', 'system'))
        Weekly.search(weekly_domain).unlink()

    @api.model
    def _poultry_rebuild_indicator(self, indicator):
        """Rehace los Valores Reales de UN indicador que sale del Parte de Peso, desde
        todos los partes confirmados (botón "Recalcular este indicador"). El recálculo de
        los Cierres de Galpón no lo toca: los partes de peso son su única fuente.

        - Cada día con partes confirmados se vuelve a publicar, en orden cronológico
          (los modos acumulados dependen del día anterior).
        - Se borran los valores que vienen de una OF (production_id): son de cuando el
          indicador tenía otra fórmula y ya no corresponden.
        - Los demás valores diarios sin parte confirmado ese día se dejan: pueden ser
          carga manual del Gestor (un parte cancelado ya limpió los suyos).
        Devuelve la cantidad de días (lote, fecha) publicados."""
        Value = self.env['poultry.batch.indicator.value'].sudo()
        stale = Value.search([('indicator_id', '=', indicator.id), ('production_id', '!=', False)])
        touched = {(value.batch_id, value.date) for value in stale}
        stale.unlink()
        records = self.sudo().search([('state', '=', 'done')], order='date, id')
        records._poultry_apply_indicator_values(only_indicators=indicator)
        published = {(record.batch_id, record.date) for record in records}
        for batch, target_date in touched - published:
            self._poultry_refresh_week(batch, indicator, target_date)
        return len(published)
