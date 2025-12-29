/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";

patch(ListRenderer.prototype, {
    setup() {
        super.setup();
        if (this.props.list && this.props.list.resModel === 'poultry.egg.collection.line') {
            this._updateDynamicColumnHeaders = this._updateDynamicColumnHeaders.bind(this);
        }
    },

    _updateDynamicColumnHeaders() {
        // Buscar la tabla
        const table = this.el?.querySelector('table.o_list_table');
        if (!table) return;

        const headers = table.querySelectorAll('thead th');
        if (!headers.length) return;

        // Obtener los nombres de las unidades desde los datos del primer registro
        const firstRow = table.querySelector('tbody tr[data-id]');
        if (!firstRow) return;

        // Buscar los valores de uom_X_name en las celdas (pueden estar en atributos o en el contenido)
        let uom1Name = '';
        let uom2Name = '';
        let uom3Name = '';

        // Intentar obtener desde las celdas invisibles
        const allCells = firstRow.querySelectorAll('td');
        allCells.forEach((cell) => {
            const fieldName = cell.getAttribute('data-name') || cell.getAttribute('name');
            if (fieldName === 'uom_1_name') {
                uom1Name = cell.textContent?.trim() || cell.getAttribute('title') || '';
            } else if (fieldName === 'uom_2_name') {
                uom2Name = cell.textContent?.trim() || cell.getAttribute('title') || '';
            } else if (fieldName === 'uom_3_name') {
                uom3Name = cell.textContent?.trim() || cell.getAttribute('title') || '';
            }
        });

        // Si no se encontraron, intentar desde el modelo
        if (!uom1Name && this.props.list && this.props.list.records && this.props.list.records.length > 0) {
            const firstRecord = this.props.list.records[0];
            uom1Name = firstRecord.data?.uom_1_name || '';
            uom2Name = firstRecord.data?.uom_2_name || '';
            uom3Name = firstRecord.data?.uom_3_name || '';
        }

        // Actualizar headers
        headers.forEach((header) => {
            const fieldName = header.getAttribute('data-name') || header.getAttribute('name');
            if (!fieldName) return;

            if (fieldName === 'initial_box' && uom1Name) {
                const headerText = header.querySelector('.o_column_title') || header;
                headerText.textContent = `${uom1Name} Inicial`;
            } else if (fieldName === 'initial_map' && uom2Name) {
                const headerText = header.querySelector('.o_column_title') || header;
                headerText.textContent = `${uom2Name} Inicial`;
            } else if (fieldName === 'initial_egg' && uom3Name) {
                const headerText = header.querySelector('.o_column_title') || header;
                headerText.textContent = `${uom3Name} Inicial`;
            } else if (fieldName === 'final_box' && uom1Name) {
                const headerText = header.querySelector('.o_column_title') || header;
                headerText.textContent = `${uom1Name} Final`;
            } else if (fieldName === 'final_map' && uom2Name) {
                const headerText = header.querySelector('.o_column_title') || header;
                headerText.textContent = `${uom2Name} Final`;
            } else if (fieldName === 'final_egg' && uom3Name) {
                const headerText = header.querySelector('.o_column_title') || header;
                headerText.textContent = `${uom3Name} Final`;
            }
        });
    },

    onMounted() {
        super.onMounted();
        if (this.props.list && this.props.list.resModel === 'poultry.egg.collection.line') {
            // Intentar múltiples veces para asegurar que se actualice
            setTimeout(() => this._updateDynamicColumnHeaders(), 100);
            setTimeout(() => this._updateDynamicColumnHeaders(), 500);
            setTimeout(() => this._updateDynamicColumnHeaders(), 1000);
        }
    },

    onWillUpdateProps(nextProps) {
        super.onWillUpdateProps(nextProps);
        if (nextProps.list && nextProps.list.resModel === 'poultry.egg.collection.line') {
            setTimeout(() => this._updateDynamicColumnHeaders(), 100);
        }
    },
});

