# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.float_utils import float_compare


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    coop_id = fields.Many2one('poultry.coop', string='Galpón', 
                               domain="[('active', '=', True)]",
                               help='Seleccione un galpón para cargar automáticamente el producto y la lista de materiales activa')
    egg_collection_id = fields.Many2one('poultry.egg.collection', string='Recolección de Huevos',
                                         readonly=True)
    coop_close_id = fields.Many2one('poultry.coop.close', string='Cierre de Galpón',
                                    readonly=True, copy=False,
                                    help='Cierre de galpón que generó esta OF de huevo sin clasificar')
    # groups: los campos avícolas de mortandad solo existen para usuarios con rol
    # avícola. Sin esto, cualquier usuario de Manufactura ajeno al módulo (ej. la
    # planta de alimentos, que usa el Galpón solo para elegir la fórmula) recibía
    # "Error de acceso" al abrir/procesar sus OFs: el cliente web lee TODOS los
    # campos de la vista -incluso los de solapas ocultas-, y leer el One2many exige
    # acceso de lectura sobre poultry.mortality, que es solo de los grupos avícolas.
    poultry_dead_count_total = fields.Integer(
        string='Aves Muertas (total galpón)', copy=False,
        groups='poultry_management.poultry_user,poultry_management.poultry_manager',
        help='Cantidad total de aves muertas del galpón en la fecha de esta OF. Se reparte '
             'automáticamente entre los lotes presentes según su población viva, generando '
             'un registro de mortandad por lote.')
    poultry_mortality_ids = fields.One2many(
        'poultry.mortality', 'production_id', string='Registros de Mortalidad', readonly=True,
        groups='poultry_management.poultry_user,poultry_management.poultry_manager')
    # Fecha real a la que se imputan los huevos, la mortandad y TODOS los
    # indicadores de esta OF (no la fecha técnica de Odoo). La setea el Cierre de
    # Galpón al crear la OF de Huevo sin Clasificar (= fecha del cierre); el grupo
    # "Mortandad: Carga Manual" puede corregirla incluso con la OF Hecha (el write
    # resincroniza mortandad y recalcula indicadores automáticamente).
    poultry_collection_date = fields.Date(
        string='Fecha de Recolección/Postura', copy=False,
        groups='poultry_management.poultry_user,poultry_management.poultry_manager',
        help='Fecha real de la recolección/postura: es la fecha a la que se imputan '
             'los huevos, la mortandad y todos los indicadores de esta OF. Se toma '
             'del Cierre de Galpón al crearla.')
    
    def _get_scheduled_date(self):
        """Obtiene la fecha programada de la OF con tolerancia entre versiones."""
        self.ensure_one()
        for field_name in ('date_start', 'date_planned_start'):
            value = getattr(self, field_name, False)
            if value:
                return fields.Datetime.to_datetime(value).date()
        return fields.Date.context_today(self)

    def _apply_coop_active_bom(self):
        """Carga producto y BOM del galpón para la fecha programada."""
        self.ensure_one()
        if not self.coop_id:
            self.product_id = False
            self.bom_id = False
            return

        scheduled_date = self._get_scheduled_date()
        active_bom = self.env['poultry.coop.bom'].get_active_bom_for_coop_date(
            self.coop_id.id, scheduled_date
        )
        if not active_bom:
            self.product_id = False
            self.bom_id = False
            return {
                'warning': {
                    'title': 'Sin lista activa para la fecha',
                    'message': (
                        f'No existe una lista de materiales activa para el galpón '
                        f'{self.coop_id.display_name} en la fecha {scheduled_date}.'
                    ),
                }
            }

        self.product_id = active_bom.bom_product_id or False
        self.bom_id = active_bom.bom_id or False
        if self.bom_id and hasattr(self, '_onchange_bom_id'):
            self._onchange_bom_id()
        elif hasattr(self, '_onchange_product_id'):
            self._onchange_product_id()
        return {}

    @api.onchange('coop_id', 'date_start')
    def _onchange_coop_or_date(self):
        """Refresca BOM/producto al cambiar galpón o fecha programada."""
        warning = {}
        for production in self:
            result = production._apply_coop_active_bom()
            if result and result.get('warning'):
                warning = result
        return warning

    # -- Mortandad de aves (solo OF de Huevo sin Clasificar) --------------------
    # El registro se materializa al confirmar/producir la OF (button_mark_done), no en
    # cada guardado del total; y se elimina al desmantelar la OF (ver mrp_unbuild.py).

    def _poultry_target_date(self):
        """Fecha a la que se imputa TODO lo derivado de esta OF (huevos, mortandad,
        consumos e indicadores): la Fecha de Recolección/Postura si está cargada,
        si no la del Cierre de Galpón, y en último caso la fecha programada de la
        OF. sudo() acotado: poultry_collection_date tiene groups= (ver el
        comentario del bloque de campos) y este helper también corre en flujos de
        sistema (rebuild, migraciones) sin usuario avícola."""
        self.ensure_one()
        return (self.sudo().poultry_collection_date
                or (self.coop_close_id.date if self.coop_close_id else False)
                or self._get_scheduled_date())

    # Campos avícolas corregibles en una OF ya procesada (sin desmantelarla),
    # solo por el grupo "Mortandad: Carga Manual"; al corregirlos el write
    # resincroniza la mortandad y recalcula los indicadores automáticamente.
    _POULTRY_PROTECTED_DONE_FIELDS = ('poultry_dead_count_total', 'poultry_collection_date')

    def write(self, vals):
        """Permite corregir Aves Muertas / Fecha de Recolección de una OF de cierre
        ya Hecha sin desmantelarla: verifica el permiso server-side (la vista solo
        gatea la UX), y tras guardar resincroniza la mortandad y reconstruye los
        indicadores desde la fecha más vieja afectada hacia adelante (los
        acumulados propagan hacia adelante: nunca acotar el rebuild con date_to)."""
        touched = [f for f in self._POULTRY_PROTECTED_DONE_FIELDS if f in vals]
        to_resync = self.env['mrp.production']
        old_dates = {}
        if touched and not self.env.context.get('poultry_skip_done_edit_check'):
            for mo in self:
                if mo.state != 'done' or not mo.coop_close_id:
                    continue
                # sudo() acotado: los campos tienen groups= y hay que COMPARAR su
                # valor actual aunque el que escribe no sea usuario avícola.
                mo_sudo = mo.sudo()
                changed = False
                for field_name in touched:
                    new_val = vals[field_name]
                    if field_name == 'poultry_collection_date':
                        new_val = fields.Date.to_date(new_val)  # el cliente manda string
                    if (new_val or False) != (mo_sudo[field_name] or False):
                        changed = True
                        break
                if not changed:
                    continue
                if not self.env.user.has_group('poultry_management.group_poultry_mortality_manual'):
                    raise AccessError(
                        'Solo los usuarios con el permiso "Mortandad: Carga Manual" '
                        'pueden corregir las Aves Muertas o la Fecha de Recolección/'
                        'Postura de una OF ya procesada.')
                old_dates[mo.id] = mo._poultry_target_date()
                to_resync |= mo
        result = super().write(vals)
        for mo in to_resync:
            # Primero la mortandad (las aves vivas del recálculo dependen de los
            # registros ya movidos a la fecha nueva), después el rebuild — mismo
            # orden que button_mark_done. Acotado al galpón de la OF (con expansión
            # por lotes compartidos dentro del rebuild).
            mo._poultry_sync_mortality()
            rebuild_from = min(old_dates[mo.id], mo._poultry_target_date())
            self.env['poultry.coop.close']._poultry_rebuild_all_indicator_values(
                date_from=rebuild_from, coops=mo.coop_id)
        return result

    @api.constrains('poultry_collection_date')
    def _check_poultry_collection_date_unique(self):
        """Dos OFs de cierre del mismo galpón no pueden imputar a la misma fecha
        efectiva: los valores diarios son únicos por (lote, indicador, fecha) y el
        upsert de _set_value PISARÍA los de la otra OF (el resultado dependería
        del orden de recálculo). La restricción de unicidad de Cierres solo cubre
        la fecha del cierre, no una Fecha de Recolección corregida."""
        for mo in self.sudo():
            if not mo.coop_close_id or not mo.coop_id:
                continue
            eff = mo._poultry_target_date()
            clash = self.sudo().search([
                ('id', '!=', mo.id),
                ('coop_close_id', '!=', False),
                ('coop_id', '=', mo.coop_id.id),
                ('state', '!=', 'cancel'),
                '|',
                ('poultry_collection_date', '=', eff),
                '&',
                ('poultry_collection_date', '=', False),
                ('coop_close_id.date', '=', eff),
            ], limit=1)
            if clash:
                raise ValidationError(
                    f'Ya existe otra OF de cierre del galpón {mo.coop_id.display_name} '
                    f'que imputa a la fecha {eff} ({clash.display_name}). Dos OFs del '
                    f'mismo galpón no pueden compartir Fecha de Recolección/Postura.')

    def _poultry_distribute_integer(self, total, lines, birds_by_line):
        """Reparte un entero 'total' entre 'lines' proporcional a su población viva
        (birds_by_line), usando el método del mayor resto para que la suma de las partes
        sea exactamente 'total' sin perder unidades por redondeo."""
        total_birds = sum(birds_by_line.get(line.id, 0) for line in lines)
        if total_birds <= 0:
            return {}
        shares = {}
        floor_sum = 0
        remainders = []
        for line in lines:
            exact = total * birds_by_line.get(line.id, 0) / total_birds
            base = int(exact)
            shares[line.id] = base
            floor_sum += base
            remainders.append((exact - base, line.id))
        leftover = total - floor_sum
        remainders.sort(reverse=True)
        for i in range(leftover):
            shares[remainders[i % len(remainders)][1]] += 1
        return shares

    def _poultry_sync_mortality(self):
        """Regenera los registros poultry.mortality de esta OF a partir del total cargado
        en poultry_dead_count_total, repartiéndolo entre los lotes presentes en el galpón
        a la fecha según su población viva. Borra primero los registros previos de esta
        OF para que la base de reparto no se descuente a sí misma."""
        self.ensure_one()
        Mortality = self.env['poultry.mortality']
        Mortality.search([('production_id', '=', self.id)]).unlink()

        total = self.poultry_dead_count_total or 0
        if total <= 0 or not self.coop_id:
            return

        target_date = self._poultry_target_date()
        lines, birds_by_line, total_birds = self._poultry_get_active_lines_and_birds(target_date)
        if not lines or total_birds <= 0:
            raise UserError(
                f'No hay lotes con aves vivas en el galpón {self.coop_id.display_name} '
                f'a la fecha {target_date}. No se puede registrar la mortandad.'
            )
        if total > total_birds:
            raise UserError(
                f'Las aves muertas ({total}) superan las aves vivas del galpón '
                f'{self.coop_id.display_name} ({total_birds}) a la fecha {target_date}.'
            )

        shares = self._poultry_distribute_integer(total, lines, birds_by_line)
        vals_list = []
        for line in lines:
            share = shares.get(line.id, 0)
            if share <= 0:
                continue
            vals_list.append({
                'production_id': self.id,
                'coop_id': self.coop_id.id,
                'batch_id': line.batch_id.id,
                'genetics_id': line.batch_id.genetics_id.id,
                'date': target_date,
                'dead_count': share,
            })
        if vals_list:
            Mortality.create(vals_list)

    def _poultry_get_finished_qty_for_validation(self):
        """
        Cantidad del producto final a usar en la validación.
        Prioriza qty_producing (si existe y está seteado) y cae a product_qty.
        """
        self.ensure_one()
        qty_producing = getattr(self, 'qty_producing', 0.0) or 0.0
        return qty_producing if qty_producing > 0 else (self.product_qty or 0.0)

    def _poultry_get_move_consumed_qty(self, move):
        """
        Obtiene la cantidad consumida de un stock.move en su propia UdM.
        Usa quantity_done si existe, si no quantity, y como último recurso suma qty_done de move_line_ids.
        """
        qty = getattr(move, 'quantity_done', None)
        if qty is None:
            qty = getattr(move, 'quantity', None)
        if qty is None:
            qty = sum(getattr(move, 'move_line_ids', self.env['stock.move.line']).mapped('qty_done') or [0.0])
        return qty or 0.0

    def _poultry_get_egg_uom(self, uom):
        """
        Devuelve la unidad marcada como Huevo (is_poultry_egg) en la categoría
        de la UdM recibida. Es la unidad de referencia para convertir a huevos.
        """
        if not uom:
            return self.env['uom.uom']
        return self.env['uom.uom'].search([
            ('category_id', '=', uom.category_id.id),
            ('is_poultry_egg', '=', True),
        ], limit=1)

    def _poultry_qty_to_eggs(self, qty, uom):
        """
        Convierte una cantidad en su UdM a cantidad de Huevos, usando la
        conversión estándar de Odoo dentro de la categoría hacia la unidad
        marcada como Huevo de esa misma categoría.

        Devuelve None si la categoría de la UdM no tiene unidad Huevo, es decir,
        si la UdM no representa huevos (p. ej. film en gramos, cajas en unidades).
        Nunca cruza categorías, por lo que no dispara el error de Odoo de
        "distinta categoría".
        """
        egg_uom = self._poultry_get_egg_uom(uom)
        if not egg_uom:
            return None
        return uom._compute_quantity(qty or 0.0, egg_uom)

    def _poultry_validate_kit_consumption_equals_finished(self):
        """
        Valida que, en una OF marcada como Mix Producto Avícola, la suma de los
        componentes que SON huevos (convertidos a Huevos según la UdM Huevo de
        cada categoría) sea igual a la cantidad de huevos producida.

        Los componentes que no son huevos (film, cajas, etc., medidos en gramos
        o unidades) se ignoran: pueden mezclarse libremente en la OF. El producido
        y los componentes huevo pueden estar en categorías de UdM distintas.
        """
        self.ensure_one()
        finished_qty = self._poultry_get_finished_qty_for_validation()
        finished_eggs = self._poultry_qty_to_eggs(finished_qty, self.product_uom_id)
        if finished_eggs is None:
            raise UserError(
                f'No hay una unidad marcada como Huevo (referencia) en la categoría '
                f'"{self.product_uom_id.category_id.display_name}" del producto a producir. '
                f'Configúrela en Gestión Avícola > Unidades de Medida.'
            )
        egg_uom = self._poultry_get_egg_uom(self.product_uom_id)

        total_eggs = 0.0
        for move in self.move_raw_ids.filtered(lambda m: m.state != 'cancel'):
            consumed = self._poultry_get_move_consumed_qty(move)
            consumed_eggs = self._poultry_qty_to_eggs(consumed, move.product_uom)
            if consumed_eggs is None:
                # Componente que no es huevo (p. ej. film en gramos): no participa del balance.
                continue
            total_eggs += consumed_eggs

        rounding = egg_uom.rounding or 0.01
        if float_compare(total_eggs, finished_eggs, precision_rounding=rounding) != 0:
            raise UserError(
                f'Validación KIT: la suma de huevos consumidos ({total_eggs:g} huevos) '
                f'no coincide con los huevos producidos ({finished_eggs:g} huevos).'
            )

    def button_mark_done(self):
        # Advertencia de mortandad en cero: si una OF de cierre se va a procesar
        # sin Aves Muertas cargadas, se pregunta antes de tocar nada (por eso va
        # ANTES de la validación kit y del super: si el operador cancela, no debe
        # haber cambiado nada). Confirmar reintenta con el flag de contexto.
        # sudo() acotado: el campo tiene groups= y el botón puede apretarlo un
        # usuario de Manufactura sin rol avícola (el dato faltante es del galpón,
        # el aviso aplica igual).
        if not self.env.context.get('poultry_skip_zero_dead_warning'):
            pending = self.filtered(
                lambda m: m.coop_close_id and not m.sudo().poultry_dead_count_total)
            if pending:
                wizard = self.env['poultry.zero.mortality.confirm.wizard'].create({
                    'production_ids': [(6, 0, self.ids)],
                    'pending_names': ', '.join(pending.mapped('display_name')),
                })
                return {
                    'type': 'ir.actions.act_window',
                    'name': 'Confirmar sin Aves Muertas',
                    'res_model': 'poultry.zero.mortality.confirm.wizard',
                    'res_id': wizard.id,
                    'view_mode': 'form',
                    'target': 'new',
                }
        for mo in self:
            tmpl = mo.product_id.product_tmpl_id if mo.product_id else False
            if tmpl and getattr(tmpl, 'poultry_validate_kit_consumption', False):
                mo._poultry_validate_kit_consumption_equals_finished()
        result = super().button_mark_done()
        # La mortandad se guarda en la tabla recién al confirmar/producir la OF de Huevo
        # sin Clasificar (no en cada guardado del total). Se sincroniza ANTES de calcular
        # los indicadores para que las Aves Vivas del día reflejen la mortandad registrada,
        # igual que en el recálculo histórico (_poultry_rebuild_all_indicator_values). Si
        # el total supera las aves vivas, _poultry_sync_mortality levanta UserError y toda
        # la operación (incluido el producido) se revierte.
        for mo in self:
            if mo.coop_close_id:
                mo._poultry_sync_mortality()
            mo._poultry_compute_all_indicator_values()
        return result

    def _poultry_get_consumption_uom(self, xml_id):
        uom = self.env.ref(xml_id, raise_if_not_found=False)
        return uom or self.env['uom.uom']

    def _poultry_get_active_lines_and_birds(self, target_date):
        """Devuelve (lines, birds_by_line, total_birds): las poultry.batch.coop.line
        activas para self.coop_id en target_date, y la población viva de cada una.
        Compartido por el cálculo de consumo y el de producción de huevos."""
        self.ensure_one()
        lines = self.env['poultry.batch.coop.line'].search([
            ('coop_id', '=', self.coop_id.id),
            ('active', '=', True),
            ('date_from', '<=', target_date),
            '|', ('date_to', '=', False), ('date_to', '>=', target_date),
        ])
        birds_by_line = {line.id: line._get_live_bird_count_on(target_date) for line in lines}
        return lines, birds_by_line, sum(birds_by_line.values())

    def _poultry_previous_accumulated(self, batch, indicator, target_date):
        """Valor acumulado previo desde el cual continuar la suma corrida de un
        indicador acumulado (empalme). Devuelve, en este orden de prioridad:
        1) el último Valor Real DIARIO del sistema anterior a target_date;
        2) si no hay, el último Valor Real SEMANAL MANUAL con Fecha del Dato anterior
           a target_date (dato histórico cargado a mano, ej. el acumulado al final de
           la crianza antes de empezar a usar Odoo);
        3) 0.0 si no hay ninguno.
        Así los acumulados del sistema (que arrancan cuando ya hay datos) continúan
        a partir del histórico manual en vez de reiniciarse en cero."""
        Value = self.env['poultry.batch.indicator.value'].sudo()
        previous = Value.search([
            ('batch_id', '=', batch.id),
            ('indicator_id', '=', indicator.id),
            ('date', '<', target_date),
        ], order='date desc', limit=1)
        if previous:
            return previous.value
        if batch.birth_date and target_date >= batch.birth_date:
            Weekly = self.env['poultry.batch.indicator.weekly.value'].sudo()
            base = [
                ('batch_id', '=', batch.id),
                ('indicator_id', '=', indicator.id),
                ('source', '=', 'manual'),
            ]
            # Se busca por FECHA DEL DATO, no por número de semana. El histórico
            # manual viene de planillas cuya semana no coincide con la Semana de
            # Vida de Odoo, y los datos diarios casi siempre arrancan en MEDIO de
            # una semana. Con 'week < semana_actual' ese último valor manual queda
            # descartado justo cuando el empalme cae dentro de su semana, y las
            # bajas de esos días no las toma nadie: el acumulado sigue corrido
            # hacia abajo por esa misma diferencia para siempre.
            manual = Weekly.search(
                base + [('manual_date', '<', target_date)],
                order='manual_date desc', limit=1)
            if not manual:
                # Cargas viejas sin Fecha del Dato: se cae al criterio por semana.
                manual = Weekly.search(
                    base + [('manual_date', '=', False),
                            ('week', '<', batch._poultry_week_of(target_date))],
                    order='week desc', limit=1)
            if manual:
                return manual.real_value
        return 0.0

    def _poultry_compute_all_indicator_values(self, only_indicators=None):
        """Punto de entrada único para calcular todos los indicadores reales derivados
        de esta OF de Huevo sin Clasificar (consumo + producción de huevos). Se llama
        tanto desde button_mark_done() (tiempo real) como desde el recálculo histórico
        (poultry.coop.close._poultry_rebuild_all_indicator_values).

        only_indicators: recordset de poultry.indicator para recalcular SOLO esos
        (botón "Recalcular este indicador" de la ficha), sin tocar los valores de
        los demás. Los cálculos cableados se saltean en ese caso: identifican al
        indicador por categoría, no reciben un filtro, y recalcular todo sería
        justamente lo que el usuario está evitando."""
        self.ensure_one()
        if not self.coop_close_id or not self.coop_id:
            return
        # Motor de fórmulas: calcula los indicadores que tienen Numerador,
        # Denominador y Modo de Cálculo configurados en su ficha. Los cálculos
        # cableados que siguen abajo solo alcanzan a los indicadores SIN fórmula
        # (buscan con _poultry_legacy_indicator), así que nunca se pisan.
        target_date = self._poultry_target_date()
        magnitudes = self._poultry_collect_magnitudes(target_date)
        if magnitudes:
            self.env['poultry.indicator'].sudo()._poultry_apply_formulas(
                magnitudes, self.coop_id, target_date, production=self,
                only_indicators=only_indicators)

        if only_indicators is not None:
            return

        self._poultry_compute_consumption_indicator_values()
        self._poultry_compute_egg_production_indicator_values()
        self._poultry_compute_mortality_indicator_values()
        self._poultry_compute_egg_mass_and_weight_indicator_values()
        self._poultry_compute_viability_indicator_values()
        self._poultry_compute_feed_conversion_indicator_values()

    # -- Motor de fórmulas: recolección de datos crudos --------------------------

    def _poultry_production_cost(self):
        """Costo real de esta OF: la suma de las capas de valuación de los
        componentes consumidos, o sea lo que Odoo muestra en el botón "Valoración"
        (las líneas negativas, la salida de stock). Es el costo con el que el stock
        salió realmente, ya congelado por Odoo -no se recalcula con el precio de
        coste de hoy-, así que el histórico no cambia si después se actualiza un
        precio.

        Devuelve None (no 0.0) cuando no hay valuación disponible, para que el
        indicador de costo quede sin valor ese día en vez de mostrar un cero
        engañoso: pasa si la contabilidad de stock no está instalada, o si la OF
        todavía no se marcó como Hecha (las capas se crean recién ahí)."""
        self.ensure_one()
        Move = self.env['stock.move']
        if 'stock_valuation_layer_ids' not in Move._fields:
            # Sin contabilidad de stock (stock_account) no existen las capas: el
            # módulo sigue funcionando, solo que sin indicadores de costo.
            return None
        layers = self.sudo().move_raw_ids.filtered(
            lambda m: m.state != 'cancel').mapped('stock_valuation_layer_ids')
        if not layers:
            return None
        # Las capas de consumo son negativas (sale del stock): el costo es su
        # valor absoluto.
        return abs(sum(layers.mapped('value')))

    def _poultry_collect_magnitudes(self, target_date):
        """Datos crudos del día por lote, para que el motor de fórmulas
        (poultry.indicator._poultry_apply_formulas) arme cualquier indicador sin
        que la fórmula esté cableada acá. Devuelve {batch_id: {clave: valor}} con
        las claves que ofrecen los campos Numerador/Denominador del indicador.

        Reusa exactamente las mismas fuentes que los cálculos cableados, para que
        los números coincidan: la población viva del día
        (_poultry_get_active_lines_and_birds), los huevos de la OF (product_qty),
        la masa estimada de los Partes del cierre, los componentes de la OF
        marcados como Alimento/Agua, y los Registros de Aves Muertas de la fecha.

        Los datos del GALPÓN (huevos, masa, alimento, agua) se reparten entre los
        lotes presentes según su población viva, igual que hoy. Los atributos del
        HUEVO (gramos medidos, huevos con peso) NO se reparten: son el mismo valor
        para todos los lotes, porque describen el huevo y no cuántas aves hay."""
        self.ensure_one()
        lines, birds_by_line, total_birds = self._poultry_get_active_lines_and_birds(target_date)
        if not lines or total_birds <= 0:
            return {}

        # Huevos del galpón del día (mismo dato que usa el cálculo cableado).
        total_eggs = self.product_qty or 0.0

        # Masa de huevo: Peso Medio Elaborado extrapolado a TODOS los huevos
        # (Total Peso Estimado del Parte), y los gramos medidos por separado.
        collections = self.coop_close_id.egg_collection_ids.filtered(lambda c: c.state == 'done')
        measured_mass_grams = 0.0
        eggs_with_weight = 0.0
        all_collection_eggs = 0.0
        for line in collections.mapped('line_ids'):
            all_collection_eggs += line.total_produced_reference or 0.0
            if line.average_weight and line.total_produced_reference:
                measured_mass_grams += line.average_weight * line.total_produced_reference
                eggs_with_weight += line.total_produced_reference
        avg_weight_g = (measured_mass_grams / eggs_with_weight) if eggs_with_weight else 0.0
        estimated_mass_grams = avg_weight_g * all_collection_eggs

        # Consumo de Alimento y Agua de la OF (tipo congelado en cada movimiento).
        kg_uom = self._poultry_get_consumption_uom('uom.product_uom_kgm')
        liter_uom = self._poultry_get_consumption_uom('uom.product_uom_litre')
        feed_qty_kg = 0.0
        water_qty_l = 0.0
        for move in self.move_raw_ids.filtered(lambda m: m.state != 'cancel'):
            consumption_type = move._poultry_consumption_type()
            if consumption_type not in ('feed', 'water'):
                continue
            qty = self._poultry_get_move_consumed_qty(move)
            if consumption_type == 'feed':
                feed_qty_kg += move.product_uom._compute_quantity(qty, kg_uom) if kg_uom else qty
            else:
                water_qty_l += move.product_uom._compute_quantity(qty, liter_uom) if liter_uom else qty

        # Costo real del día (capas de valuación de los componentes consumidos).
        production_cost = self._poultry_production_cost()

        # Aves muertas del día por lote: los registros de esta OF y los cargados a
        # mano para el mismo galpón y fecha (la mortandad del día es la suma).
        dead_by_batch = {}
        mortalities = self.env['poultry.mortality'].sudo().search([
            ('coop_id', '=', self.coop_id.id),
            ('date', '=', target_date),
            ('active', '=', True),
        ])
        for mortality in mortalities.filtered('batch_id'):
            dead_by_batch[mortality.batch_id.id] = (
                dead_by_batch.get(mortality.batch_id.id, 0) + mortality.dead_count)

        magnitudes = {}
        for line in lines:
            birds = birds_by_line.get(line.id, 0)
            if birds <= 0:
                continue
            batch = line.batch_id
            share = birds / total_birds
            dead = dead_by_batch.get(batch.id, 0)
            batch_eggs = total_eggs * share
            batch_mass_g = estimated_mass_grams * share
            batch_feed_kg = feed_qty_kg * share
            batch_water_l = water_qty_l * share
            magnitudes[batch.id] = {
                'batch': batch,
                # Numeradores
                'eggs': batch_eggs,
                # Costo del día repartido entre los lotes del galpón, igual que el
                # resto de los datos del galpón. Ausente (no cero) si la OF no
                # tiene valuación: así el indicador de costo no se calcula ese día.
                **({'production_cost': production_cost * share}
                   if production_cost is not None else {}),
                'egg_mass_g': batch_mass_g,
                'egg_mass_kg': batch_mass_g / 1000.0,
                'measured_egg_g': measured_mass_grams,   # atributo del huevo: no se reparte
                'dead_birds': float(dead),
                'feed_kg': batch_feed_kg,
                'feed_g': batch_feed_kg * 1000.0,
                'water_l': batch_water_l,
                'water_ml': batch_water_l * 1000.0,
                # Denominadores (live_birds también sirve de numerador en Viabilidad)
                'live_birds': float(birds),
                # Base del % de Mortandad: las vivas ANTES de las muertas del día.
                'live_birds_start': float(birds + dead),
                'housed_birds': float(batch.housed_bird_count or 0.0),
                # Aves Alojadas con respaldo en la Cantidad de Aves: base de la
                # Viabilidad, que en crianza (sin Cambio de Período todavía) no
                # tiene una foto alojada válida y usa las aves originales.
                'housed_or_original_birds': float(
                    batch.housed_bird_count
                    if (batch.housed_bird_count and batch.production_start_date
                        and target_date >= batch.production_start_date)
                    else (batch.bird_count or 0.0)),
                'original_birds': float(batch.bird_count or 0.0),
                'eggs_with_weight': eggs_with_weight,    # atributo del huevo: no se reparte
                'one': 1.0,
                # egg_units depende de Huevos por Unidad, que es propio de cada
                # indicador: lo resuelve el motor, no el recolector.
                '_eggs_for_units': batch_eggs,
            }
        return magnitudes

    def _poultry_compute_consumption_indicator_values(self):
        """Al cerrar la OF de Huevo sin Clasificar generada por un Cierre de Galpón,
        calcula el consumo real de Alimento (g/ave-día) y Agua (ml/ave-día) sumando
        las líneas de componentes marcadas como tales, y lo reparte entre los lotes
        presentes en el galpón esa fecha según su población viva ese día
        (poultry.batch.coop.line), guardando el resultado en
        poultry.batch.indicator.value."""
        self.ensure_one()
        if not self.coop_close_id or not self.coop_id:
            return

        target_date = self._poultry_target_date()

        kg_uom = self._poultry_get_consumption_uom('uom.product_uom_kgm')
        liter_uom = self._poultry_get_consumption_uom('uom.product_uom_litre')

        feed_qty_kg = 0.0
        water_qty_l = 0.0
        for move in self.move_raw_ids.filtered(lambda m: m.state != 'cancel'):
            # Tipo congelado en el movimiento (no el actual de la Lista): así un
            # cambio posterior del componente de alimento no altera este consumo.
            consumption_type = move._poultry_consumption_type()
            if consumption_type not in ('feed', 'water'):
                continue
            qty = self._poultry_get_move_consumed_qty(move)
            if consumption_type == 'feed':
                feed_qty_kg += move.product_uom._compute_quantity(qty, kg_uom) if kg_uom else qty
            else:
                water_qty_l += move.product_uom._compute_quantity(qty, liter_uom) if liter_uom else qty

        if feed_qty_kg <= 0 and water_qty_l <= 0:
            return

        lines, birds_by_line, total_birds = self._poultry_get_active_lines_and_birds(target_date)
        if not lines or total_birds <= 0:
            return

        Indicator = self.env['poultry.indicator'].sudo()
        feed_indicator = Indicator._poultry_legacy_indicator('feed_consumption', 'none')
        water_indicator = Indicator._poultry_legacy_indicator('water_consumption', 'none')

        Value = self.env['poultry.batch.indicator.value'].sudo()
        feed_g_per_bird_day = (feed_qty_kg * 1000.0 / total_birds) if feed_qty_kg > 0 else 0.0
        water_ml_per_bird_day = (water_qty_l * 1000.0 / total_birds) if water_qty_l > 0 else 0.0

        for line in lines:
            birds = birds_by_line[line.id]
            if birds <= 0:
                continue
            if feed_indicator and feed_qty_kg > 0:
                Value._set_value(line.batch_id, self.coop_id, target_date, feed_indicator,
                                  feed_g_per_bird_day,
                                  numerator=feed_g_per_bird_day * birds, denominator=birds,
                                  production=self)
            if water_indicator and water_qty_l > 0:
                Value._set_value(line.batch_id, self.coop_id, target_date, water_indicator,
                                  water_ml_per_bird_day,
                                  numerator=water_ml_per_bird_day * birds, denominator=birds,
                                  production=self)

    def _poultry_compute_egg_production_indicator_values(self):
        """Al cerrar la OF de Huevo sin Clasificar: % Ave-Día, Huevos Acumulados
        Ave-Día y Huevos Acumulados Ave-Alojada por lote, repartiendo el total de
        huevos del día (self.product_qty, fijado desde la creación de la OF en
        poultry.coop.close, sin depender del estado MRP en que quede) entre los
        lotes presentes en el galpón según su población viva ese día.

        % Ave-Día es una tasa diaria (huevos de este lote ese día / aves vivas ese
        día). Los dos acumulados son independientes entre sí: NO se derivan del %
        Ave-Día ya calculado, se recalculan cada día desde los mismos datos crudos.
        Ave-Día acumulado suma cada día huevos/aves VIVAS ese día. Ave-Alojada
        acumulado suma cada día huevos/aves ALOJADAS AL INICIO (fija, no baja con la
        mortalidad ni sube con nuevos Ingresos) — solo se calcula si el lote ya tiene
        un Cambio de Período a Producción registrado (poultry.batch.period_change_ids,
        que fija housed_bird_count/production_start_date) y la fecha es posterior a
        esa Fecha de Entrada en Producción; antes de eso no hay una base fija
        válida, porque el lote puede seguir recibiendo Ingresos o todavía no haber
        cambiado de galpón/período."""
        self.ensure_one()
        if not self.coop_close_id or not self.coop_id:
            return
        target_date = self._poultry_target_date()
        total_eggs = self.product_qty or 0.0
        if total_eggs <= 0:
            return

        lines, birds_by_line, total_birds = self._poultry_get_active_lines_and_birds(target_date)
        if not lines or total_birds <= 0:
            return

        Indicator = self.env['poultry.indicator'].sudo()
        rate_indicator = Indicator._poultry_legacy_indicator('egg_production', 'none')
        rate_original_indicator = Indicator._poultry_legacy_indicator('egg_production', 'original_rate')
        cumulative_live_indicator = Indicator._poultry_legacy_indicator('egg_production', 'live')
        cumulative_housed_indicator = Indicator._poultry_legacy_indicator('egg_production', 'housed')
        if not any((rate_indicator, rate_original_indicator, cumulative_live_indicator,
                    cumulative_housed_indicator)):
            return

        Value = self.env['poultry.batch.indicator.value'].sudo()
        # Uniforme por ave: mismo huevos/ave para todos los lotes que comparten el galpón.
        eggs_per_bird_day = total_eggs / total_birds

        for line in lines:
            birds = birds_by_line[line.id]
            if birds <= 0:
                continue
            batch_egg_share = eggs_per_bird_day * birds

            if rate_indicator:
                Value._set_value(line.batch_id, self.coop_id, target_date, rate_indicator,
                                  eggs_per_bird_day * 100.0,
                                  numerator=batch_egg_share * 100.0, denominator=birds,
                                  production=self)

            if rate_original_indicator and line.batch_id.bird_count:
                # % Postura sobre Aves Originales del Lote: misma cantidad de huevos
                # de hoy que arriba, pero contra la Cantidad de Aves del lote (fija,
                # no la población viva de hoy).
                postura_original_pct = (batch_egg_share / line.batch_id.bird_count) * 100.0
                Value._set_value(line.batch_id, self.coop_id, target_date, rate_original_indicator,
                                  postura_original_pct,
                                  numerator=batch_egg_share * 100.0, denominator=line.batch_id.bird_count,
                                  production=self)

            if cumulative_live_indicator:
                previous_total = self._poultry_previous_accumulated(
                    line.batch_id, cumulative_live_indicator, target_date)
                Value._set_value(line.batch_id, self.coop_id, target_date, cumulative_live_indicator,
                                  previous_total + eggs_per_bird_day,
                                  numerator=batch_egg_share, denominator=birds,
                                  production=self)

            if cumulative_housed_indicator:
                batch = line.batch_id
                # Solo se calcula si el lote ya tiene un Cambio de Período a
                # Producción registrado (poultry.batch.period_change_ids) y la fecha
                # es posterior a la Fecha de Entrada en Producción: antes de eso no
                # hay una base fija válida (el lote puede seguir recibiendo Ingresos).
                if (batch.housed_bird_count and batch.production_start_date
                        and target_date >= batch.production_start_date):
                    previous_total = self._poultry_previous_accumulated(
                        batch, cumulative_housed_indicator, target_date)
                    eggs_per_housed_bird = batch_egg_share / batch.housed_bird_count
                    Value._set_value(batch, self.coop_id, target_date, cumulative_housed_indicator,
                                      previous_total + eggs_per_housed_bird,
                                      numerator=batch_egg_share, denominator=batch.housed_bird_count,
                                      production=self)

    def _poultry_compute_mortality_indicator_values(self):
        """Indicadores reales de Mortandad (% diario y/o acumulados), a partir de los
        registros de poultry.mortality que generó esta OF (_poultry_sync_mortality).
        Reusa dead_count/live_bird_count/mortality_pct ya calculados en el propio
        registro (misma lógica de Aves Vivas de todo el módulo, sin recalcularla acá).
        Mismo patrón de acumulación que Producción de Huevos: 'none' = tasa diaria,
        'live'/'housed' = suma corrida sobre la población viva/alojada."""
        self.ensure_one()
        if not self.coop_close_id or not self.coop_id:
            return
        target_date = self._poultry_target_date()
        # Incluye tanto los registros generados por esta OF (_poultry_sync_mortality) como
        # los cargados a mano (production_id vacío) para este galpón en la fecha: la
        # mortandad del día de un lote es la suma de ambos.
        mortalities = self.env['poultry.mortality'].search([
            ('coop_id', '=', self.coop_id.id),
            ('date', '=', target_date),
            ('active', '=', True),
        ])
        if not mortalities:
            return
        # Agrupa por lote: suma de muertas del día y aves vivas al cierre del día
        # (live_bird_count es igual para todos los registros del mismo lote/fecha, porque
        # acumula toda la mortandad hasta la fecha).
        dead_by_batch = {}
        live_by_batch = {}
        for m in mortalities.filtered('batch_id'):
            dead_by_batch[m.batch_id] = dead_by_batch.get(m.batch_id, 0) + m.dead_count
            live_by_batch[m.batch_id] = m.live_bird_count
        if not dead_by_batch:
            return

        Indicator = self.env['poultry.indicator'].sudo()
        rate_indicator = Indicator._poultry_legacy_indicator('mortality', 'none')
        cumulative_live_indicator = Indicator._poultry_legacy_indicator('mortality', 'live')
        cumulative_housed_indicator = Indicator._poultry_legacy_indicator('mortality', 'housed')
        cumulative_original_indicator = Indicator._poultry_legacy_indicator('mortality', 'original_cumulative')
        # Cantidad de aves muertas (no %): categoría propia, sin ambigüedad con el
        # % semanal. El valor diario es la cantidad cruda; el agregado semanal es
        # la SUMA de los días (ver _poultry_aggregate_week_values).
        count_indicator = Indicator._poultry_legacy_indicator('mortality_count', 'none')
        if (not rate_indicator and not cumulative_live_indicator and not cumulative_housed_indicator
                and not cumulative_original_indicator and not count_indicator):
            return

        Value = self.env['poultry.batch.indicator.value'].sudo()
        for batch, dead in dead_by_batch.items():
            base = live_by_batch[batch] + dead
            if base <= 0:
                continue
            daily_pct = (dead / base * 100.0)

            if rate_indicator:
                Value._set_value(batch, self.coop_id, target_date, rate_indicator,
                                  daily_pct, numerator=dead * 100.0, denominator=base,
                                  production=self)

            if count_indicator:
                Value._set_value(batch, self.coop_id, target_date, count_indicator,
                                  float(dead), numerator=float(dead), denominator=1.0,
                                  production=self)

            if cumulative_live_indicator:
                previous_total = self._poultry_previous_accumulated(
                    batch, cumulative_live_indicator, target_date)
                Value._set_value(batch, self.coop_id, target_date, cumulative_live_indicator,
                                  previous_total + daily_pct,
                                  numerator=dead * 100.0, denominator=base, production=self)

            if cumulative_housed_indicator:
                if (batch.housed_bird_count and batch.production_start_date
                        and target_date >= batch.production_start_date):
                    previous_total = self._poultry_previous_accumulated(
                        batch, cumulative_housed_indicator, target_date)
                    dead_pct_housed = dead / batch.housed_bird_count * 100.0
                    Value._set_value(batch, self.coop_id, target_date, cumulative_housed_indicator,
                                      previous_total + dead_pct_housed,
                                      numerator=dead * 100.0, denominator=batch.housed_bird_count,
                                      production=self)

            if cumulative_original_indicator and batch.bird_count:
                previous_total = self._poultry_previous_accumulated(
                    batch, cumulative_original_indicator, target_date)
                dead_pct_original = dead / batch.bird_count * 100.0
                Value._set_value(batch, self.coop_id, target_date, cumulative_original_indicator,
                                  previous_total + dead_pct_original,
                                  numerator=dead * 100.0, denominator=batch.bird_count,
                                  production=self)

    def _poultry_compute_viability_indicator_values(self):
        """% de Viabilidad Acumulada (aves vivas hoy / Aves Alojadas x 100). A
        diferencia de los indicadores de mortandad (que suman contribuciones
        diarias), se calcula como una foto directa del estado del lote a la fecha
        -no depende del valor del día anterior- y el agregado semanal toma el
        último valor de la semana (estado), no un promedio de tasas diarias.

        Base: las Aves Alojadas (la foto a la Entrada en Producción, igual que la
        ficha del lote y el encabezado del reporte). Antes de la Entrada en
        Producción (crianza, sin Cambio de Período) cae a la Cantidad de Aves
        original: todavía no existe una base alojada válida.

        El indicador se acepta con tipo 'housed' (sobre Aves Alojadas, la
        semántica real) o 'original_cumulative' (el tipo histórico, por
        compatibilidad con configuraciones existentes); ambos agregan el semanal
        como último valor (estado)."""
        self.ensure_one()
        if not self.coop_close_id or not self.coop_id:
            return
        target_date = self._poultry_target_date()
        Indicator = self.env['poultry.indicator'].sudo()
        viability_indicator = Indicator._poultry_legacy_indicator('viability', ('housed', 'original_cumulative'))
        if not viability_indicator:
            return

        lines, birds_by_line, total_birds = self._poultry_get_active_lines_and_birds(target_date)
        if not lines:
            return

        Value = self.env['poultry.batch.indicator.value'].sudo()
        for line in lines:
            batch = line.batch_id
            base = (batch.housed_bird_count
                    if (batch.housed_bird_count and batch.production_start_date
                        and target_date >= batch.production_start_date)
                    else batch.bird_count)
            if not base:
                continue
            live_today = birds_by_line.get(line.id, 0)
            viability_pct = live_today / base * 100.0
            Value._set_value(batch, self.coop_id, target_date, viability_indicator,
                              viability_pct, numerator=live_today * 100.0, denominator=base,
                              production=self)

    def _poultry_compute_egg_mass_and_weight_indicator_values(self):
        """Indicadores reales de Masa de Huevo y Peso del Huevo Promedio, a partir de
        los Partes de Producción (poultry.egg.collection) incluidos en el Cierre de
        Galpón que generó esta OF -no de la OF en sí, que solo tiene el total de
        huevos sin distinguir peso por variante.

        Masa de Huevo Ave-Alojada Acumulada (kg): masa total del galpón (suma por
        variante de peso medio × cantidad producida, igual que
        poultry.egg.collection.total_weight pero agregado a nivel de todos los
        partes del cierre) repartida entre los lotes según su población viva ese
        día, acumulada en kg de masa de huevo por ave alojada -mismo patrón que
        Huevos Acumulados Ave-Alojada.

        Masa de Huevo Ave-Día (g/ave/día, tipo de acumulación Ninguno): la misma
        masa del galpón del día pero SIN acumular, expresada en gramos por ave
        viva ese día (como en las guías de genética, ej. 57.5 g). Al ser masa por
        ave, el valor del día es el mismo para todos los lotes del galpón (misma
        lógica de reparto uniforme por ave que % Ave-Día).

        Peso del Huevo Promedio (g/huevo): promedio ponderado del galpón ese día
        (por variante: peso medio × cantidad de huevos de esa variante, igual que
        poultry.egg.collection.average_weight_elaborated). No se reparte por
        población -es un atributo del huevo, no de cuántas aves hay-, así que se
        guarda el mismo valor para cada lote presente, con el mismo numerador/
        denominador (gramos totales / huevos con peso), para que el agregado
        semanal por lote siga siendo el promedio ponderado correcto (nunca
        promedio de promedios)."""
        self.ensure_one()
        if not self.coop_close_id or not self.coop_id:
            return
        target_date = self._poultry_target_date()

        collections = self.coop_close_id.egg_collection_ids.filtered(lambda c: c.state == 'done')
        measured_mass_grams = 0.0
        total_eggs_with_weight = 0.0
        total_all_eggs = 0.0
        for line in collections.mapped('line_ids'):
            total_all_eggs += line.total_produced_reference or 0.0
            if line.average_weight and line.total_produced_reference:
                measured_mass_grams += line.average_weight * line.total_produced_reference
                total_eggs_with_weight += line.total_produced_reference
        if measured_mass_grams <= 0:
            return
        avg_weight_g = measured_mass_grams / total_eggs_with_weight if total_eggs_with_weight else 0.0
        # Masa del día = Peso ESTIMADO del galpón: el Peso Medio Elaborado
        # extrapolado a TODOS los huevos (incluye variantes sin Peso Medio),
        # igual que Total Peso Estimado del Parte de Producción. Si todas las
        # variantes tienen peso, coincide exacto con el medido.
        total_mass_grams = avg_weight_g * total_all_eggs
        total_mass_kg = total_mass_grams / 1000.0

        lines, birds_by_line, total_birds = self._poultry_get_active_lines_and_birds(target_date)
        if not lines or total_birds <= 0:
            return

        Indicator = self.env['poultry.indicator'].sudo()
        mass_housed_indicator = Indicator._poultry_legacy_indicator('egg_mass', 'housed')
        mass_rate_indicator = Indicator._poultry_legacy_indicator('egg_mass', 'none')
        weight_indicator = Indicator._poultry_legacy_indicator('egg_weight', 'none')
        if not mass_housed_indicator and not mass_rate_indicator and not weight_indicator:
            return

        Value = self.env['poultry.batch.indicator.value'].sudo()
        mass_kg_per_bird_day = total_mass_kg / total_birds
        mass_g_per_bird_day = total_mass_grams / total_birds

        for line in lines:
            birds = birds_by_line[line.id]
            if birds <= 0:
                continue
            batch = line.batch_id

            if mass_housed_indicator:
                if (batch.housed_bird_count and batch.production_start_date
                        and target_date >= batch.production_start_date):
                    batch_mass_kg = mass_kg_per_bird_day * birds
                    previous_total = self._poultry_previous_accumulated(
                        batch, mass_housed_indicator, target_date)
                    kg_per_housed_bird = batch_mass_kg / batch.housed_bird_count
                    Value._set_value(batch, self.coop_id, target_date, mass_housed_indicator,
                                      previous_total + kg_per_housed_bird,
                                      numerator=batch_mass_kg, denominator=batch.housed_bird_count,
                                      production=self)

            if mass_rate_indicator:
                Value._set_value(batch, self.coop_id, target_date, mass_rate_indicator,
                                  mass_g_per_bird_day,
                                  numerator=mass_g_per_bird_day * birds, denominator=birds,
                                  production=self)

            if weight_indicator:
                # Numerador = gramos MEDIDOS (no extrapolados): el peso promedio es
                # un atributo del huevo pesado, y el agregado semanal Σnum/Σden debe
                # reproducir el promedio ponderado real de las variantes con peso.
                Value._set_value(batch, self.coop_id, target_date, weight_indicator,
                                  avg_weight_g,
                                  numerator=measured_mass_grams, denominator=total_eggs_with_weight,
                                  production=self)

    def _poultry_compute_feed_conversion_indicator_values(self):
        """Indicadores reales de Conversión Alimenticia: kg de Alimento consumido por
        Docena/Unidad de Huevos, y kg de Alimento por kg de Masa de Huevo -cada uno en
        variante Semanal (tasa diaria que se agrega por semana como suma/suma) y
        Acumulada desde Inicio de Producción (cociente de numerador y denominador
        acumulados por separado, mismo criterio de fecha que los indicadores 'sobre
        Aves Alojadas': solo corre desde production_start_date, nunca se suman
        razones diarias entre sí porque el denominador cambia día a día).

        Reutiliza el mismo consumo de alimento del galpón (kg) que
        _poultry_compute_consumption_indicator_values y la misma masa de huevo del
        galpón (kg) que _poultry_compute_egg_mass_and_weight_indicator_values,
        recalculados acá de forma independiente para no depender del orden en que se
        llamen los demás métodos de este mismo punto de entrada."""
        self.ensure_one()
        if not self.coop_close_id or not self.coop_id:
            return
        target_date = self._poultry_target_date()

        kg_uom = self._poultry_get_consumption_uom('uom.product_uom_kgm')
        feed_qty_kg = 0.0
        for move in self.move_raw_ids.filtered(lambda m: m.state != 'cancel'):
            # Tipo congelado en el movimiento (ver _poultry_compute_consumption_indicator_values).
            if move._poultry_consumption_type() != 'feed':
                continue
            qty = self._poultry_get_move_consumed_qty(move)
            feed_qty_kg += move.product_uom._compute_quantity(qty, kg_uom) if kg_uom else qty
        if feed_qty_kg <= 0:
            return

        total_eggs = self.product_qty or 0.0

        # Masa de huevo del día = Peso ESTIMADO (peso medio elaborado extrapolado a
        # todos los huevos), mismo criterio que Masa de Huevo Ave-Día/Ave-Alojada y
        # que Total Peso Estimado del Parte de Producción.
        collections = self.coop_close_id.egg_collection_ids.filtered(lambda c: c.state == 'done')
        measured_mass_grams = 0.0
        eggs_with_weight = 0.0
        all_eggs = 0.0
        for line in collections.mapped('line_ids'):
            all_eggs += line.total_produced_reference or 0.0
            if line.average_weight and line.total_produced_reference:
                measured_mass_grams += line.average_weight * line.total_produced_reference
                eggs_with_weight += line.total_produced_reference
        total_mass_grams = (measured_mass_grams / eggs_with_weight * all_eggs
                            if eggs_with_weight else 0.0)
        total_mass_kg = total_mass_grams / 1000.0

        lines, birds_by_line, total_birds = self._poultry_get_active_lines_and_birds(target_date)
        if not lines or total_birds <= 0:
            return

        Indicator = self.env['poultry.indicator'].sudo()
        feed_rate_indicator = Indicator._poultry_legacy_indicator('feed_conversion', 'none')
        feed_cumulative_indicator = Indicator._poultry_legacy_indicator('feed_conversion', 'ratio_cumulative')
        mass_rate_indicator = Indicator._poultry_legacy_indicator('feed_egg_mass_conversion', 'none')
        mass_cumulative_indicator = Indicator._poultry_legacy_indicator('feed_egg_mass_conversion', 'ratio_cumulative')
        if not any((feed_rate_indicator, feed_cumulative_indicator,
                    mass_rate_indicator, mass_cumulative_indicator)):
            return

        Value = self.env['poultry.batch.indicator.value'].sudo()
        feed_size_indicator = feed_rate_indicator or feed_cumulative_indicator
        egg_group_size = (feed_size_indicator.egg_group_size or 12) if feed_size_indicator else 12

        for line in lines:
            birds = birds_by_line[line.id]
            if birds <= 0:
                continue
            batch = line.batch_id
            share = birds / total_birds
            batch_feed_kg = feed_qty_kg * share
            batch_eggs = total_eggs * share
            batch_mass_kg = total_mass_kg * share
            batch_units = batch_eggs / egg_group_size if egg_group_size else 0.0
            in_production = (batch.housed_bird_count and batch.production_start_date
                              and target_date >= batch.production_start_date)

            if feed_rate_indicator and batch_units > 0:
                Value._set_value(batch, self.coop_id, target_date, feed_rate_indicator,
                                  batch_feed_kg / batch_units,
                                  numerator=batch_feed_kg, denominator=batch_units,
                                  production=self)

            if feed_cumulative_indicator and batch_units > 0 and in_production:
                previous = Value.search([
                    ('batch_id', '=', batch.id),
                    ('indicator_id', '=', feed_cumulative_indicator.id),
                    ('date', '<', target_date),
                ], order='date desc', limit=1)
                new_num = (previous.numerator if previous else 0.0) + batch_feed_kg
                new_denom = (previous.denominator if previous else 0.0) + batch_units
                Value._set_value(batch, self.coop_id, target_date, feed_cumulative_indicator,
                                  new_num / new_denom if new_denom else 0.0,
                                  numerator=new_num, denominator=new_denom,
                                  production=self)

            if mass_rate_indicator and batch_mass_kg > 0:
                Value._set_value(batch, self.coop_id, target_date, mass_rate_indicator,
                                  batch_feed_kg / batch_mass_kg,
                                  numerator=batch_feed_kg, denominator=batch_mass_kg,
                                  production=self)

            if mass_cumulative_indicator and batch_mass_kg > 0 and in_production:
                previous = Value.search([
                    ('batch_id', '=', batch.id),
                    ('indicator_id', '=', mass_cumulative_indicator.id),
                    ('date', '<', target_date),
                ], order='date desc', limit=1)
                new_num = (previous.numerator if previous else 0.0) + batch_feed_kg
                new_denom = (previous.denominator if previous else 0.0) + batch_mass_kg
                Value._set_value(batch, self.coop_id, target_date, mass_cumulative_indicator,
                                  new_num / new_denom if new_denom else 0.0,
                                  numerator=new_num, denominator=new_denom,
                                  production=self)

