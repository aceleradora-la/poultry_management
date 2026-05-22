# -*- coding: utf-8 -*-
"""
Tablero de cobertura de stock (solo productos comprables): consumo en ventana configurable
y semáforo según plazo del primer proveedor, días para comprar y margen PO (buffer).

Incluye segunda línea con stock pronosticado (``virtual_available`` de Odoo) y mismo criterio de color.
"""
from collections import defaultdict
from datetime import timedelta

from odoo import api, fields, models
from odoo.tools.float_utils import float_compare, float_is_zero, float_round

# Orden estándar de product.supplierinfo (mismo criterio que el planificador al tomar el primero).
_SUPPLIERINFO_ORDER = 'sequence, min_qty desc, price, id'
# Valor alto para ordenar al final (menos urgente) en columnas con orden ascendente por días.
_SORT_TAIL = 1e9
# Orden fijo de columnas Kanban al agrupar por semáforo (Odoo suele ordenar por conteo al filtrar).
_SIGNAL_GROUP_READ_ORDER = {'red': 0, 'yellow': 1, 'green': 2, 'neutral': 3}

_COVER_SIGNAL_SEL = [
    ('red', 'Rojo'),
    ('yellow', 'Amarillo'),
    ('green', 'Verde'),
    ('neutral', 'Sin datos'),
]


class ProductProduct(models.Model):
    _inherit = 'product.product'

    poultry_cover_daily_avg = fields.Float(
        string='Consumo diario (ventana)',
        digits='Product Unit of Measure',
        compute='_compute_poultry_cover_metrics',
        help='Promedio diario de salidas desde stock interno en la ventana configurada (UdM del producto).',
    )
    poultry_cover_days = fields.Float(
        string='Días de cobertura (real)',
        compute='_compute_poultry_cover_metrics',
        digits=(16, 2),
        help='Cantidad a la mano / consumo diario. Vacío si no hubo consumo en el período.',
    )
    poultry_cover_days_display = fields.Char(
        string='Días cobertura (real)',
        compute='_compute_poultry_cover_metrics',
    )
    poultry_cover_signal = fields.Selection(
        selection=_COVER_SIGNAL_SEL,
        string='Semáforo cobertura (real)',
        compute='_compute_poultry_cover_metrics',
        store=True,
        index=True,
        group_expand='_group_expand_poultry_cover_signal',
    )
    poultry_cover_sort_days = fields.Float(
        string='Orden cobertura (días)',
        compute='_compute_poultry_cover_metrics',
        store=True,
        index=True,
        help='Clave para ordenar el tablero Kanban: menor = más urgente (solo uso interno).',
    )
    poultry_cover_forecast_days = fields.Float(
        string='Días cobertura (pronóstico)',
        compute='_compute_poultry_cover_metrics',
        digits=(16, 2),
        help='Cantidad pronosticada (virtual_available) / consumo diario.',
    )
    poultry_cover_forecast_days_display = fields.Char(
        string='Días cobertura pronóstico',
        compute='_compute_poultry_cover_metrics',
    )
    poultry_cover_forecast_signal = fields.Selection(
        selection=_COVER_SIGNAL_SEL,
        string='Semáforo cobertura (pronóstico)',
        compute='_compute_poultry_cover_metrics',
    )

    @staticmethod
    def _poultry_cover_line_metrics(daily, rounding, qty, plazo_th, tope_amarillo_th):
        """Una línea semáforo: (días_float_o_False, texto, señal, sort_key)."""
        if float_is_zero(daily, precision_rounding=rounding):
            if float_is_zero(qty, precision_rounding=rounding):
                return False, '—', 'neutral', _SORT_TAIL
            return False, '∞', 'green', _SORT_TAIL
        days = qty / daily if daily else 0.0
        days_rounded = float_round(days, precision_rounding=0.01)
        display = str(days_rounded)
        sort_key = float(days_rounded)
        if float_compare(days, tope_amarillo_th, precision_digits=2) > 0:
            sig = 'green'
        elif float_compare(days, plazo_th, precision_digits=2) > 0:
            sig = 'yellow'
        else:
            sig = 'red'
        return days_rounded, display, sig, sort_key

    def _poultry_first_supplierinfo(self):
        """Primer vendor line como lista ordenada del modelo (sequence, min_qty desc, …)."""
        self.ensure_one()
        SupplierInfo = self.env['product.supplierinfo'].sudo()
        company = self.env.company
        domain = [
            ('product_tmpl_id', '=', self.product_tmpl_id.id),
            '|', ('product_id', '=', False), ('product_id', '=', self.id),
            '|', ('company_id', '=', False), ('company_id', '=', company.id),
        ]
        return SupplierInfo.search(domain, order=_SUPPLIERINFO_ORDER, limit=1)

    def _poultry_odoo_cover_threshold_days(self):
        """Límites del semáforo: (plazo_proveedor, tope_amarillo).

        * **Plazo proveedor**: ``delay`` del primer ``product.supplierinfo`` (0 si no hay).
        * **Delay interno**: ``days_to_purchase`` de la compañía (``purchase_stock``).
        * **Buffer**: ``po_lead`` si ``purchase.use_po_lead`` está activo; si no, 0.

        - Rojo: días de cobertura ``<=`` plazo proveedor.
        - Amarillo: ``>`` plazo y ``<=`` plazo + delay + buffer.
        - Verde: ``>`` plazo + delay + buffer.

        Si delay + buffer sería igual al solo plazo (sin delay interno ni buffer), se usa 0,01 días
        mínimos en el bloque interno para conservar una banda amarilla mínima.
        """
        self.ensure_one()
        company = self.env.company
        info = self._poultry_first_supplierinfo()
        plazo = float(info.delay) if info else 0.0

        days_purchase = 0.0
        if 'days_to_purchase' in company._fields:
            days_purchase = float(company.days_to_purchase or 0.0)

        use_po_lead = self.env['ir.config_parameter'].sudo().get_param('purchase.use_po_lead') == 'True'
        buffer_po = float(company.po_lead or 0.0) if use_po_lead else 0.0

        bloque_interno = days_purchase + buffer_po
        if bloque_interno <= 0.0:
            bloque_interno = 0.01

        tope_amarillo = plazo + bloque_interno
        return plazo, tope_amarillo

    def _poultry_sum_outgoing_product_uom(self, product_ids, window_days):
        """Salidas done en ventana: stock interno → fuera de stock interno útil.

        No cuenta traspasos interno→interno ni salidas hacia **tránsito** (suele ser paso intermedio
        de entregas/recepciones y no es consumo real).
        """
        if not product_ids:
            return {}
        window_days = max(float(window_days or 7.0), 1.0)
        date_from = fields.Datetime.now() - timedelta(days=window_days)
        domain = [
            ('state', '=', 'done'),
            '|',
            ('date', '>=', date_from),
            ('move_id.date', '>=', date_from),
            ('product_id', 'in', list(product_ids)),
            ('location_id.usage', '=', 'internal'),
            ('location_dest_id.usage', 'not in', ('internal', 'transit')),
        ]
        MoveLine = self.env['stock.move.line'].sudo()
        groups = MoveLine.read_group(domain, ['quantity_product_uom:sum'], ['product_id'])
        result = {}
        for row in groups:
            p = row.get('product_id')
            if not p:
                continue
            pid = p[0] if isinstance(p, (list, tuple)) else p
            qty = None
            for key, val in row.items():
                if key == 'product_id' or key == '__domain':
                    continue
                if key.endswith('_sum'):
                    qty = val
                    break
            if qty is None:
                qty = row.get('quantity_product_uom') or 0.0
            result[pid] = qty or 0.0
        return result

    @api.depends_context('company')
    @api.depends(
        'qty_available',
        'virtual_available',
        'uom_id',
        'product_tmpl_id.poultry_cover_window_days',
        'product_tmpl_id.categ_id.poultry_cover_window_days',
        'product_tmpl_id.seller_ids',
        'product_tmpl_id.seller_ids.delay',
        'product_tmpl_id.seller_ids.sequence',
        'product_tmpl_id.seller_ids.min_qty',
        'product_tmpl_id.seller_ids.product_id',
        'product_tmpl_id.seller_ids.company_id',
        'product_tmpl_id.purchase_ok',
    )
    def _compute_poultry_cover_metrics(self):
        buckets = defaultdict(list)
        for product in self:
            tmpl = product.product_tmpl_id
            wd = float(tmpl._poultry_effective_cover_window_days())
            buckets[wd].append(product.id)

        consumption = {}
        for window_days, pids in buckets.items():
            consumption.update(self._poultry_sum_outgoing_product_uom(pids, window_days))

        for product in self:
            tmpl = product.product_tmpl_id
            rounding = product.uom_id.rounding or 0.0001
            window = tmpl._poultry_effective_cover_window_days()
            plazo_th, tope_amarillo_th = product._poultry_odoo_cover_threshold_days()
            total_out = consumption.get(product.id, 0.0)
            daily = total_out / window if window else 0.0
            product.poultry_cover_daily_avg = float_round(daily, precision_rounding=rounding)

            qty_real = product.qty_available
            qty_fcst = product.virtual_available

            dr, dstr_r, sig_r, sort_r = self._poultry_cover_line_metrics(
                daily, rounding, qty_real, plazo_th, tope_amarillo_th
            )
            df, dstr_f, sig_f, _ = self._poultry_cover_line_metrics(
                daily, rounding, qty_fcst, plazo_th, tope_amarillo_th
            )

            product.poultry_cover_days = dr
            product.poultry_cover_days_display = dstr_r
            product.poultry_cover_signal = sig_r
            product.poultry_cover_sort_days = sort_r

            product.poultry_cover_forecast_days = df
            product.poultry_cover_forecast_days_display = dstr_f
            product.poultry_cover_forecast_signal = sig_f

    @api.model
    def _group_expand_poultry_cover_signal(self, groups, domain, order):
        """Columnas Kanban fijas (rojo → amarillo → verde); sin datos queda fuera del dominio del tablero."""
        return ['red', 'yellow', 'green']

    @api.model
    def read_group(self, domain, fields, groupby, **kwargs):
        """Fija el orden de columnas Rojo → Amarillo → Verde → Sin datos al agrupar por semáforo.

        Sin esto, el cliente ordena grupos por nº de registros (y empata alfabéticamente: Amarillo antes que Rojo).
        """
        rows = super().read_group(domain, fields, groupby, **kwargs)
        if not groupby:
            return rows
        first = groupby[0] if isinstance(groupby, (list, tuple)) else groupby
        field_name = first.split(':')[0] if isinstance(first, str) else first
        if field_name != 'poultry_cover_signal':
            return rows

        def _signal_sort_key(row):
            val = row.get('poultry_cover_signal')
            if val is False or val is None:
                return _SIGNAL_GROUP_READ_ORDER['neutral']
            if isinstance(val, (list, tuple)):
                val = val[0]
            return _SIGNAL_GROUP_READ_ORDER.get(val, 99)

        return sorted(rows, key=_signal_sort_key)

    @api.model
    def action_open_poultry_stock_dashboard(self):
        """Solo Kanban: agrupación y orden por semáforo real; tarjeta muestra también pronóstico."""
        domain = [
            ('is_storable', '=', True),
            ('active', '=', True),
            ('purchase_ok', '=', True),
        ]
        cats = self.env.company.poultry_stock_dashboard_category_ids
        if cats:
            domain.append(('categ_id', 'child_of', cats.ids))
        # Refrescar semáforos almacenados antes de filtrar por color (evita columnas mezcladas en 1ª carga).
        products = self.search(domain)
        if products:
            products._compute_poultry_cover_metrics()
        domain.append(('poultry_cover_signal', 'in', ('red', 'yellow', 'green')))
        kanban_view = self.env.ref('poultry_management.product_product_kanban_poultry_cover')
        search_view = self.env.ref('poultry_management.product_product_search_poultry_cover')
        return {
            'type': 'ir.actions.act_window',
            'name': 'Cobertura de stock',
            'res_model': 'product.product',
            'view_mode': 'kanban',
            'views': [(kanban_view.id, 'kanban')],
            'search_view_id': search_view.id,
            'domain': domain,
            'context': {
                'search_default_poultry_cover_tablero_con_datos': 1,
                'group_by': ['poultry_cover_signal'],
            },
        }
