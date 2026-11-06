# -*- coding: utf-8 -*-
{
    'name': 'Poultry Management',
    'version': '19.0.1.109.0',
    'category': 'Agriculture',
    'summary': 'Gestión integral de granjas de postura: producción, indicadores, sanidad y cobertura de stock',
    'description': """
        Gestión avícola sobre Odoo 19
        - Galpones, lotes de aves, genéticas y estándares de rendimiento por versión
        - Partes de producción por calibre y envase, en cajones, maples y huevos
        - Cierre de galpón con consumo de alimento y agua, y registro de mortandad
        - Indicadores reales por lote con fórmulas configurables
        - Seguimiento de estándares por semana de vida o calendario, con exportación a PDF y Excel
        - Semáforo de indicadores según el desvío contra el estándar
        - Planes de vacunación, cumplimiento sanitario y pesajes con uniformidad
        - App de campo instalable en el celular, con jaulas identificadas por QR
        - Análisis de facturas en huevos y cajones, con precio por cajón
        - Tablero de cobertura de stock según consumo y plazo del proveedor
    """,
    'author': 'aceleradora.la',
    'website': 'https://aceleradora.la',
    'depends': ['base', 'mrp', 'product', 'mail', 'hr', 'web', 'stock', 'purchase_stock', 'account'],
    'assets': {
        'web.assets_backend': [
            'poultry_management/static/src/css/poultry_stock_cover_dashboard.css',
            'poultry_management/static/src/css/poultry_standard_tracking_report.css',
            'poultry_management/static/src/js/poultry_dynamic_columns.js',
            'poultry_management/static/src/js/poultry_standard_tracking_report/poultry_standard_tracking_report.js',
            'poultry_management/static/src/js/poultry_standard_tracking_report/poultry_standard_tracking_report.xml',
            'poultry_management/static/src/weighing/poultry_weighing.js',
            'poultry_management/static/src/weighing/poultry_weighing.xml',
            'poultry_management/static/src/weighing/poultry_weighing.scss',
        ],
    },
    'data': [
        'security/poultry_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/genetics_data.xml',
        'data/poultry_config_parameters.xml',
        'views/uom_views.xml',
        'views/product_category_views.xml',
        'views/product_template_views.xml',
        'views/poultry_res_company_views.xml',
        'views/poultry_res_config_settings_views.xml',
        'views/poultry_stock_dashboard_views.xml',
        'views/poultry_indicator_views.xml',
        'views/poultry_genetics_standard_version_views.xml',
        'views/poultry_genetics_views.xml',
        'views/poultry_coop_views.xml',
        'views/poultry_batch_views.xml',
        'views/poultry_batch_coop_line_views.xml',
        'views/poultry_batch_indicator_value_views.xml',
        'views/poultry_coop_bom_views.xml',
        'report/poultry_egg_collection_report_templates.xml',
        'report/poultry_egg_collection_report.xml',
        'views/poultry_egg_collection_views.xml',
        'views/poultry_egg_collection_line_views.xml',
        'views/poultry_egg_collection_line_pivot_views.xml',
        'views/poultry_stock_move_views.xml',
        'views/poultry_account_invoice_report_views.xml',
        'views/poultry_coop_close_views.xml',
        'views/poultry_coop_close_wizard_views.xml',
        'views/poultry_mortality_views.xml',
        'views/poultry_cage_views.xml',
        'views/poultry_cage_wizard_views.xml',
        'report/poultry_cage_label_report.xml',
        'report/poultry_weight_sheet_report.xml',
        'views/poultry_weight_record_views.xml',
        'views/poultry_weight_wizard_views.xml',
        'views/poultry_vaccine_views.xml',
        'views/poultry_vaccination_plan_views.xml',
        'views/poultry_vaccination_views.xml',
        'views/poultry_vaccination_compliance_views.xml',
        'views/poultry_genetics_standard_views.xml',
        'views/mrp_bom_views.xml',
        'views/mrp_production_views.xml',
        'views/poultry_zero_mortality_wizard_views.xml',
        'views/poultry_batch_movement_views.xml',
        'views/poultry_menus.xml',
        'views/poultry_batch_period_change_views.xml',
        'views/poultry_batch_indicator_weekly_value_views.xml',
        'views/poultry_recompute_indicators_wizard_views.xml',
        'views/poultry_formula_check_wizard_views.xml',
        'reports/poultry_report_wizard_views.xml',
        'reports/poultry_reports.xml',
        'reports/poultry_standard_tracking_report_templates.xml',
        'reports/poultry_standard_tracking_report_actions.xml',
        'reports/poultry_standard_tracking_report_views.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
    'external_dependencies': {
        'python': ['xlsxwriter'],
    },
    'images': ['static/description/icon.svg'],
    'post_init_hook': 'post_init_renumber_collections',
}

