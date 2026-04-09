# -*- coding: utf-8 -*-
{
    'name': 'Poultry Management',
    'version': '18.0.1.7.0',
    'category': 'Agriculture',
    'summary': 'Gestión de Granjas de Huevos y Pollos',
    'description': """
        Módulo para la gestión completa de granjas avícolas
        - Gestión de Galpones con capacidad y tamaño
        - Gestión de Lotes de Aves con genética y asignación
        - Lista de Materiales de Alimento Balanceado por galpón
        - Integración con Órdenes de Fabricación
    """,
    'author': 'aceleradora.la',
    'website': 'https://www.tuempresa.com',
    'depends': ['base', 'mrp', 'product', 'mail', 'hr', 'web', 'stock'],
    'assets': {
        # JavaScript dinámico desactivado - usando nombres fijos ahora
        # 'web.assets_backend': [
        #     'poultry_management/static/src/js/poultry_dynamic_columns.js',
        # ],
    },
    'data': [
        'security/poultry_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/genetics_data.xml',
        'data/poultry_config_parameters.xml',
        'views/uom_views.xml',
        'views/product_template_views.xml',
        'views/poultry_genetics_views.xml',
        'views/poultry_coop_views.xml',
        'views/poultry_batch_views.xml',
        'views/poultry_coop_bom_views.xml',
        'report/poultry_egg_collection_report_templates.xml',
        'report/poultry_egg_collection_report.xml',
        'views/poultry_egg_collection_views.xml',
        'views/poultry_egg_collection_line_views.xml',
        'views/poultry_egg_collection_line_pivot_views.xml',
        'views/poultry_stock_move_views.xml',
        'views/poultry_coop_close_views.xml',
        'views/poultry_coop_close_wizard_views.xml',
        'views/poultry_mortality_views.xml',
        'views/poultry_genetics_standard_views.xml',
        'views/mrp_production_views.xml',
        'views/poultry_menus.xml',
        'reports/poultry_report_wizard_views.xml',
        'reports/poultry_reports.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
    'images': ['static/description/icon.svg'],
    'post_init_hook': 'post_init_renumber_collections',
}

