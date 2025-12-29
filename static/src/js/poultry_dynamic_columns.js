/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";
import { FormRenderer } from "@web/views/form/form_renderer";

// Patch para ListRenderer (columnas de la lista)
patch(ListRenderer.prototype, {
    setup() {
        super.setup();
        if (this.props.list && this.props.list.resModel === 'poultry.egg.collection.line') {
            this._updateDynamicColumnHeaders = this._updateDynamicColumnHeaders.bind(this);
        }
    },

    _updateDynamicColumnHeaders() {
        const table = this.el?.querySelector('table.o_list_table');
        if (!table) return;

        const headers = table.querySelectorAll('thead th');
        if (!headers.length) return;

        // Obtener valores desde el modelo
        let uom1Name = '';
        let uom2Name = '';
        let uom3Name = '';

        if (this.props.list && this.props.list.records && this.props.list.records.length > 0) {
            const firstRecord = this.props.list.records[0];
            uom1Name = firstRecord.data?.uom_1_name || '';
            uom2Name = firstRecord.data?.uom_2_name || '';
            uom3Name = firstRecord.data?.uom_3_name || '';
            
            // Si no están en el record, intentar desde las celdas
            if (!uom1Name) {
                const firstRow = table.querySelector('tbody tr[data-id]');
                if (firstRow) {
                    const allCells = firstRow.querySelectorAll('td');
                    allCells.forEach((cell) => {
                        const fieldName = cell.getAttribute('data-name') || cell.getAttribute('name');
                        if (fieldName === 'uom_1_name') {
                            uom1Name = cell.textContent?.trim() || '';
                        } else if (fieldName === 'uom_2_name') {
                            uom2Name = cell.textContent?.trim() || '';
                        } else if (fieldName === 'uom_3_name') {
                            uom3Name = cell.textContent?.trim() || '';
                        }
                    });
                }
            }
        }

        // Actualizar headers
        headers.forEach((header) => {
            const fieldName = header.getAttribute('data-name') || header.getAttribute('name');
            if (!fieldName) return;

            let headerText = header.querySelector('.o_column_title') || header.querySelector('span') || header;

            if (fieldName === 'initial_box' && uom1Name) {
                headerText.textContent = `${uom1Name} Inicial`;
            } else if (fieldName === 'initial_map' && uom2Name) {
                headerText.textContent = `${uom2Name} Inicial`;
            } else if (fieldName === 'initial_egg' && uom3Name) {
                headerText.textContent = `${uom3Name} Inicial`;
            } else if (fieldName === 'final_box' && uom1Name) {
                headerText.textContent = `${uom1Name} Final`;
            } else if (fieldName === 'final_map' && uom2Name) {
                headerText.textContent = `${uom2Name} Final`;
            } else if (fieldName === 'final_egg' && uom3Name) {
                headerText.textContent = `${uom3Name} Final`;
            }
        });
    },

    onMounted() {
        super.onMounted();
        if (this.props.list && this.props.list.resModel === 'poultry.egg.collection.line') {
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

// Patch para FormRenderer (labels de totales)
patch(FormRenderer.prototype, {
    setup() {
        super.setup();
        if (this.props.resModel === 'poultry.egg.collection') {
            this._updateTotalLabels = this._updateTotalLabels.bind(this);
        }
    },

    _updateTotalLabels() {
        const form = this.el?.querySelector('.o_form_view');
        if (!form) return;

        const record = this.props.record;
        if (!record || !record.data) return;

        const uom1Name = record.data.uom_1_name || '';
        const uom2Name = record.data.uom_2_name || '';
        const uom3Name = record.data.uom_3_name || '';

        // Actualizar labels de totales iniciales
        const totalInitialBoxesLabel = form.querySelector('label[for="total_initial_boxes"]');
        if (totalInitialBoxesLabel && uom1Name) {
            totalInitialBoxesLabel.textContent = `Total Inicial ${uom1Name}`;
        }
        const totalInitialMapsLabel = form.querySelector('label[for="total_initial_maps"]');
        if (totalInitialMapsLabel && uom2Name) {
            totalInitialMapsLabel.textContent = `Total Inicial ${uom2Name}`;
        }
        const totalInitialEggsLabel = form.querySelector('label[for="total_initial_eggs"]');
        if (totalInitialEggsLabel && uom3Name) {
            totalInitialEggsLabel.textContent = `Total Inicial ${uom3Name}`;
        }

        // Actualizar labels de totales finales
        const totalFinalBoxesLabel = form.querySelector('label[for="total_final_boxes"]');
        if (totalFinalBoxesLabel && uom1Name) {
            totalFinalBoxesLabel.textContent = `Total Final ${uom1Name}`;
        }
        const totalFinalMapsLabel = form.querySelector('label[for="total_final_maps"]');
        if (totalFinalMapsLabel && uom2Name) {
            totalFinalMapsLabel.textContent = `Total Final ${uom2Name}`;
        }
        const totalFinalEggsLabel = form.querySelector('label[for="total_final_eggs"]');
        if (totalFinalEggsLabel && uom3Name) {
            totalFinalEggsLabel.textContent = `Total Final ${uom3Name}`;
        }

        // Actualizar labels de totales producidos
        const totalProducedBoxesLabel = form.querySelector('label[for="total_produced_boxes"]');
        if (totalProducedBoxesLabel && uom1Name) {
            totalProducedBoxesLabel.textContent = `Total Producido ${uom1Name}`;
        }
        const totalProducedMapsLabel = form.querySelector('label[for="total_produced_maps"]');
        if (totalProducedMapsLabel && uom2Name) {
            totalProducedMapsLabel.textContent = `Total Producido ${uom2Name}`;
        }
        const totalProducedEggsLabel = form.querySelector('label[for="total_produced_eggs"]');
        if (totalProducedEggsLabel && uom3Name) {
            totalProducedEggsLabel.textContent = `Total Producido ${uom3Name}`;
        }
    },

    onMounted() {
        super.onMounted();
        if (this.props.resModel === 'poultry.egg.collection') {
            setTimeout(() => this._updateTotalLabels(), 100);
            setTimeout(() => this._updateTotalLabels(), 500);
        }
    },

    onWillUpdateProps(nextProps) {
        super.onWillUpdateProps(nextProps);
        if (nextProps.resModel === 'poultry.egg.collection') {
            setTimeout(() => this._updateTotalLabels(), 100);
        }
    },
});
